"""Aleph OCR v0.4: one capture, one faithful reading, editable text."""
from pathlib import Path
import time

from PIL import Image
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel,
    QPushButton, QVBoxLayout, QHBoxLayout, QSplitter, QTextEdit, QFileDialog,
    QInputDialog, QLineEdit, QMenu, QMessageBox, QDialog, QListWidget)

from core import ASSETS, Document, Options, clean_text, hebrew_typography, probable_overlap, repair_mixed_rtl, save_text, without_nikud
from domain.session import CaptureRecord, RawReading
from domain.text import edit_hidden
from ocr.faithful import FaithfulWorker
from quick import GlobalHotkeys
from widgets import PageView, app_icon
from version import VERSION
from .capture import CaptureController
from .i18n import tr


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings('AlephOCR', 'Quick')
        self.language = self.settings.value('language', 'he')
        if self.language not in ('he', 'fr', 'en'):
            self.language = 'he'
        self.records = []
        self.current_index = -1
        self.current_image = None
        self.document = None
        self.page = 0
        self.worker = None
        self._ocr_target = None
        self._hotkeys = None
        self._text_updating = False
        self._buttons = []
        self._build()
        self.capture = CaptureController(self)
        self.capture.captured.connect(self.receive_capture)
        self.capture.stateChanged.connect(self.update_actions)
        self.apply_preferences()
        self.resize(1160, 760)
        self.setMinimumSize(700, 490)
        self.setAcceptDrops(True)
        self.status.setText(self.t('ready') + ' · ' + self.t('privacy'))

    def t(self, key, **values):
        return tr(key, self.language).format(**values)

    @property
    def current_record(self):
        return self.records[self.current_index] if 0 <= self.current_index < len(self.records) else None

    def _button(self, key, callback, layout, primary=False, compact=False):
        button = QPushButton(self.t(key))
        button.clicked.connect(callback)
        if primary:
            button.setObjectName('primary')
        if compact:
            button.setFixedSize(32, 32)
            button.setStyleSheet('QPushButton { padding:0; font-size:17px; }')
        layout.addWidget(button)
        self._buttons.append((button, key))
        return button

    def _build(self):
        self.setWindowIcon(app_icon())
        self.setWindowTitle(f'Aleph OCR {VERSION}')
        root = QWidget()
        root.setObjectName('v04Root')
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 11)
        outer.setSpacing(11)

        top = QHBoxLayout()
        brand = QLabel('Aleph OCR')
        brand.setObjectName('brand')
        top.addWidget(brand)
        self.badge = QLabel(self.t('faithful'))
        self.badge.setObjectName('badge')
        top.addWidget(self.badge)
        top.addStretch()
        self.open_button = self._button('open_short', self.open_dialog, top)
        self.capture_button = self._button('capture', self.capture_action, top, primary=True)
        self.window_button = self._button('window', self.capture_window_action, top)
        self.recognize_button = self._button('read', self.recognize, top)
        self.copy_button = self._button('copy_short', self.copy_text, top)
        self.export_button = self._button('export', self.show_export_menu, top)
        self.export_button.setToolTip(self.t('text_title'))
        self.history_button = self._button('history', self.show_history, top)
        self.settings_button = self._button('settings', self.show_settings, top)
        # Visual hierarchy: capture actions stay strong, utilities stay subtle.
        for action in (self.open_button, self.export_button, self.history_button, self.settings_button):
            action.setObjectName('subtle')
        outer.addLayout(top)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(self.splitter, 1)
        source = QFrame()
        source.setObjectName('panel')
        left = QVBoxLayout(source)
        left.setContentsMargins(14, 14, 14, 14)
        left.setSpacing(9)
        source_heading = QHBoxLayout()
        self.source_title = QLabel(self.t('source_title'))
        self.source_title.setObjectName('panelTitle')
        source_heading.addWidget(self.source_title)
        source_heading.addStretch()
        self.document_name = QLabel('')
        self.document_name.setObjectName('muted')
        self.document_name.setMaximumWidth(240)
        self.document_name.setToolTip(self.t('source_hint'))
        source_heading.addWidget(self.document_name)
        left.addLayout(source_heading)

        local = QHBoxLayout()
        self.page_label = QLabel('')
        self.page_label.setObjectName('muted')
        local.addWidget(self.page_label)
        self.previous_button = self._button('previous_page', lambda: self.navigate(-1), local, compact=True)
        self.previous_button.setText('‹')
        self.next_button = self._button('next_page', lambda: self.navigate(1), local, compact=True)
        self.next_button.setText('›')
        local.addStretch()
        self.zoom_out = self._button('zoom_help', lambda: self.image_panel.zoom(1 / 1.2), local, compact=True)
        self.zoom_out.setText('−')
        self.zoom_label = QLabel('100 %')
        self.zoom_label.setObjectName('muted')
        self.zoom_label.setMinimumWidth(46)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        local.addWidget(self.zoom_label)
        self.zoom_in = self._button('zoom_help', lambda: self.image_panel.zoom(1.2), local, compact=True)
        self.zoom_in.setText('+')
        self.fit_button = self._button('fit', self._fit, local)
        self.fit_button.setToolTip(self.t('zoom_help'))
        left.addLayout(local)

        self.image_panel = PageView()
        self.image_panel.zoomChanged.connect(lambda value: self.zoom_label.setText(f'{value} %'))
        self.image_panel.selectionChanged.connect(self.update_actions)
        self.image_panel.setToolTip(self.t('selection_hint') + '\n' + self.t('zoom_help'))
        left.addWidget(self.image_panel, 1)
        image_actions = QHBoxLayout()
        self.image_hint = QLabel(self.t('source_hint'))
        self.image_hint.setObjectName('muted')
        self.image_hint.setWordWrap(True)
        image_actions.addWidget(self.image_hint, 1)
        self.save_image_button = self._button('save_image', self.save_image, image_actions)
        left.addLayout(image_actions)
        self.splitter.addWidget(source)

        text_panel = QFrame()
        text_panel.setObjectName('panel')
        right = QVBoxLayout(text_panel)
        right.setContentsMargins(14, 14, 14, 14)
        right.setSpacing(9)
        text_heading = QHBoxLayout()
        self.text_title = QLabel(self.t('text_title'))
        self.text_title.setObjectName('panelTitle')
        text_heading.addWidget(self.text_title)
        text_heading.addStretch()
        self.raw_button = self._button('raw_view', self.view_raw, text_heading)
        self.raw_button.setObjectName('subtle')
        right.addLayout(text_heading)
        self.editor = QTextEdit()
        self.editor.setObjectName('hebrewEditor')
        self.editor.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.editor.setPlaceholderText(self.t('editor'))
        self.editor.textChanged.connect(self._editor_changed)
        right.addWidget(self.editor, 1)
        text_actions = QHBoxLayout()
        self.text_count = QLabel('')
        self.text_count.setObjectName('muted')
        text_actions.addWidget(self.text_count)
        text_actions.addStretch()
        self.copy_text_button = self._button('copy_short', self.copy_text, text_actions)
        self.export_text_button = self._button('export', self.show_export_menu, text_actions)
        right.addLayout(text_actions)
        self.splitter.addWidget(text_panel)
        self.splitter.setSizes([610, 520])

        footer = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName('muted')
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.timing_label = QLabel('')
        self.timing_label.setObjectName('muted')
        footer.addWidget(self.timing_label)
        outer.addLayout(footer)
        QShortcut(QKeySequence('Ctrl+O'), self).activated.connect(self.open_dialog)
        QShortcut(QKeySequence('Ctrl+Return'), self).activated.connect(self.recognize)
        QShortcut(QKeySequence('Ctrl+Shift+C'), self).activated.connect(self.copy_text)

    def _fit(self):
        self.image_panel.fit_page()

    def apply_preferences(self):
        value = self.settings.value('language', 'he')
        self.language = value if value in ('he', 'fr', 'en') else 'he'
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.language == 'he'
                                else Qt.LayoutDirection.LeftToRight)
        self.editor.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        enabled = self.settings.value('v04_always_on_top', False, type=bool)
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != enabled:
            maximized = self.isMaximized()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
            if self.isVisible():
                self.showMaximized() if maximized else self.showNormal()
        self.editor.setFont(QFont(self.settings.value('font', 'Arial'),
                                  self.settings.value('font_size', 18, type=int)))
        self.install_hotkey()
        for button, key in self._buttons:
            if button in (self.previous_button, self.next_button, self.zoom_out, self.zoom_in):
                button.setToolTip(self.t(key))
            else:
                button.setText(self.t(key))
        for button, symbol in ((self.previous_button, '‹'), (self.next_button, '›'),
                               (self.zoom_out, '−'), (self.zoom_in, '+')):
            button.setText(symbol)
        self.source_title.setText(self.t('source_title'))
        self.text_title.setText(self.t('text_title'))
        self.badge.setText(self.t('faithful'))
        self.image_hint.setText(self.t('source_hint'))
        self.editor.setPlaceholderText(self.t('editor'))
        record = self.current_record
        if record and self.nikud_mode() == 'remove' and self.settings.value('v04_last_nikud', 'keep') != 'remove':
            record.edited_text = without_nikud(record.edited_text)
        self.settings.setValue('v04_last_nikud', self.nikud_mode())
        self._show_record_text()
        self.update_actions()

    def install_hotkey(self):
        if self._hotkeys:
            QApplication.instance().removeNativeEventFilter(self._hotkeys)
            self._hotkeys.close()
        sequence = self.settings.value('v04_shortcut', 'Ctrl+Shift+O')
        self._hotkeys = GlobalHotkeys({0xA401: self.capture.begin_selection}, {0xA401: sequence})
        QApplication.instance().installNativeEventFilter(self._hotkeys)
        if QApplication.platformName() != 'offscreen' and not self._hotkeys.registered:
            self.status.setText(self.t('shortcut_unavailable'))

    def nikud_mode(self):
        return self.settings.value('v04_nikud', 'keep')

    def v04_languages(self):
        script = self.settings.value('v04_script', 'square')
        base = 'heb_rashi' if script == 'rashi' else 'heb'
        latin = []
        if self.settings.value('v04_eng', False, type=bool):
            latin.append('eng')
        if self.settings.value('v04_fra', False, type=bool):
            latin.append('fra')
        return tuple([base] + latin)

    def v04_profile(self):
        value = self.settings.value('v04_profile', 'torah')
        return value if value in ('torah', 'general') else 'torah'

    def join_lines_enabled(self):
        return self.settings.value('v04_join_lines', True, type=bool)

    def _show_record_text(self):
        record = self.current_record
        text = record.edited_text if record else ''
        if self.nikud_mode() == 'hide':
            text = without_nikud(text)
        self._text_updating = True
        self.editor.setPlainText(text)
        self._text_updating = False
        self.text_count.setText(self.t('text_count', count=len(text)))

    def _editor_changed(self):
        if self._text_updating:
            return
        record = self.current_record
        if not record:
            return
        visible = self.editor.toPlainText()
        record.edited_text = edit_hidden(record.edited_text, visible) if self.nikud_mode() == 'hide' else visible
        self.text_count.setText(self.t('text_count', count=len(visible)))
        self.update_actions()

    def update_actions(self, *unused):
        busy = self.worker is not None
        active = bool(self.current_record and self.current_record.image)
        text = bool(self.current_record and self.current_record.edited_text)
        idle = self.capture.state == 'idle' if hasattr(self, 'capture') else True
        for button in (self.open_button, self.capture_button, self.window_button, self.history_button, self.settings_button):
            button.setEnabled(not busy and idle)
        self.recognize_button.setEnabled(active and not busy and idle)
        for button in (self.copy_button, self.copy_text_button):
            button.setEnabled(text and not busy)
        for button in (self.export_button, self.export_text_button):
            button.setEnabled((text or active) and not busy)
        self.save_image_button.setEnabled(active and not busy)
        self.raw_button.setEnabled(bool(self.current_record and self.current_record.reading))
        self.previous_button.setEnabled(bool(self.document and self.page > 0 and not busy))
        self.next_button.setEnabled(bool(self.document and self.page < self.document.pages - 1 and not busy))
        for button in (self.zoom_out, self.zoom_in, self.fit_button):
            button.setEnabled(active)
        if active and not text:
            self.recognize_button.setObjectName('primary')
        else:
            self.recognize_button.setObjectName('')
        if text:
            self.copy_button.setObjectName('primary')
        else:
            self.copy_button.setObjectName('')
        for button in (self.recognize_button, self.copy_button):
            button.style().unpolish(button)
            button.style().polish(button)

    def capture_action(self):
        self.capture.arm()

    def capture_window_action(self):
        self.capture.capture_window()

    def receive_capture(self, image, rect):
        self.document = None
        self.page = 0
        self._add_record(image, self.t('selection'), timings={'capture_ms': round(self.capture.capture_ms, 1)})
        if self.settings.value('v04_after_capture', 'preview') == 'recognize':
            self.recognize()

    def _add_record(self, image, source, page=0, document=None, timings=None):
        if self.current_record and not self.settings.value('retain_image', True, type=bool):
            self.current_record.image = None
        record = CaptureRecord(image.copy(), source, page, document, timings=timings or {})
        self.records.append(record)
        self.current_index = len(self.records) - 1
        self.current_image = record.image
        self.image_panel.set_image(record.image)
        self.image_hint.setText(self.t('selection_hint'))
        self.document_name.setText(source)
        self._show_record_text()
        self._update_page()
        self.status.setText(self.t('ready'))
        self.update_actions()
        return record

    def open_dialog(self):
        if self.worker:
            return
        path, _ = QFileDialog.getOpenFileName(self, self.t('open'), '',
            'PDF / Images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)')
        if path:
            self.open_document(path)

    def open_document(self, path):
        if self.worker:
            return
        try:
            try:
                document = Document(path)
            except Exception as error:
                if getattr(error, 'err_code', None) != 4:
                    raise
                password, ok = QInputDialog.getText(self, self.t('password'), self.t('password'),
                                                     QLineEdit.EchoMode.Password)
                if not ok:
                    return
                document = Document(path, password)
            image = document.render(0, self.resolution())
            self.document, self.page = document, 0
            self._add_record(image, Path(path).name, 0, document)
        except Exception as error:
            self.show_error(str(error))

    def resolution(self):
        value = self.settings.value('v04_resolution', 'auto')
        return int(value) if value in ('300', '360', '450') else 360

    def navigate(self, delta):
        if not self.document or self.worker:
            return
        target = self.page + delta
        if not 0 <= target < self.document.pages:
            return
        try:
            image = self.document.render(target, self.resolution())
            self.page = target
            self._add_record(image, Path(self.document.path).name, target, self.document)
        except Exception as error:
            self.show_error(str(error))

    def _update_page(self):
        self.page_label.setText(self.t('page_number', page=self.page + 1, total=self.document.pages)
                                if self.document else '')

    def recognize(self):
        if self.worker or not self.current_record or self.current_record.image is None:
            return
        record = self.current_record
        selection = self.image_panel.normalized_selection()
        if record.document and record.document.is_pdf and not selection and ' · ' not in record.source:
            self.status.setText(self.t('select_block_first'))
            return
        if selection:
            x0, y0, x1, y1 = selection
            image = record.image
            bounds = (max(0, round(x0 * image.width)), max(0, round(y0 * image.height)),
                      min(image.width, round(x1 * image.width)), min(image.height, round(y1 * image.height)))
            if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                return
            record = self._add_record(image.crop(bounds), record.source + ' · ' + self.t('selection'),
                                      record.page, record.document)
        elif record.reading is not None:
            # A second OCR attempt is a new reading; the first raw result remains
            # available in its own history entry even if settings changed.
            record = self._add_record(record.image, record.source, record.page, record.document)
        options = Options(script=self.settings.value('v04_script', 'square'), layout='block',
                          dpi=self.resolution(), enhanced=False, deskew=False, typography='none',
                          languages=self.v04_languages(), profile=self.v04_profile(),
                          ignore_running_headers=False, ignore_pagination=False, pipeline='faithful')
        self._ocr_target = record
        self.worker = FaithfulWorker(record.image, options)
        self.worker.resultReady.connect(self._ocr_finished)
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(self._worker_closed)
        self.editor.setReadOnly(True)
        self.status.setText(self.t('reading'))
        self.update_actions()
        self.worker.start()

    def _ocr_finished(self, candidate, diagnostics):
        started = time.perf_counter()
        record = self._ocr_target
        if record is not None:
            record.reading = RawReading(candidate.text, candidate.model, candidate.confidence)
            edited = (without_nikud(candidate.text) if self.nikud_mode() == 'remove'
                      else candidate.text)
            # The raw engine text above stays untouched. The profile only shapes
            # the editable copy: torah applies conservative gershayim marks and
            # mixed RTL order repair, general repairs Latin/Hebrew order only
            # when a Latin model was enabled. No dictionary, no word replacement.
            if self.v04_profile() == 'torah':
                edited = repair_mixed_rtl(hebrew_typography(edited))
            elif set(self.v04_languages()) & {'eng', 'fra'}:
                edited = repair_mixed_rtl(edited)
            if self.join_lines_enabled():
                edited = clean_text(edited, join_lines=True)
            record.edited_text = edited
            record.timings.update(diagnostics)
            self._show_record_text()
            record.timings['display_ms'] = round((time.perf_counter() - started) * 1000, 1)
            if candidate.text.strip():
                # Duplicate suspicion never deletes: it explains the overlap
                # (shared leading words) and leaves keep/remove to the user.
                message = self.t('done')
                previous = self._previous_text(record)
                count = probable_overlap(previous, record.edited_text)[0] if previous else 0
                record.overlap_words = count
                if count:
                    message += f" · {self.t('duplicate')} ({count})"
                self.status.setText(message)
            else:
                record.overlap_words = 0
                self.status.setText(self.t('empty_ocr'))
            if self.settings.value('v04_diagnostics', False, type=bool):
                def display_ms(key):
                    return f'{record.timings.get(key, 0):.0f} ms'
                self.timing_label.setText(self.t('processing_times', capture=display_ms('capture_ms'),
                                   ocr=display_ms('ocr_ms'), display=display_ms('display_ms')) +
                                   (' · ' + self.t('cached') if diagnostics.get('cache_hit') else ''))
        self.update_actions()

    def _worker_closed(self):
        if self.worker:
            self.worker.deleteLater()
        self.worker = None
        self._ocr_target = None
        self.editor.setReadOnly(False)
        self.update_actions()

    def _previous_text(self, record):
        for item in reversed(self.records):
            if item is not record and item.edited_text.strip():
                return item.edited_text
        return ''

    def delete_record(self, index):
        if not 0 <= index < len(self.records):
            return
        del self.records[index]
        if not self.records:
            self.current_index = -1
            self.current_image = None
            self.document, self.page = None, 0
            self.image_panel.clear_image()
            self.document_name.setText('')
            self._update_page()
            self._show_record_text()
        else:
            self.show_record(min(index, len(self.records) - 1))
        self.update_actions()

    def copy_text(self):
        record = self.current_record
        if record and record.edited_text:
            QApplication.clipboard().setText(record.edited_text)
            self.status.setText(self.t('copied'))

    def show_export_menu(self):
        record = self.current_record
        if not record or (not record.edited_text and record.image is None):
            return
        menu = QMenu(self)
        if record.edited_text:
            menu.addAction('Word (.docx)', lambda: self.export_text('.docx'))
            menu.addAction(self.t('export_txt'), lambda: self.export_text('.txt'))
        if record.image is not None:
            menu.addAction(self.t('save_image'), self.save_image)
        menu.exec(self.sender().mapToGlobal(self.sender().rect().bottomLeft()))

    def export_text(self, extension='.docx'):
        record = self.current_record
        if not record or not record.edited_text:
            return
        filter_text = 'Word (*.docx)' if extension == '.docx' else 'Texte UTF-8 (*.txt)'
        path, _ = QFileDialog.getSaveFileName(self, self.t('export'), 'AlephOCR' + extension, filter_text)
        if not path:
            return
        if not Path(path).suffix:
            path += extension
        try:
            save_text(path, record.edited_text, self.settings.value('font', 'Arial'),
                      self.settings.value('font_size', 18, type=int))
            self.status.setText(self.t('text_saved'))
        except Exception as error:
            self.show_error(str(error))

    def save_image(self):
        self._save_image_for(self.current_record)

    def _save_image_for(self, record):
        if not record or record.image is None:
            self.show_error(self.t('no_history_image'))
            return
        path, selected = QFileDialog.getSaveFileName(self, self.t('save_image'), 'AlephOCR-capture.png',
                           'PNG (*.png);;JPEG (*.jpg);;TIFF (*.tiff);;WEBP (*.webp)')
        if not path:
            return
        suffix = { 'PNG': '.png', 'JPEG': '.jpg', 'TIFF': '.tiff', 'WEBP': '.webp' }
        extension = next((ext for name, ext in suffix.items() if selected.startswith(name)), '.png')
        if not Path(path).suffix:
            path += extension
        try:
            record.image.save(path)
            self.status.setText(self.t('image_saved'))
        except Exception as error:
            self.show_error(str(error))

    def view_raw(self):
        record = self.current_record
        if not record or not record.reading:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t('raw_view'))
        dialog.resize(720, 480)
        layout = QVBoxLayout(dialog)
        label = QLabel(self.t('raw_help'))
        label.setWordWrap(True)
        layout.addWidget(label)
        info = QLabel(f"{record.reading.model} · {record.reading.confidence:.0f}/100")
        info.setObjectName('muted')
        layout.addWidget(info)
        raw = QTextEdit(record.raw_text)
        raw.setReadOnly(True)
        raw.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout.addWidget(raw, 1)
        buttons = QHBoxLayout()
        restore = QPushButton(self.t('raw_restore'))
        def restore_text():
            if record.edited_text != record.raw_text and QMessageBox.question(
                dialog, self.t('raw_restore'), self.t('raw_restore_confirm')) != QMessageBox.StandardButton.Yes:
                return
            record.edited_text = record.raw_text
            self._show_record_text()
            dialog.accept()
        restore.clicked.connect(restore_text)
        buttons.addWidget(restore)
        close = QPushButton(self.t('close'))
        close.clicked.connect(dialog.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        dialog.exec()

    def show_history(self):
        if not self.records:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t('history'))
        dialog.resize(690, 450)
        layout = QVBoxLayout(dialog)
        hint = QLabel(self.t('history_help'))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        entries = QListWidget()
        layout.addWidget(entries, 1)

        def populate(select=None):
            entries.clear()
            for number, item in enumerate(self.records, 1):
                created = time.strftime('%H:%M:%S', time.localtime(item.created))
                text = item.edited_text.strip().splitlines()[0][:52] if item.edited_text.strip() else '—'
                marker = ' ⚠' if item.overlap_words else ''
                entries.addItem(f'{number}. {item.source} · {created} · {text}{marker}')
            entries.setCurrentRow(self.current_index if select is None else select)
        populate()

        def selected():
            index = entries.currentRow()
            return self.records[index] if 0 <= index < len(self.records) else None

        actions = QHBoxLayout()
        def action(key, callback):
            button = QPushButton(self.t(key))
            button.clicked.connect(callback)
            actions.addWidget(button)
            return button
        def reopen():
            index = entries.currentRow()
            if index >= 0:
                self.show_record(index)
                dialog.accept()
        def move(direction):
            index = entries.currentRow()
            target = index + direction
            if 0 <= index < len(self.records) and 0 <= target < len(self.records):
                self.records[index], self.records[target] = self.records[target], self.records[index]
                if self.current_index == index:
                    self.current_index = target
                elif self.current_index == target:
                    self.current_index = index
                populate(target)
        action('reopen', reopen)
        def remove():
            index = entries.currentRow()
            if index >= 0:
                self.delete_record(index)
                populate()
        action('delete', remove)
        action('copy_short', lambda: QApplication.clipboard().setText(selected().edited_text) if selected() else None)
        action('save_image', lambda: self._save_image_for(selected()))
        action('move_up', lambda: move(-1))
        action('move_down', lambda: move(1))
        action('copy_zones', lambda: QApplication.clipboard().setText('\n\n'.join(
               item.edited_text for item in self.records if item.edited_text)))
        layout.addLayout(actions)
        dialog.exec()

    def show_record(self, index):
        if not 0 <= index < len(self.records):
            return
        self.current_index = index
        record = self.records[index]
        self.document, self.page = record.document, record.page
        self.current_image = record.image
        if record.image:
            self.image_panel.set_image(record.image)
        else:
            self.image_panel.clear_image()
        self.document_name.setText(record.source)
        self._update_page()
        self._show_record_text()
        self.update_actions()

    def show_settings(self):
        from .settings import show_settings
        show_settings(self)

    def show_error(self, message):
        self.status.setText(f'{self.t("error")} · {message}')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.worker:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.worker:
            return
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_document(url.toLocalFile())
                break

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancel.set()
            event.ignore()
            return
        if self._hotkeys:
            QApplication.instance().removeNativeEventFilter(self._hotkeys)
            self._hotkeys.close()
            self._hotkeys = None
        if hasattr(self, 'capture') and self.capture.state != 'idle':
            self.capture.cleanup()
        event.accept()
