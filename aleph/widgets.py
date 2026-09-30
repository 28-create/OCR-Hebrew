from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from pathlib import Path
import os
import sys
from PySide6.QtGui import QColor, QPen, QBrush, QPixmap, QImage, QPainter, QFont, QIcon, QFontDatabase, QGuiApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem


def app_icon():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    icon = QIcon(str(root / 'assets/app.ico'))
    if not icon.isNull():
        return icon
    pixmap = QPixmap(512, 512)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(root / 'assets/logo.svg')).render(painter)
    painter.end()
    return QIcon(pixmap)


def init_fonts():
    # The offscreen Qt test platform doesn't enumerate Windows fonts by itself.
    if QGuiApplication.platformName() == 'offscreen':
        directory = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for name in ['segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf', 'seguisym.ttf', 'arial.ttf', 'arialbd.ttf', 'times.ttf']:
            if (directory / name).exists():
                QFontDatabase.addApplicationFont(str(directory / name))


def pil_pixmap(image):
    rgb = image.convert('RGB')
    data = rgb.tobytes()
    return QPixmap.fromImage(QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888).copy())


class PageView(QGraphicsView):
    selectionChanged = Signal(bool)
    zoomChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName('pageView')
        self.canvas = QGraphicsScene(self)
        self.setScene(self.canvas)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.page_rect = QRectF()
        self.selection = None
        self.overlay = None
        self.origin = None
        self.word_highlight = None
        self.auto_fit = True
        self.setMinimumWidth(240)

    def set_image(self, image):
        self.canvas.clear()
        self.word_highlight = None
        self.overlay = None
        self.selection = None
        self.origin = None
        item = self.canvas.addPixmap(pil_pixmap(image))
        self.page_rect = item.boundingRect()
        self.canvas.setSceneRect(self.page_rect.adjusted(-18, -18, 18, 18))
        self.fit_page()
        self.selectionChanged.emit(False)

    def set_highlight(self, box):
        if self.word_highlight is not None:
            self.canvas.removeItem(self.word_highlight)
            self.word_highlight = None
        if box and not self.page_rect.isEmpty():
            x, y, w, h = box
            rect = QRectF(x * self.page_rect.width(), y * self.page_rect.height(), w * self.page_rect.width(), h * self.page_rect.height())
            self.word_highlight = self.canvas.addRect(rect, QPen(QColor('#cc8f35'), 2), QBrush(QColor(255, 191, 72, 65)))

    def fit_page(self):
        self.auto_fit = True
        if not self.page_rect.isEmpty():
            self.fitInView(self.page_rect.adjusted(-14, -14, 14, 14), Qt.AspectRatioMode.KeepAspectRatio)
            self.zoomChanged.emit(round(self.transform().m11() * 100))

    def zoom(self, factor):
        target = self.transform().m11() * factor
        if .05 < target < 8:
            self.auto_fit = False
            self.scale(factor, factor)
            self.zoomChanged.emit(round(self.transform().m11() * 100))

    def clear_selection(self):
        if self.overlay:
            self.canvas.removeItem(self.overlay)
            self.overlay = None
        self.selection = None
        self.selectionChanged.emit(False)

    def normalized_selection(self):
        if self.selection and not self.page_rect.isEmpty():
            r = self.selection
            return r.left() / self.page_rect.width(), r.top() / self.page_rect.height(), r.right() / self.page_rect.width(), r.bottom() / self.page_rect.height()
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.page_rect.isEmpty():
            point = self.mapToScene(event.position().toPoint())
            if self.page_rect.contains(point):
                self.clear_selection()
                self.origin = point
                self.overlay = QGraphicsRectItem(QRectF(point, point))
                pen = QPen(QColor('#168675'), 2)
                pen.setCosmetic(True)
                self.overlay.setPen(pen)
                self.overlay.setBrush(QBrush(QColor(20, 120, 100, 45)))
                self.canvas.addItem(self.overlay)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            rect = QRectF(self.origin, self.mapToScene(event.position().toPoint())).normalized().intersected(self.page_rect)
            self.overlay.setRect(rect)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.origin is not None:
            rect = self.overlay.rect()
            self.origin = None
            if rect.width() >= 8 and rect.height() >= 8:
                self.selection = rect
                self.selectionChanged.emit(True)
            else:
                self.clear_selection()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1.18 if event.angleDelta().y() > 0 else 1 / 1.18)
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.clear_selection()
        self.fit_page()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit:
            self.fit_page()

    def clear_image(self):
        self.canvas.clear()
        self.page_rect = QRectF()
        self.selection = self.overlay = self.origin = self.word_highlight = None
        self.selectionChanged.emit(False)


STYLE = '''
QMainWindow { background: #f5f5ef; }
QWidget { font-family: "Segoe UI"; font-size: 13px; color: #223831; }
QFrame#header { background: #ffffff; border-bottom: 1px solid #dce4dd; }
QLabel#brand { font-size: 25px; font-weight: 650; color: #123e34; letter-spacing: -0.6px; }
QLabel#tagline { color: #79867e; font-size: 12px; }
QLabel#badge { background: #e6f3eb; color: #22644f; border-radius: 12px; padding: 5px 12px; font-size: 11px; font-weight: 600; }
QFrame#panel { background: #ffffff; border: 1px solid #dce4dd; border-radius: 12px; }
QLabel#section { color: #829088; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QLabel#panelTitle { font-size: 16px; font-weight: 650; }
QLabel#muted { color: #79867e; font-size: 12px; }
QLabel#hint { color: #61756a; font-size: 12px; background: #f0f5ef; border-radius: 8px; padding: 10px; }
QLabel#emptyTitle { font-size: 26px; font-weight: 600; color: #33584c; }
QLabel#emptyMark { font-family: "Times New Roman"; font-size: 88px; color: #146b5b; }
QPushButton { background: #ffffff; border: 1px solid #d4dfd7; border-radius: 7px; padding: 8px 11px; font-weight: 500; }
QPushButton:hover { background: #edf5ef; border-color: #8db5a1; }
QPushButton:pressed { background: #d9ebde; }
QPushButton:disabled { color: #a8b4ab; background: #f3f5f1; border-color: #e6ebe4; }
QPushButton#primary { color: #ffffff; background: #146b5b; border: 1px solid #146b5b; padding: 11px 14px; font-weight: 600; }
QPushButton#primary:hover { background: #0d5749; }
QPushButton#primary:disabled { background: #9bbfb0; border-color: #9bbfb0; }
QPushButton#subtle { border: none; background: transparent; color: #668477; }
QPushButton#danger { color: #a24d3b; }
QComboBox, QSpinBox, QLineEdit { background: #fafbf8; border: 1px solid #d6dfd6; border-radius: 6px; padding: 7px; min-height: 18px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #d8ebdf; selection-color: #174f40; }
QComboBox::drop-down { border: none; width: 22px; }
QCheckBox { spacing: 7px; padding: 4px 0; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { background: #fff; border: 1px solid #b8cabd; border-radius: 4px; }
QCheckBox::indicator:checked { background: #146b5b; border: 1px solid #146b5b; border-radius: 4px; }
QGraphicsView#pageView { border: none; background: #e7ece5; border-radius: 7px; }
QTextEdit { background: #fffef9; border: 1px solid #e2e6db; border-radius: 8px; padding: 12px; selection-background-color: #c4e3d4; selection-color: #173e32; }
QTextEdit#hebrewEditor { font-family: "Arial"; font-size: 23px; }
QScrollArea { border: none; background: transparent; }
QWidget#settingsBody { background: #ffffff; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #c7d4ca; border-radius: 4px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSplitter::handle { background: transparent; width: 9px; }
QProgressBar { background: #e6ece5; border: none; border-radius: 4px; height: 7px; text-align: center; }
QProgressBar::chunk { background: #388d70; border-radius: 4px; }
QStatusBar { background: #edf2eb; color: #617568; font-size: 12px; }
QToolTip { background: #193e32; color: #ffffff; border: none; padding: 7px; }
'''
