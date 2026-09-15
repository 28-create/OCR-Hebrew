from pathlib import Path
import os
import sys
import time
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).parent / 'aleph'))
from PIL import Image
from PySide6.QtCore import QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from core import ASSETS, probable_overlap, hebrew_typography, repair_mixed_rtl, without_nikud
from quick import QuickWindow, CaptureOverlay, qimage_to_pil, QUICK_STYLE
from widgets import STYLE, init_fonts

def wait_worker(window, app):
    deadline = time.monotonic() + 90
    while window.worker and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(30)
    assert window.worker is None

def test_hebrew_rules_and_overlap():
    assert hebrew_typography('רש"י כתב') == 'רש״י כתב'
    assert without_nikud('שָׁלוֹם') == 'שלום'
    assert repair_mixed_rtl('document.pdf בשנת 2026 נכתב') == 'בשנת 2026 נכתב document.pdf'
    count, chars = probable_overlap('אמר משה אל העם', 'משה אל העם ויאמר')
    assert count == 3 and chars == len('משה אל העם')
    assert probable_overlap('טקסט אחד', 'טקסט אחר') == (0, 0)

def test_quick_ocr_append_and_nikud(tmp_path):
    app = QApplication.instance() or QApplication([])
    init_fonts()
    app.setStyleSheet(STYLE + QUICK_STYLE)
    window = QuickWindow()
    window.script.setCurrentIndex(window.script.findData('square'))
    image = Image.open(ASSETS / 'demo-square.png')
    window.pending_mode = 'replace'
    window.current_image, window.current_rect = image, QRect(100, 100, 600, 200)
    window.start_ocr(image, window.current_rect)
    wait_worker(window, app)
    first = window.internal_text
    assert 'ברוכים הבאים' in first
    assert window.history.count() == 2
    window.pending_mode = 'append'
    window.start_ocr(image, QRect(100, 320, 600, 200))
    wait_worker(window, app)
    assert window.internal_text.count('ברוכים הבאים') == 2
    assert not window.remove_duplicate.isHidden()
    window.delete_duplicate()
    assert window.internal_text.count('ברוכים הבאים') == 1
    window.internal_text = 'שָׁלוֹם'
    window.nikud.setCurrentIndex(window.nikud.findData('hide'))
    assert window.editor.toPlainText() == 'שלום'
    window.nikud.setCurrentIndex(window.nikud.findData('keep'))
    assert window.editor.toPlainText() == 'שָׁלוֹם'
    window.dirty = False
    window.close()
    QApplication.clipboard().clear()
