"""Render the canonical SVG independently at every native Windows icon size."""
from pathlib import Path
import sys

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "aleph" / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(renderer, size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return Image.frombytes('RGBA', (size, size), image.bits().tobytes(), 'raw', 'BGRA')


def main():
    application = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(ASSETS / 'logo.svg'))
    if not renderer.isValid():
        raise ValueError('Canonical logo.svg is not a valid SVG')
    render(renderer, 512).save(ASSETS / 'logo.png')
    icons = {size: render(renderer, size) for size in SIZES}
    icons[256].save(ASSETS / 'app.ico', format='ICO',
                    sizes=[(size, size) for size in SIZES],
                    append_images=[icons[size] for size in SIZES if size != 256])
    print('Canonical SVG, PNG and native-size ICO icons ready.', flush=True)


if __name__ == '__main__':
    main()
