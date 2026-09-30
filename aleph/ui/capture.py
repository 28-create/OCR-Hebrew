"""Non-modal ready state; desktop selection starts only on explicit activation."""
import time
from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QLabel, QPushButton
from quick import CaptureOverlay


class ReadyBar(QWidget):
    selectRequested = Signal()
    cancelled = Signal()

    def __init__(self, owner):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle('Aleph OCR')
        self.setLayoutDirection(owner.layoutDirection())
        self.setStyleSheet('QWidget { background:#123e34; color:#fffaf0; border-radius:8px; }'
                           'QPushButton { background:#f8f4e9; color:#123e34; padding:8px 12px; }')
        layout = QHBoxLayout(self)
        label = QLabel(owner.t('capture_ready'))
        label.setToolTip(owner.t('capture_ready_help'))
        layout.addWidget(label)
        select = QPushButton(owner.t('select_now'))
        select.clicked.connect(self.selectRequested)
        layout.addWidget(select)
        cancel = QPushButton('×')
        cancel.setAccessibleName(owner.t('cancel'))
        cancel.setToolTip(owner.t('cancel'))
        cancel.clicked.connect(self.cancelled)
        layout.addWidget(cancel)
        self.adjustSize()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.top() + 18)


class CaptureController(QObject):
    captured = Signal(object, object)
    stateChanged = Signal(str)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.state = 'idle'
        self.ready_bar = None
        self.overlays = []
        self.capture_ms = 0
        self._maximized = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show_overlays)

    def set_state(self, state):
        self.state = state
        self.stateChanged.emit(state)

    def arm(self):
        if self.owner.worker or self.state != 'idle':
            return
        self._maximized = self.owner.isMaximized()
        self.set_state('ready')
        self.ready_bar = ReadyBar(self.owner)
        self.ready_bar.selectRequested.connect(self.begin_selection)
        self.ready_bar.cancelled.connect(self.cancel)
        self.owner.showMinimized()
        self.ready_bar.show()

    def begin_selection(self):
        if self.owner.worker or self.state == 'selecting':
            return
        if self.state == 'idle':
            self.arm()
        if self.state != 'ready':
            return
        if self.ready_bar:
            self.ready_bar.hide()
        self.owner.showMinimized()
        self.set_state('selecting')
        # Let the floating button disappear before taking the desktop snapshot.
        self._timer.start(180)

    def _show_overlays(self):
        if self.state != 'selecting':
            return
        started = time.perf_counter()
        screens = QApplication.screens()
        snapshots = [(screen, screen.grabWindow(0)) for screen in screens]
        self.capture_ms = (time.perf_counter() - started) * 1000
        if any(image.isNull() for _, image in snapshots):
            self.cancel()
            self.owner.show_error(self.owner.t('capture_failed'))
            return
        for screen, screenshot in snapshots:
            overlay = CaptureOverlay(screen, screenshot)
            overlay.hint = self.owner.t('capture_hint')
            overlay.selected.connect(self._selected)
            overlay.cancelled.connect(self.cancel)
            self.overlays.append(overlay)
        for overlay in self.overlays:
            overlay.show()
        active = next((o for o in self.overlays if o.geometry().contains(QCursor.pos())), None)
        if active:
            active.activateWindow()

    def _selected(self, image, rect):
        self.cleanup()
        self.restore_owner()
        self.captured.emit(image, rect)

    def restore_owner(self):
        if self._maximized:
            self.owner.showMaximized()
        else:
            self.owner.showNormal()
        self.owner.raise_()
        self.owner.activateWindow()

    def cancel(self):
        self.cleanup()
        self.restore_owner()

    def cleanup(self):
        self._timer.stop()
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.overlays = []
        if self.ready_bar:
            self.ready_bar.close()
            self.ready_bar.deleteLater()
            self.ready_bar = None
        self.set_state('idle')
