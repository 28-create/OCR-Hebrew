"""Experimental v0.3 interface, available only through --experimental.

Reuses QuickWindow capture/history and the existing document worker/PageView.
The legacy AlephWindow remains available for regression tests during migration.
"""
from pathlib import Path
import time
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QKeySequence, QShortcut, QFont
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QSpinBox, QFileDialog, QMessageBox, QInputDialog, QCheckBox)
from PIL import Image
from quick import QuickWindow, qimage_to_pil
from core import Document, Candidate, Options, parse_pages, save_text, clean_text, ASSETS
from widgets import PageView
from .i18n import tr


class MainWindow(QuickWindow):
    def __init__(self):
        self.document = None
        self.page = 0
        self.rotations = {}
        self.professional = False
        self.dirty = False
        self.errors = []
        self._buttons = []
        super().__init__()
        self.resize(1100, 740)
        self.setMinimumSize(720, 440)
        self.setAcceptDrops(True)
        self.openProfessional.connect(self.toggle_mode)
        self.apply_font()
        self.retranslate()
        self.apply_display(self.display.currentIndex())

    def t(self, key):
        return tr(key, self.language.currentData() or 'he')

    def action(self, key, callback, layout):
        button = QPushButton()
        button.clicked.connect(callback)
        self._buttons.append((button, key))
        layout.addWidget(button)
        return button

    def _build(self):
        super()._build()
        outer = self.centralWidget().layout()
        toolbar = QHBoxLayout()
        self.open_button = self.action('open', self.open_dialog, toolbar)
        self.window_button = self.action('window', self.capture.capture_window, toolbar)
        self.paste_button = self.action('paste', self.paste_image, toolbar)
        self.document_name = QLabel('—')
        self.document_name.setWordWrap(True)
        toolbar.addWidget(self.document_name, 1)
        outer.insertLayout(1, toolbar)
        self.history_label = QLabel()
        outer.itemAt(0).layout().insertWidget(3, self.history_label)
        old = self.image_panel
        self.image_panel = PageView()
        self.splitter.replaceWidget(0, self.image_panel)
        old.deleteLater()
        self.navigation = QWidget()
        nav = QHBoxLayout(self.navigation)
        self.previous = QPushButton('‹')
        self.previous.clicked.connect(lambda: self.navigate(-1))
        self.next = QPushButton('›')
        self.next.clicked.connect(lambda: self.navigate(1))
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.valueChanged.connect(self.go_to_page)
        for w in (self.previous, self.page_spin, self.next):
            nav.addWidget(w)
        self.scope = QComboBox()
        for key in ('all', 'current', 'custom'):
            self.scope.addItem('', key)
        nav.addWidget(self.scope)
        self.page_range = QLineEdit()
        self.page_range.setPlaceholderText('1-3, 5, 8-10')
        self.page_range.setEnabled(False)
        self.scope.currentIndexChanged.connect(lambda: self.page_range.setEnabled(self.scope.currentData() == 'custom'))
        nav.addWidget(self.page_range)
        self.read_button = self.action('read', self.read_document, nav)
        self.cancel_button = self.action('cancel', self.cancel_work, nav)
        outer.insertWidget(2, self.navigation)
        self.advanced = QWidget()
        advanced = QVBoxLayout(self.advanced)
        settings = QHBoxLayout()
        self.layout_mode = QComboBox()
        for key in ('auto', 'block', 'line', 'columns'):
            self.layout_mode.addItem('', key)
        settings.addWidget(self.layout_mode)
        self.resolution = QComboBox()
        for dpi in (300, 360, 450):
            self.resolution.addItem(f'{dpi} dpi', dpi)
        self.resolution.setCurrentIndex(1)
        settings.addWidget(self.resolution)
        self.action('rotate', self.rotate, settings)
        self.action('fit', self.image_panel.fit_page, settings)
        zoom_out, zoom_in = QPushButton('−'), QPushButton('+')
        zoom_out.clicked.connect(lambda: self.image_panel.zoom(1/1.2))
        zoom_in.clicked.connect(lambda: self.image_panel.zoom(1.2))
        settings.addWidget(zoom_out)
        settings.addWidget(zoom_in)
        self.action('clear', self.image_panel.clear_selection, settings)
        advanced.addLayout(settings)
        variants = QHBoxLayout()
        self.variants_label = QLabel()
        variants.addWidget(self.variants_label)
        self.variants = QComboBox()
        self.variants.currentIndexChanged.connect(self.select_variant)
        variants.addWidget(self.variants, 1)
        self.blocks_label = QLabel()
        variants.addWidget(self.blocks_label)
        self.blocks = QComboBox()
        self.blocks.currentIndexChanged.connect(self.show_block)
        variants.addWidget(self.blocks, 1)
        advanced.addLayout(variants)
        exports = QHBoxLayout()
        self.action('join', self.join_lines, exports)
        self.action('native', self.extract_native, exports)
        self.action('export', lambda: self.export_text(False), exports)
        self.action('export_all', lambda: self.export_text(True), exports)
        advanced.addLayout(exports)
        outer.insertWidget(outer.count() - 2, self.advanced)
        self.advanced.hide()
        for sequence, action in [('Ctrl+O', self.open_dialog), ('Ctrl+Shift+V', self.paste_image), ('Ctrl+Return', self.read_document)]:
            QShortcut(QKeySequence(sequence), self).activated.connect(action)

    def make_options(self):
        return Options(pipeline='experimental', script=self.script.currentData(), layout=self.layout_mode.currentData(),
            dpi=self.resolution.currentData(), languages=tuple(self.settings.value('ocr_languages', ['heb', 'heb_rashi'])),
            profile=self.profile.currentData(), enhanced=self.settings.value('enhanced', True, type=bool),
            deskew=self.settings.value('deskew', True, type=bool),
            ignore_running_headers=self.settings.value('ignore_headers', True, type=bool),
            ignore_pagination=self.settings.value('ignore_pages', True, type=bool),
            include_repeated=self.settings.value('include_repeated', False, type=bool))

    def toggle_mode(self):
        self.professional = not self.professional
        self.advanced.setVisible(self.professional)
        self.apply_display(self.display.currentIndex())
        self.retranslate()

    def apply_display(self, index):
        super().apply_display(index)
        self.pro_button.show()
        if self.professional:
            for widget in (self.profile, self.script, self.nikud, self.confidence):
                widget.show()

    def open_dialog(self):
        if self.worker:
            return
        path, _ = QFileDialog.getOpenFileName(self, self.t('open'), '', 'PDF / Images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)')
        if path:
            self.open_document(path)

    def open_demo(self):
        self.open_document(str(ASSETS / 'demo.png'))

    def open_document(self, path):
        if self.worker:
            return
        try:
            try:
                document = Document(path)
            except Exception as error:
                if getattr(error, 'err_code', None) != 4:
                    raise
                password, accepted = QInputDialog.getText(self, self.t('password'), self.t('password'), QLineEdit.EchoMode.Password)
                if not accepted:
                    return
                document = Document(path, password)
            image = document.render(0, self.make_options().dpi)
            self.document, self.page, self.rotations = document, 0, {}
            self.current_image, self.current_rect = image, QRect()
            self.active_history = -1
            self.scope.setCurrentIndex(0)
            self.page_range.clear()
            self.page_spin.blockSignals(True)
            self.page_spin.setRange(1, document.pages)
            self.page_spin.setValue(1)
            self.page_spin.blockSignals(False)
            self.document_name.setText(Path(path).name)
            self.show_capture_image(image)
            if not document.is_pdf and document.pages == 1:
                self.pending_mode = 'replace'
                self.start_ocr(image, QRect())
        except Exception as error:
            self.show_error(str(error))

    def navigate(self, delta):
        self.page_spin.setValue(self.page_spin.value() + delta)

    def go_to_page(self, number):
        if not self.document or self.worker:
            return
        try:
            image = self.document.render(number - 1, self.make_options().dpi, rotation=self.rotations.get(number - 1, 0))
            self.page = number - 1
            self.current_image = image
            self.show_capture_image(image)
        except Exception as error:
            self.show_error(str(error))

    def selected_pages(self):
        if self.scope.currentData() == 'current':
            return [self.page]
        return parse_pages(self.page_range.text() if self.scope.currentData() == 'custom' else '', self.document.pages)

    def read_document(self):
        if self.worker:
            return
        if not self.document:
            if self.current_image:
                self.redo_capture()
            return
        try:
            from app import OcrWorker
            pages = self.selected_pages()
            options = self.make_options()
            from ocr.engine import models
            models(options)
            self.last_options = options
            self.errors = []
            # A drawn selection is an explicit current-page action.
            box = self.image_panel.normalized_selection()
            if box:
                pages = [self.page]
            self.worker = OcrWorker(self.document, pages, options, box, dict(self.rotations))
            self.worker.resultReady.connect(self.receive_document_result)
            self.worker.failed.connect(self.errors.append)
            self.worker.finished.connect(self.worker_finished)
            self.progress.show()
            self.status.setText(self.t('reading'))
            self.page_spin.setEnabled(False)
            self.worker.start()
        except Exception as error:
            self.show_error(str(error))

    def receive_document_result(self, result):
        self.current_image = result.image
        self.current_rect = QRect()
        self.page = result.page
        self.pending_mode, self.base_text = 'replace', ''
        self.user_edited_draft = False
        self.active_history = -1
        self.show_capture_image(result.image)
        self.show_final(result.candidates)
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(result.page + 1)
        self.page_spin.blockSignals(False)

    def receive_capture(self, image, rect):
        self.document = None
        self.page = 0
        self.document_name.setText(self.t('area'))
        super().receive_capture(image, rect)

    def paste_image(self):
        if self.worker:
            return
        from PySide6.QtWidgets import QApplication
        image = QApplication.clipboard().image()
        if image.isNull():
            self.show_error(self.t('no_image'))
            return
        self.pending_mode = 'replace'
        self.receive_capture(qimage_to_pil(image), QRect())

    def start_ocr(self, image, rect):
        super().start_ocr(image, rect)
        self.status.setText(self.t('reading'))

    def show_draft(self, candidate):
        super().show_draft(candidate)
        self.status.setText(self.t('reading'))
        self.confidence.setText(self.t('raw'))

    def show_final(self, candidates):
        super().show_final(candidates)
        if self.active_history >= 0:
            item = self.items[self.active_history]
            item.source = Path(self.document.path).name if self.document else self.t('area')
            item.page, item.document = self.page, self.document
            self.history.setItemText(self.active_history + 1, f'{item.source} — {item.page + 1} · {time.strftime("%H:%M:%S", time.localtime(item.created))}')
        self.dirty = True
        self.populate_variants()
        self.status.setText(self.t('done'))
        self.confidence.setText(f'OCR {candidates[0].confidence:.0f}/100')
        self.history_label.setText(f'{self.t("history")} ({len(self.items)}) ▾')
        if self.duplicate_chars:
            self.duplicate.setText(self.t('duplicate'))

    def populate_variants(self):
        self.variants.blockSignals(True)
        self.variants.clear()
        for i, candidate in enumerate(self.candidates):
            self.variants.addItem(f'{self.t("improved" if i == 0 and len(self.candidates) > 1 else "raw")} · {candidate.confidence:.0f}/100')
        if 0 <= self.active_history < len(self.items):
            self.variants.setCurrentIndex(self.items[self.active_history].selected)
        self.variants.blockSignals(False)
        self.populate_blocks()

    def select_variant(self, index):
        if not 0 <= index < len(self.candidates):
            return
        self.save_history_text()
        self.current_candidate = self.candidates[index]
        item = self.items[self.active_history] if self.active_history >= 0 else None
        if item:
            item.selected = index
        self.internal_text = item.corrections.get(index, self.current_candidate.text) if item else self.current_candidate.text
        self.apply_nikud()
        self.populate_blocks()

    def populate_blocks(self):
        self.blocks.blockSignals(True)
        self.blocks.clear()
        if self.current_candidate:
            for block in self.current_candidate.blocks:
                self.blocks.addItem(f'{block.order + 1} · {block.kind} · {block.model} · {block.score:.0f} · {block.box}')
        self.blocks.blockSignals(False)

    def show_block(self, index):
        if self.current_candidate and self.current_image and 0 <= index < len(self.current_candidate.blocks):
            x0, y0, x1, y1 = self.current_candidate.blocks[index].box
            w, h = self.current_image.size
            self.image_panel.set_highlight((x0/w, y0/h, (x1-x0)/w, (y1-y0)/h))

    def restore_history(self, index):
        super().restore_history(index)
        if 0 <= self.active_history < len(self.items):
            item = self.items[self.active_history]
            self.document, self.page = item.document, item.page
            self.document_name.setText(item.source)
            self.profile.setCurrentIndex(max(0, self.profile.findData(item.profile)))
            if item.options:
                self.script.setCurrentIndex(max(0, self.script.findData(item.options.script)))
                self.layout_mode.setCurrentIndex(max(0, self.layout_mode.findData(item.options.layout)))
                self.resolution.setCurrentIndex(max(0, self.resolution.findData(item.options.dpi)))
            self.page_spin.blockSignals(True)
            self.page_spin.setRange(1, self.document.pages if self.document else 1)
            self.page_spin.setValue(self.page + 1)
            self.page_spin.blockSignals(False)
            self.populate_variants()
            self.variants.blockSignals(True)
            self.variants.setCurrentIndex(item.selected)
            self.variants.blockSignals(False)

    def rotate(self):
        if self.worker or self.current_image is None:
            return
        if self.document:
            self.rotations[self.page] = (self.rotations.get(self.page, 0) + 90) % 360
            self.go_to_page(self.page + 1)
        else:
            self.current_image = self.current_image.rotate(-90, expand=True, fillcolor='white')
            self.show_capture_image(self.current_image)

    def cancel_work(self):
        if self.worker:
            self.worker.cancel.set()

    def worker_finished(self):
        super().worker_finished()
        self.page_spin.setEnabled(True)
        if self.errors:
            self.show_error('\n'.join(self.errors))
            self.errors = []

    def show_settings(self):
        from .legacy_settings import show_settings
        show_settings(self)

    def apply_font(self):
        family = self.settings.value('font', 'Arial')
        size = self.settings.value('font_size', 18, type=int)
        self.editor.setFont(QFont(family, size))
        self.editor.setStyleSheet(f'font-family: "{family.replace(chr(34), "")}"; font-size: {size}pt;')

    def join_lines(self):
        self.internal_text = clean_text(self.internal_text, join_lines=True)
        self.apply_nikud()
        self.save_history_text()

    def extract_native(self):
        if self.worker or not self.document or not self.document.is_pdf:
            return
        try:
            text = self.document.extract(self.page)
        except Exception as error:
            self.show_error(str(error))
            return
        if not text:
            self.show_error(self.t('no_text'))
            return
        self.pending_mode, self.base_text, self.user_edited_draft = 'replace', '', False
        self.show_final([Candidate(text, -1, [], self.t('native'), len(text.split()))])

    def export_text(self, all_results=False):
        text = '\n\n'.join(f'[{item.source} — {item.page+1}]\n{self.visible_text(item.text)}' for item in self.items) if all_results else self.editor.toPlainText()
        path, selected = QFileDialog.getSaveFileName(self, self.t('export'), 'AlephOCR.docx', 'Word (*.docx);;Text (*.txt)')
        if not path:
            return
        extension = '.docx' if 'docx' in selected else '.txt'
        if not Path(path).suffix:
            path += extension
            if Path(path).exists():
                self.show_error(path + ' — ' + self.t('save'))
                return
        try:
            save_text(path, text, self.settings.value('font', 'Arial'), self.settings.value('font_size', 18, type=int))
        except Exception as error:
            self.show_error(str(error))

    def copy_all(self):
        super().copy_all()
        self.status.setText(self.t('copied'))

    def show_error(self, message):
        self.status.setText(f'{self.t("error")} · {message}')
        self.show()

    def retranslate(self):
        if not hasattr(self, 'advanced'):
            return
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.language.currentData() == 'he' else Qt.LayoutDirection.LeftToRight)
        self.editor.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        for button, key in self._buttons:
            button.setText(self.t(key))
        for button, key in [(self.capture_button, 'area'), (self.add_button, 'add'), (self.redo_button, 'redo'),
                            (self.copy_button, 'copy'), (self.remove_duplicate, 'delete'), (self.keep_duplicate, 'keep')]:
            button.setText(self.t(key))
        self.pro_button.setText(self.t('quick' if self.professional else 'pro'))
        self.history_label.setText(f'{self.t("history")} ({len(self.items)}) ▾')
        self.history.setItemText(0, self.t('history'))
        self.variants_label.setText(self.t('variants'))
        self.blocks_label.setText(self.t('blocks'))
        self.gear.setToolTip(self.t('settings'))
        self.pin.setToolTip(self.t('pin'))
        self.editor.setPlaceholderText(self.t('editor'))
        for combo, keys in [(self.display, ('compact', 'mini', 'full')), (self.profile, ('torah', 'general')),
                            (self.nikud, ('nikud_keep', 'nikud_hide', 'nikud_remove')), (self.scope, ('all', 'current', 'custom')),
                            (self.layout_mode, ('layout', 'block', 'line', 'columns'))]:
            for i, key in enumerate(keys):
                combo.setItemText(i, self.t(key))
        self.script.setItemText(0, self.t('auto'))
        self.status.setText(self.t('ready') + ' · ' + self.t('privacy'))
        self.populate_variants()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.worker:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not self.worker:
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self.open_document(url.toLocalFile())
                    break

    def closeEvent(self, event):
        if not self.worker and self.dirty and self.internal_text:
            dialog = QMessageBox(self)
            dialog.setWindowTitle(self.t('close_title'))
            dialog.setText(self.t('close_body'))
            yes = dialog.addButton(self.t('yes'), QMessageBox.ButtonRole.YesRole)
            no = dialog.addButton(self.t('no'), QMessageBox.ButtonRole.NoRole)
            dialog.setDefaultButton(no)
            dialog.exec()
            if dialog.clickedButton() is not yes:
                event.ignore()
                return
        super().closeEvent(event)
