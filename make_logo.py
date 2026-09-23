"""Render the canonical SVG into sharp application and Windows icon assets."""
from pathlib import Path
import sys

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "aleph" / "assets"
application = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
image = QImage(512, 512, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
QSvgRenderer(str(ASSETS / "logo.svg")).render(painter)
painter.end()
image.save(str(ASSETS / "logo.png"))
with Image.open(ASSETS / "logo.png") as source:
    source.save(ASSETS / "app.ico", format="ICO",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                       (64, 64), (128, 128), (256, 256)])
