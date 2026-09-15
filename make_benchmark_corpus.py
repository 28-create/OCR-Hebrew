from pathlib import Path
import json
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QFont, QColor, QFontDatabase
from PySide6.QtWidgets import QApplication
from PIL import Image, ImageEnhance
import sys
sys.path.insert(0, str(Path(__file__).parent / 'aleph'))
from core import ASSETS
from widgets import init_fonts

ROOT = Path(__file__).parent / 'corpus-v02'
ROOT.mkdir(exist_ok=True)
app = QApplication([])
init_fonts()
font_id = QFontDatabase.addApplicationFont(str(ASSETS / 'fonts/NotoRashiHebrew.ttf'))
rashi = QFontDatabase.applicationFontFamilies(font_id)[0]

def page(name, lines, font='Arial', color='#171b18', background='#fffef8', columns=None):
    image = QImage(1500, 760, QImage.Format.Format_RGB32)
    image.fill(QColor(background))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setPen(QColor(color))
    painter.setFont(QFont(font, 40))
    if columns:
        for x, values in [(780, columns[0]), (40, columns[1])]:
            for n, text in enumerate(values):
                painter.drawText(QRectF(x, 110+n*115, 650, 90), Qt.AlignmentFlag.AlignRight, text)
    else:
        for n, text in enumerate(lines):
            painter.drawText(QRectF(70, 100+n*120, 1360, 95), Qt.AlignmentFlag.AlignRight, text)
    painter.end()
    path = ROOT / f'{name}.png'
    image.save(str(path))
    return path

truth = {}
truth['mixed'] = ['בשנת 2026 נכתב document.pdf', 'בתוך המסמך כתוב texte français', 'בתוך הטקסט מופיעות English words']
page('mixed', truth['mixed'])
truth['nikud'] = ['בְּרֵאשִׁית בָּרָא אֱלֹהִים', 'שָׁלוֹם עוֹלָם', 'רש״י ורמב״ם']
page('nikud', truth['nikud'])
truth['low_contrast'] = ['אמר רבי משה אל העם', 'וכן כתב הרמב״ם בהלכותיו', 'שו״ת ודברי חכמים']
page('low_contrast', truth['low_contrast'], color='#77736a', background='#ddd3b9')
truth['columns'] = ['טור ימין ראשון', 'טור ימין שני', 'טור שמאל ראשון', 'טור שמאל שני']
page('columns', [], columns=(truth['columns'][:2], truth['columns'][2:]))
source = Image.open(page('skew_source', ['עמוד מעט עקום לבדיקה', 'האותיות צריכות להישאר ברורות']))
truth['skew'] = ['עמוד מעט עקום לבדיקה', 'האותיות צריכות להישאר ברורות']
source.rotate(2.2, expand=True, fillcolor='#fffef8').save(ROOT / 'skew.png')
(ROOT / 'truth.json').write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding='utf-8')
print(ROOT)
