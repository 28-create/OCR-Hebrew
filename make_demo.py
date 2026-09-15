"""Generate a reproducible OCR fixture and the application icon."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).parent / 'aleph'))
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QFont, QFontDatabase, QColor
from PySide6.QtWidgets import QApplication
from PIL import Image
from core import ASSETS
from widgets import app_icon, init_fonts

application = QApplication([])
init_fonts()
font_id = QFontDatabase.addApplicationFont(str(ASSETS / 'fonts/NotoRashiHebrew.ttf'))
rashi_family = QFontDatabase.applicationFontFamilies(font_id)[0]
square_lines = ['ברוכים הבאים לאוצר הספרים', 'כאן אפשר לקרוא טקסט בעברית ולהעתיק אותו', 'בחרו קטע מתוך העמוד ובדקו את התוצאה']
rashi_lines = ['פירוש הדברים נכתב באותיות רש״י', 'כל אדם יכול ללמוד מתוך הספר', 'טוב לעיין בדברים ולקרוא אותם בנחת']
image = QImage(1700, 1450, QImage.Format.Format_RGB32)
image.fill(QColor('#fffefa'))
painter = QPainter(image)
painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
painter.setPen(QColor('#617569'))
painter.setFont(QFont('Segoe UI', 19))
painter.drawText(QRectF(100, 45, 1500, 55), Qt.AlignmentFlag.AlignLeft, 'CAPTURE OTZAR  /  DOCUMENT DE DÉMONSTRATION')
painter.setPen(QColor('#123e34'))
painter.setFont(QFont('Segoe UI', 23, QFont.Weight.DemiBold))
painter.drawText(QRectF(100, 150, 1500, 70), Qt.AlignmentFlag.AlignLeft, '01  Hébreu classique')
painter.setPen(QColor('#161e18'))
painter.setFont(QFont('Arial', 43))
for n, line in enumerate(square_lines):
    painter.drawText(QRectF(110, 270 + n * 110, 1450, 95), Qt.AlignmentFlag.AlignRight, line)
painter.setPen(QColor('#d7ded2'))
painter.drawLine(100, 650, 1600, 650)
painter.setPen(QColor('#123e34'))
painter.setFont(QFont('Segoe UI', 23, QFont.Weight.DemiBold))
painter.drawText(QRectF(100, 710, 1500, 70), Qt.AlignmentFlag.AlignLeft, '02  Écriture Rachi')
painter.setPen(QColor('#161e18'))
painter.setFont(QFont(rashi_family, 43))
for n, line in enumerate(rashi_lines):
    painter.drawText(QRectF(110, 825 + n * 110, 1450, 100), Qt.AlignmentFlag.AlignRight, line)
painter.setPen(QColor('#738174'))
painter.setFont(QFont('Segoe UI', 18))
painter.drawText(QRectF(100, 1290, 1500, 80), Qt.AlignmentFlag.AlignLeft, 'Sélectionnez un paragraphe. Choisissez son écriture, puis lancez la reconnaissance.')
painter.end()
image.save(str(ASSETS / 'demo.png'))
image.copy(80, 245, 1530, 370).save(str(ASSETS / 'demo-square.png'))
image.copy(80, 800, 1530, 375).save(str(ASSETS / 'demo-rashi.png'))
(ASSETS / 'demo-truth.json').write_text(json.dumps({'square': '\n'.join(square_lines), 'rashi': '\n'.join(rashi_lines)}, ensure_ascii=False, indent=2), encoding='utf-8')
app_icon().pixmap(128, 128).save(str(ASSETS / 'logo.png'))
Image.open(ASSETS / 'logo.png').save(ASSETS / 'app.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128)])
print('Demo and logo generated.')
