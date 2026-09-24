"""Render four review-only SVG logo proposals at native Windows icon sizes."""

from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parent / 'logo-proposals'
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
DESCRIPTIONS = {
    'A': 'Fidèle au logo initial',
    'B': 'Séparation plus visible',
    'C': 'Traits affinés',
    'D': 'Lisibilité petite taille',
}


def render(svg_path, size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f'Could not render {svg_path}')
    renderer.render(painter)
    painter.end()
    target = ROOT / f'{svg_path.stem}-{size}.png'
    image.save(str(target))
    return Image.open(target).convert('RGBA')


def main():
    application = QGuiApplication(sys.argv[:1])
    font_file = Path('C:/Windows/Fonts/segoeui.ttf')
    bold_file = Path('C:/Windows/Fonts/segoeuib.ttf')
    font = ImageFont.truetype(str(font_file), 18) if font_file.exists() else ImageFont.load_default()
    bold = ImageFont.truetype(str(bold_file), 29) if bold_file.exists() else font
    title = ImageFont.truetype(str(bold_file), 31) if bold_file.exists() else font
    sheet = Image.new('RGB', (1460, 1160), '#f4f6f5')
    draw = ImageDraw.Draw(sheet)
    draw.text((42, 24), 'Aleph OCR · quatre propositions de logo', font=title, fill='#163e35')
    draw.text((42, 68), 'Même identité visuelle ; comparer surtout la séparation des trois barres.', font=font, fill='#415b54')
    for row, letter in enumerate('ABCD'):
        y = 110 + row * 258
        draw.rounded_rectangle((35, y, 1424, y + 238), radius=19, fill='#ffffff', outline='#d5deda', width=2)
        draw.text((59, y + 12), f'{letter}  ·  {DESCRIPTIONS[letter]}', font=bold, fill='#173c33')
        svg = ROOT / f'{letter}.svg'
        images = {size: render(svg, size) for size in SIZES}
        sheet.paste(images[128].resize((154, 154), Image.Resampling.LANCZOS), (80, y + 62), images[128].resize((154, 154), Image.Resampling.LANCZOS))
        draw.text((112, y + 211), 'Logo seul', font=font, fill='#455d56')
        draw.rounded_rectangle((278, y + 60, 482, y + 207), radius=12, fill='#ecf1ef')
        sheet.paste(images[128], (316, y + 70), images[128])
        draw.text((337, y + 211), 'Fond clair', font=font, fill='#455d56')
        draw.rounded_rectangle((510, y + 60, 714, y + 207), radius=12, fill='#1c2c2a')
        sheet.paste(images[128], (548, y + 70), images[128])
        draw.text((569, y + 211), 'Fond foncé', font=font, fill='#455d56')
        for index, size in enumerate((16, 24, 32, 48)):
            x = 756 + index * 83
            draw.rounded_rectangle((x, y + 78, x + 68, y + 153), radius=8, fill='#eff2f0')
            sheet.paste(images[size], (x + (68 - size) // 2, y + 87 + (48 - size) // 2), images[size])
            draw.text((x + 10, y + 163), f'{size}×{size}', font=font, fill='#455d56')
        enlarged = images[32].resize((104, 104), Image.Resampling.NEAREST)
        sheet.paste(enlarged, (1117, y + 77), enlarged)
        draw.text((1102, y + 187), '32× agrandi', font=font, fill='#455d56')
    target = ROOT / 'comparatif.png'
    sheet.save(target)
    print(target)


if __name__ == '__main__':
    main()
