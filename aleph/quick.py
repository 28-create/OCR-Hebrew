"""Fast, screen-first OCR workflow for Aleph OCR."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
import sys
import threading
import time

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QObject, QRect, QRectF, QPoint, Signal, QThread, QTimer, QAbstractNativeEventFilter, QSettings
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QTextCursor, QTextBlockFormat, QKeySequence, QShortcut, QGuiApplication, QCursor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton, QTextEdit, QVBoxLayout,
    QHBoxLayout, QSplitter, QComboBox, QProgressBar, QMessageBox, QDialog, QCheckBox, QDialogButtonBox,
    QFormLayout, QKeySequenceEdit, QGroupBox)

from core import Options, Candidate, recognize, probable_overlap, without_nikud
from widgets import app_icon, pil_pixmap
from version import VERSION


class FitImageLabel(QWidget):
    def __init__(self):
        super().__init__()
        self.pixmap = None
        self.highlight = None
        self.setMinimumWidth(220)

    def set_image(self, image):
        self.pixmap = pil_pixmap(image)
        self.highlight = None
        self.update()

    def set_highlight(self, box):
        self.highlight = box
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#e4eae3'))
        if self.pixmap is None or self.pixmap.isNull():
            painter.setPen(QColor('#60766c'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Ctrl+Shift+O\n\nבחרו אזור על המסך')
            return
        scaled = self.pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        target = QRect((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled.width(), scaled.height())
        painter.drawPixmap(target, scaled)
        if self.highlight:
            x, y, w, h = self.highlight
            box = QRectF(target.x() + x * target.width(), target.y() + y * target.height(), w * target.width(), h * target.height())
            painter.setPen(QPen(QColor('#cc8f35'), 2))
            painter.setBrush(QColor(255, 191, 72, 65))
            painter.drawRoundedRect(box, 3, 3)


def qimage_to_pil(image):
    image = image.convertToFormat(image.Format.Format_RGBA8888)
    array = np.frombuffer(image.bits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine())
    return Image.fromarray(array[:, :image.width() * 4].reshape(image.height(), image.width(), 4).copy(), 'RGBA').convert('RGB')


class CaptureOverlay(QWidget):
    selected = Signal(object, object)
    cancelled = Signal()

    def __init__(self, screen, screenshot):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.screen, self.screenshot = screen, screenshot
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.origin = None
        self.selection = QRect()
        self.hint = 'גרור מסגרת סביב הטקסט · Esc'

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.screenshot)
        painter.fillRect(self.rect(), QColor(8, 25, 21, 105))
        if not self.selection.isNull():
            ratio = self.screenshot.devicePixelRatio()
            source = QRect(round(self.selection.x() * ratio), round(self.selection.y() * ratio),
                           round(self.selection.width() * ratio), round(self.selection.height() * ratio))
            painter.drawPixmap(QRectF(self.selection), self.screenshot, QRectF(source))
            painter.setPen(QPen(QColor('#d6b875'), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.selection)
        painter.setPen(Qt.GlobalColor.white)
        painter.setFont(QFont('Segoe UI', 12, QFont.Weight.DemiBold))
        painter.drawText(24, 34, self.hint)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.selection = QRect(self.origin, self.origin)
            self.update()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.selection = QRect(self.origin, event.position().toPoint()).normalized().intersected(self.rect())
            self.update()

    def mouseReleaseEvent(self, event):
        if self.origin is not None:
            self.origin = None
            if self.selection.width() >= 12 and self.selection.height() >= 12:
                ratio = self.screenshot.devicePixelRatio()
                source = QRect(round(self.selection.x() * ratio), round(self.selection.y() * ratio),
                               round(self.selection.width() * ratio), round(self.selection.height() * ratio))
                captured = self.screenshot.toImage().copy(source)
                captured.setDevicePixelRatio(1)
                global_rect = self.selection.translated(self.screen.geometry().topLeft())
                self.selected.emit(qimage_to_pil(captured), global_rect)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()


class CaptureController(QObject):
    captured = Signal(object, object)
    cancelled = Signal()

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.overlays = []

    def capture_area(self):
        self.owner.hide()
        QTimer.singleShot(160, self._show_overlays)

    def _show_overlays(self):
        self.overlays = []
        for screen in QApplication.screens():
            screenshot = screen.grabWindow(0)
            overlay = CaptureOverlay(screen, screenshot)
            if hasattr(self.owner, 't'):
                overlay.hint = self.owner.t('capture_hint')
            overlay.selected.connect(self._selected)
            overlay.cancelled.connect(self._cancel)
            self.overlays.append(overlay)
        for overlay in self.overlays:
            overlay.show()
        if self.overlays:
            self.overlays[0].activateWindow()

    def capture_window(self):
        if self.owner.worker:
            return
        self.owner.hide()
        QTimer.singleShot(180, self._foreground_window)

    def _foreground_window(self):
        hwnd = 0
        if sys.platform == 'win32':
            function = ctypes.windll.user32.GetForegroundWindow
            function.restype = wintypes.HWND
            hwnd = function()
        self._grab_window(hwnd)

    def _grab_window(self, hwnd):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        pixmap = screen.grabWindow(hwnd)
        if pixmap.isNull():
            self.owner.show()
            self.owner.show_error('לא ניתן לצלם חלון זה. נסו לכידת אזור.')
            return
        rect = QRect(QCursor.pos(), pixmap.deviceIndependentSize().toSize())
        self.captured.emit(qimage_to_pil(pixmap.toImage()), rect)

    def _selected(self, image, rect):
        self._close_overlays()
        self.captured.emit(image, rect)

    def _cancel(self):
        self._close_overlays()
        self.owner.show()
        self.cancelled.emit()

    def _close_overlays(self):
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.overlays = []


class GlobalHotkeys(QAbstractNativeEventFilter):
    WM_HOTKEY = 0x0312
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 1, 2, 4, 0x4000

    def __init__(self, callbacks, sequences=None):
        super().__init__()
        self.callbacks = callbacks
        self.registered = []
        self.sequences = sequences or {0xA101: 'Ctrl+Shift+O', 0xA102: 'Ctrl+Shift+W', 0xA103: 'Ctrl+Shift+A', 0xA104: 'Ctrl+Shift+R'}
        if sys.platform == 'win32' and QGuiApplication.platformName() != 'offscreen':
            for hotkey_id, sequence in self.sequences.items():
                combo = QKeySequence(sequence)[0]
                modifiers = self.MOD_NOREPEAT
                qt_modifiers = combo.keyboardModifiers()
                if qt_modifiers & Qt.KeyboardModifier.ControlModifier:
                    modifiers |= self.MOD_CONTROL
                if qt_modifiers & Qt.KeyboardModifier.ShiftModifier:
                    modifiers |= self.MOD_SHIFT
                if qt_modifiers & Qt.KeyboardModifier.AltModifier:
                    modifiers |= self.MOD_ALT
                key = combo.key().value
                if ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers, key):
                    self.registered.append(hotkey_id)

    def nativeEventFilter(self, event_type, message):
        if sys.platform == 'win32' and event_type in (b'windows_generic_MSG', b'windows_dispatcher_MSG'):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == self.WM_HOTKEY and msg.wParam in self.callbacks:
                self.callbacks[msg.wParam]()
                return True, 0
        return False, 0

    def close(self):
        if sys.platform == 'win32' and self.registered:
            for hotkey_id in self.registered:
                ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
        self.registered = []


class QuickWorker(QThread):
    draft = Signal(object)
    final = Signal(object)
    failed = Signal(str)

    def __init__(self, image, options):
        super().__init__()
        self.image, self.options = image.copy(), options
        self.cancel = threading.Event()

    def run(self):
        try:
            candidates = recognize(self.image, self.options, self.cancel, draft_callback=self.draft.emit)
            self.final.emit(candidates)
        except Exception as error:
            if not self.cancel.is_set():
                self.failed.emit(str(error))


@dataclass
class CaptureItem:
    image: Image.Image | None
    text: str
    rect: QRect
    confidence: float
    profile: str
    source: str = 'Capture'
    page: int = 0
    created: float = field(default_factory=time.time)
    options: Options | None = None
    candidates: list[Candidate] = field(default_factory=list)
    document: object = None
    corrections: dict[int, str] = field(default_factory=dict)
    selected: int = 0


class QuickWindow(QMainWindow):
    openProfessional = Signal()

    PROFILE_IDS = ['torah', 'general']

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'Aleph OCR {VERSION} — OCR עברית')
        self.setWindowIcon(app_icon())
        self.resize(940, 520)
        self.setMinimumSize(660, 360)
        self.settings = QSettings('AlephOCR', 'Quick')
        self.worker = None
        self.items = []
        self.current_image = None
        self.current_rect = QRect()
        self.pending_mode = 'replace'
        self.duplicate_chars = 0
        self.internal_text = ''
        self.base_text = ''
        self.current_candidate = None
        self.issue_index = -1
        self.active_history = -1
        self.candidates = []
        self.user_edited_draft = False
        self.last_options = None
        self.duplicate_start = 0
        self.capture = CaptureController(self)
        self.capture.captured.connect(self.receive_capture)
        self._build()
        self._restore()
        self.install_hotkeys()
        self.status.setText('מוכן · Ctrl+Shift+O ללכידת אזור · עיבוד מקומי בלבד')

    def _build(self):
        root = QWidget()
        root.setObjectName('quickRoot')
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 12, 16, 13)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setFixedSize(46, 46)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(app_icon().pixmap(44, 44))
        top.addWidget(logo)
        title = QLabel('Aleph OCR  ·  OCR עברית')
        title.setObjectName('quickTitle')
        top.addWidget(title)
        top.addStretch()
        self.history = QComboBox()
        self.history.setToolTip('היסטוריה זמנית')
        self.history.setMinimumWidth(100)
        self.history.addItem('◷  היסטוריה')
        self.history.currentIndexChanged.connect(self.restore_history)
        top.addWidget(self.history)
        self.pin = QPushButton('📌')
        self.pin.setCheckable(True)
        self.pin.setToolTip('תמיד מעל החלונות')
        self.pin.toggled.connect(self.toggle_pin)
        top.addWidget(self.pin)
        self.display = QComboBox()
        self.display.addItems(['קומפקטי', 'מיני', 'מלא'])
        self.display.currentIndexChanged.connect(self.apply_display)
        top.addWidget(self.display)
        self.language = QComboBox()
        self.language.addItem('עברית', 'he')
        self.language.addItem('Français', 'fr')
        self.language.addItem('English', 'en')
        self.language.currentIndexChanged.connect(self.retranslate)
        top.addWidget(self.language)
        self.gear = QPushButton('⚙')
        self.gear.setToolTip('הגדרות')
        self.gear.clicked.connect(self.show_settings)
        top.addWidget(self.gear)
        outer.addLayout(top)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.image_panel = FitImageLabel()
        self.image_panel.setObjectName('quickImage')
        self.editor = QTextEdit()
        self.editor.setObjectName('quickEditor')
        self.editor.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.editor.setPlaceholderText('הטקסט יופיע כאן ויהיה ניתן לעריכה')
        self.editor.textChanged.connect(self.edited)
        self.editor.cursorPositionChanged.connect(self.highlight_source_word)
        self.splitter.addWidget(self.image_panel)
        self.splitter.addWidget(self.editor)
        self.splitter.setSizes([390, 520])
        outer.addWidget(self.splitter, 1)

        controls = QHBoxLayout()
        self.profile = QComboBox()
        for name, value in [('ספר תורני', 'torah'), ('כללי', 'general')]:
            self.profile.addItem(name, value)
        controls.addWidget(self.profile)
        self.script = QComboBox()
        self.script.addItem('עברית + רש״י', 'auto')
        self.script.addItem('עברית', 'square')
        self.script.addItem('רש״י', 'rashi')
        controls.addWidget(self.script)
        self.nikud = QComboBox()
        self.nikud.addItem('ניקוד: הצג', 'keep')
        self.nikud.addItem('ניקוד: הסתר', 'hide')
        self.nikud.addItem('ניקוד: הסר', 'remove')
        self.nikud.currentIndexChanged.connect(self.apply_nikud)
        controls.addWidget(self.nikud)
        self.confidence = QLabel('—')
        self.confidence.setObjectName('quickMeta')
        controls.addWidget(self.confidence)
        controls.addStretch()
        outer.addLayout(controls)

        self.duplicate = QLabel('')
        self.duplicate.setObjectName('duplicateWarning')
        self.duplicate.hide()
        outer.addWidget(self.duplicate)
        actions = QHBoxLayout()
        self.capture_button = QPushButton('לכידת אזור')
        self.capture_button.setObjectName('primary')
        self.capture_button.clicked.connect(self.new_capture)
        actions.addWidget(self.capture_button)
        self.add_button = QPushButton('+ הוסף')
        self.add_button.clicked.connect(self.add_capture)
        actions.addWidget(self.add_button)
        self.redo_button = QPushButton('בצע שוב')
        self.redo_button.clicked.connect(self.redo_capture)
        actions.addWidget(self.redo_button)
        self.remove_duplicate = QPushButton('מחק כפילות')
        self.remove_duplicate.clicked.connect(self.delete_duplicate)
        self.remove_duplicate.hide()
        actions.addWidget(self.remove_duplicate)
        self.keep_duplicate = QPushButton('Conserver / שמור')
        self.keep_duplicate.clicked.connect(self.dismiss_duplicate)
        self.keep_duplicate.hide()
        actions.addWidget(self.keep_duplicate)
        actions.addStretch()
        self.pro_button = QPushButton('פתח מצב מקצועי')
        self.pro_button.clicked.connect(self.openProfessional)
        actions.addWidget(self.pro_button)
        self.copy_button = QPushButton('העתק הכול')
        self.copy_button.setObjectName('primary')
        self.copy_button.clicked.connect(self.copy_all)
        actions.addWidget(self.copy_button)
        outer.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.status = QLabel()
        self.status.setObjectName('quickMeta')
        outer.addWidget(self.status)
        QShortcut(QKeySequence('Ctrl+Shift+O'), self).activated.connect(self.new_capture)
        QShortcut(QKeySequence('Ctrl+Shift+A'), self).activated.connect(self.add_capture)
        QShortcut(QKeySequence('Ctrl+Shift+R'), self).activated.connect(self.redo_capture)
        QShortcut(QKeySequence('F4'), self).activated.connect(self.next_issue)

    def _restore(self):
        self.pin.setChecked(self.settings.value('always_on_top', False, type=bool))
        self.display.setCurrentIndex(self.settings.value('display', 0, type=int))
        language = self.settings.value('language', 'he')
        self.language.setCurrentIndex(max(0, self.language.findData(language)))
        self.profile.setCurrentIndex(max(0, self.profile.findData(self.settings.value('profile', 'torah'))))

    def hotkey_specs(self):
        return {
            0xA101: self.settings.value('shortcut_area', 'Ctrl+Shift+O'),
            0xA102: self.settings.value('shortcut_window', 'Ctrl+Shift+W'),
            0xA103: self.settings.value('shortcut_add', 'Ctrl+Shift+A'),
            0xA104: self.settings.value('shortcut_redo', 'Ctrl+Shift+R'),
        }

    def install_hotkeys(self):
        if hasattr(self, 'hotkeys'):
            QApplication.instance().removeNativeEventFilter(self.hotkeys)
            self.hotkeys.close()
        self.hotkeys = GlobalHotkeys({0xA101: self.new_capture, 0xA102: self.capture.capture_window,
                                      0xA103: self.add_capture, 0xA104: self.redo_capture}, self.hotkey_specs())
        QApplication.instance().installNativeEventFilter(self.hotkeys)

    def show_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('הגדרות · Aleph OCR')
        dialog.resize(520, 560)
        layout = QVBoxLayout(dialog)
        privacy = QLabel('🔒 עיבוד מקומי — שום תמונה ושום טקסט אינם נשלחים לאינטרנט.')
        privacy.setWordWrap(True)
        privacy.setObjectName('privacyBadge')
        layout.addWidget(privacy)
        options_group = QGroupBox('התנהגות מצב מהיר')
        options = QFormLayout(options_group)
        auto_copy = QCheckBox('העתק אוטומטית לאחר OCR')
        auto_copy.setChecked(self.settings.value('auto_copy', False, type=bool))
        close_copy = QCheckBox('סגור את החלון לאחר העתק הכול')
        close_copy.setChecked(self.settings.value('close_after_copy', False, type=bool))
        show_image = QCheckBox('הצג את התמונה כברירת מחדל')
        show_image.setChecked(self.settings.value('show_image', True, type=bool))
        keep_history = QCheckBox('שמור היסטוריה זמנית במשך ההפעלה')
        keep_history.setChecked(self.settings.value('session_history', True, type=bool))
        for widget in [auto_copy, close_copy, show_image, keep_history]:
            options.addRow(widget)
        layout.addWidget(options_group)
        languages_group = QGroupBox('OCR · עברית / Français / English')
        languages_form = QVBoxLayout(languages_group)
        enabled_languages = self.settings.value('ocr_languages', ['heb', 'heb_rashi'])
        languages = {}
        for code, title in [('heb', 'עברית'), ('heb_rashi', 'רש״י'), ('fra', 'Français'), ('eng', 'English')]:
            checkbox = QCheckBox(title)
            checkbox.setChecked(code in enabled_languages)
            languages[code] = checkbox
            languages_form.addWidget(checkbox)
        layout.addWidget(languages_group)
        shortcut_group = QGroupBox('קיצורי דרך כלליים')
        form = QFormLayout(shortcut_group)
        editors = {}
        for key, title, default in [('shortcut_area', 'לכידת אזור', 'Ctrl+Shift+O'), ('shortcut_window', 'לכידת חלון', 'Ctrl+Shift+W'),
                                    ('shortcut_add', 'הוסף לכידה', 'Ctrl+Shift+A'), ('shortcut_redo', 'בצע שוב', 'Ctrl+Shift+R')]:
            editor = QKeySequenceEdit(QKeySequence(self.settings.value(key, default)))
            editor.setMaximumSequenceLength(1)
            editors[key] = editor
            form.addRow(title, editor)
        layout.addWidget(shortcut_group)
        note = QLabel('השינויים בקיצורי הדרך נכנסים לתוקף מיד. אם קיצור תפוס בידי תוכנה אחרת, השתמשו בקיצור אחר.')
        note.setWordWrap(True)
        note.setObjectName('quickMeta')
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_languages = [code for code, checkbox in languages.items() if checkbox.isChecked()]
            if not selected_languages:
                self.show_error('OCR: select at least one language / choisissez une langue / בחרו שפה')
                return
            self.settings.setValue('ocr_languages', selected_languages)
            self.settings.setValue('auto_copy', auto_copy.isChecked())
            self.settings.setValue('close_after_copy', close_copy.isChecked())
            self.settings.setValue('show_image', show_image.isChecked())
            self.settings.setValue('session_history', keep_history.isChecked())
            for key, editor in editors.items():
                sequence = editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                if sequence:
                    self.settings.setValue(key, sequence)
            self.install_hotkeys()
            self.image_panel.setVisible(show_image.isChecked() and self.display.currentIndex() != 1)

    def new_capture(self):
        if self.worker:
            return
        self.pending_mode = 'replace'
        self.capture.capture_area()

    def add_capture(self):
        if self.worker:
            return
        self.pending_mode = 'append'
        self.capture.capture_area()

    def redo_capture(self):
        if self.worker or self.current_image is None:
            self.new_capture()
            return
        self.pending_mode = 'replace'
        self.start_ocr(self.current_image, self.current_rect)

    def receive_capture(self, image, rect):
        self.current_image, self.current_rect = image, rect
        self.show_capture_image(image)
        self.position_near(rect)
        self.show()
        self.start_ocr(image, rect)

    def start_ocr(self, image, rect):
        if self.worker:
            return
        self.current_image, self.current_rect = image, rect
        self.active_history = -1
        self.user_edited_draft = False
        self.base_text = self.internal_text if self.pending_mode == 'append' else ''
        options = self.make_options()
        self.last_options = options
        self.progress.show()
        self.status.setText('מזהה טקסט מקומי…')
        self.capture_button.setEnabled(False)
        self.worker = QuickWorker(image, options)
        self.worker.draft.connect(self.show_draft)
        self.worker.final.connect(self.show_final)
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def make_options(self):
        return Options(script=self.script.currentData(), layout='auto', dpi=360, enhanced=True,
                          deskew=True, languages=tuple(self.settings.value('ocr_languages', ['heb', 'heb_rashi'])),
                          profile=self.profile.currentData(), typography='auto')

    def show_draft(self, candidate):
        self._set_result(candidate, final=False)

    def show_final(self, candidates):
        self.candidates = candidates
        candidate = candidates[0]
        if not self.user_edited_draft:
            self._set_result(candidate, final=True)
        if self.settings.value('session_history', True, type=bool):
            retained = self.current_image.copy() if self.current_image is not None and self.settings.value('retain_image', True, type=bool) else None
            self.items.append(CaptureItem(retained, self.internal_text, QRect(self.current_rect),
                                          candidate.confidence, self.profile.currentData(), options=self.last_options,
                                          candidates=candidates))
            self.active_history = len(self.items) - 1
            self.history.addItem(f'◷  {len(self.items)} · {time.strftime("%H:%M:%S")}')
            self.history.blockSignals(True)
            self.history.setCurrentIndex(self.history.count() - 1)
            self.history.blockSignals(False)
            self.history.setToolTip(f'Historique / היסטוריה ({len(self.items)})')
        if self.settings.value('auto_copy', False, type=bool):
            self.copy_all()

    def _set_result(self, candidate: Candidate, final):
        self.current_candidate = candidate
        text = candidate.text
        self.duplicate_chars = 0
        if self.pending_mode == 'append' and self.base_text:
            count, characters = probable_overlap(self.base_text, text)
            self.duplicate_chars = characters
            text = self.base_text.rstrip() + '\n\n' + text
            if count:
                self.duplicate.setText(f'⚠ כפילות אפשרית: {count} מילים בתחילת הלכידה החדשה. הטקסט לא נמחק אוטומטית.')
                self.duplicate.show()
                self.remove_duplicate.show()
                self.keep_duplicate.show()
                self.duplicate_start = len(self.base_text.rstrip()) + 2
        elif self.pending_mode == 'replace':
            self.duplicate.hide()
            self.remove_duplicate.hide()
            self.keep_duplicate.hide()
        self.internal_text = text
        self.editor.blockSignals(True)
        self.editor.setPlainText(self.visible_text(text))
        self._format_editor()
        self.editor.blockSignals(False)
        self.highlight_issues()
        if final:
            self.confidence.setText(f'מדד OCR {candidate.confidence:.0f}/100 · {len(candidate.uncertain)} לבדיקה')
            self.status.setText('✓ הושלם · בדקו את התוצאה מול התמונה')
        else:
            self.confidence.setText('טיוטה מהירה…')
            self.status.setText('משפר את הדיוק…')

    def _format_editor(self):
        cursor = QTextCursor(self.editor.document())
        cursor.select(QTextCursor.SelectionType.Document)
        block = QTextBlockFormat()
        block.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        block.setAlignment(Qt.AlignmentFlag.AlignRight)
        block.setLineHeight(130, 1)
        cursor.mergeBlockFormat(block)

    def visible_text(self, text):
        return text if self.nikud.currentData() == 'keep' else without_nikud(text)

    def apply_nikud(self):
        if self.nikud.currentData() == 'remove':
            self.internal_text = without_nikud(self.internal_text)
        self.editor.blockSignals(True)
        self.editor.setPlainText(self.visible_text(self.internal_text))
        self._format_editor()
        self.editor.blockSignals(False)
        self.save_history_text()

    def edited(self):
        from domain.text import edit_hidden
        visible = self.editor.toPlainText()
        self.internal_text = edit_hidden(self.internal_text, visible) if self.nikud.currentData() == 'hide' else visible
        self.user_edited_draft = True
        self.save_history_text()
        self.dismiss_duplicate()

    def save_history_text(self):
        if 0 <= self.active_history < len(self.items):
            item = self.items[self.active_history]
            item.text = self.internal_text
            item.corrections[item.selected] = self.internal_text

    def dismiss_duplicate(self):
        self.duplicate_chars = 0
        self.duplicate.hide()
        self.remove_duplicate.hide()
        self.keep_duplicate.hide()
        self.highlight_issues()

    def delete_duplicate(self):
        if not self.duplicate_chars:
            return
        if self.duplicate_start:
            start = self.duplicate_start
            self.internal_text = self.internal_text[:start] + self.internal_text[start + self.duplicate_chars:].lstrip()
            self.apply_nikud()
            self.save_history_text()
        self.dismiss_duplicate()

    def copy_all(self):
        text = self.editor.toPlainText()
        QApplication.clipboard().setText(text)
        self.status.setText('✓ הטקסט הועתק')
        if self.settings.value('close_after_copy', False, type=bool):
            self.hide()

    def show_capture_image(self, image):
        self.image_panel.set_image(image)

    def highlight_issues(self):
        selections = []
        if self.duplicate_chars:
            cursor = QTextCursor(self.editor.document())
            start = len(self.visible_text(self.internal_text[:self.duplicate_start]))
            end = len(self.visible_text(self.internal_text[:self.duplicate_start + self.duplicate_chars]))
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format.setBackground(QColor('#ffd7cf'))
            selections.append(selection)
        if self.current_candidate:
            for word in self.current_candidate.uncertain:
                cursor = QTextCursor(self.editor.document())
                while True:
                    cursor = self.editor.document().find(word, cursor)
                    if cursor.isNull():
                        break
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = cursor
                    selection.format.setBackground(QColor('#fff0b6'))
                    selection.format.setToolTip('מילה לא ודאית — השוו לתמונה')
                    selections.append(selection)
        self.editor.setExtraSelections(selections)

    def highlight_source_word(self):
        if not self.current_candidate:
            return
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText().strip()
        for candidate_word, x, y, w, h, confidence in self.current_candidate.boxes:
            if candidate_word == word:
                self.image_panel.set_highlight((x, y, w, h))
                return
        self.image_panel.set_highlight(None)

    def position_near(self, rect):
        screen = QApplication.screenAt(rect.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        size = self.size()
        candidates = [QPoint(rect.right() + 12, rect.top()), QPoint(rect.left() - size.width() - 12, rect.top()),
                      QPoint(rect.left(), rect.bottom() + 12), QPoint(rect.left(), rect.top() - size.height() - 12)]
        for point in candidates:
            trial = QRect(point, size)
            if area.contains(trial) and not trial.intersects(rect):
                self.move(point)
                return
        x = max(area.left(), min(area.right() - size.width(), rect.right() + 12))
        y = max(area.top(), min(area.bottom() - size.height(), rect.top()))
        self.move(x, y)

    def restore_history(self, index):
        if index <= 0 or index > len(self.items):
            return
        item = self.items[index - 1]
        self.active_history = index - 1
        self.current_image, self.current_rect, self.internal_text = item.image.copy() if item.image else None, QRect(item.rect), item.text
        self.candidates = item.candidates
        self.current_candidate = item.candidates[item.selected] if item.candidates else None
        if item.image:
            self.show_capture_image(item.image)
        else:
            self.image_panel.set_image(Image.new('RGB', (1, 1), 'white'))
        self.editor.blockSignals(True)
        self.editor.setPlainText(self.visible_text(item.text))
        self._format_editor()
        self.editor.blockSignals(False)
        self.highlight_issues()
        self.dismiss_duplicate()
        self.confidence.setText(f'מדד OCR {item.confidence:.0f}/100')

    def apply_display(self, index):
        mini = index == 1
        full = index == 2
        self.image_panel.setVisible(not mini and self.settings.value('show_image', True, type=bool))
        self.profile.setVisible(full)
        self.script.setVisible(full)
        self.nikud.setVisible(full)
        self.confidence.setVisible(not mini)
        self.pro_button.setVisible(not mini)
        if mini:
            self.resize(520, 300)

    def toggle_pin(self, enabled):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()

    def next_issue(self):
        if not self.current_candidate or not self.current_candidate.uncertain:
            return
        self.issue_index = (self.issue_index + 1) % len(self.current_candidate.uncertain)
        word = self.current_candidate.uncertain[self.issue_index]
        cursor = self.editor.document().find(word, self.editor.textCursor())
        if cursor.isNull():
            cursor = self.editor.document().find(word)
        if not cursor.isNull():
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()

    def retranslate(self):
        lang = self.language.currentData()
        texts = {
            'he': ('לכידת אזור', '+ הוסף', 'בצע שוב', 'פתח מצב מקצועי', 'העתק הכול'),
            'fr': ('Capturer une zone', '+ Ajouter', 'Refaire', 'Mode professionnel', 'Copier tout'),
            'en': ('Capture area', '+ Add', 'Redo', 'Professional mode', 'Copy all'),
        }[lang]
        for widget, value in zip([self.capture_button, self.add_button, self.redo_button, self.pro_button, self.copy_button], texts):
            widget.setText(value)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if lang == 'he' else Qt.LayoutDirection.LeftToRight)
        self.editor.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    def worker_finished(self):
        self.progress.hide()
        self.capture_button.setEnabled(True)
        self.worker.deleteLater()
        self.worker = None

    def show_error(self, message):
        self.status.setText('שגיאת OCR · ' + message)
        self.show()

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancel.set()
            event.ignore()
            return
        self.settings.setValue('always_on_top', self.pin.isChecked())
        self.settings.setValue('display', self.display.currentIndex())
        self.settings.setValue('language', self.language.currentData())
        self.settings.setValue('profile', self.profile.currentData())
        self.hotkeys.close()
        event.accept()


QUICK_STYLE = '''
QWidget#quickRoot { background: #f7f7f2; }
QLabel#quickTitle { font-size: 19px; font-weight: 650; color: #123e34; }
QWidget#quickImage { background: #e4eae3; border-radius: 9px; color: #60766c; font-size: 16px; }
QTextEdit#quickEditor { background: #fffef9; border: 1px solid #dce3d8; border-radius: 9px; padding: 14px; font-family: Arial; font-size: 22px; }
QLabel#quickMeta { color: #687b72; font-size: 12px; }
QLabel#duplicateWarning { background: #fff0ea; color: #9b3e2e; border: 1px solid #ecc4b9; border-radius: 7px; padding: 8px; }
QLabel#privacyBadge { background: #e7f2ea; color: #185b49; border-radius: 8px; padding: 11px; }
QGroupBox { border: 1px solid #dbe3da; border-radius: 8px; margin-top: 12px; padding: 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; right: 10px; padding: 0 6px; }
'''
