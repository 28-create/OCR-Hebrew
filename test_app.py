from pathlib import Path
import os
import sys
import time
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).parent / 'aleph'))
import pytest
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QFont, QPainter, QPdfWriter, QPageSize, QTextCursor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import AlephWindow
from core import Document, ASSETS
from widgets import STYLE, init_fonts

@pytest.fixture(scope='module')
def application():
    app = QApplication.instance() or QApplication([])
    init_fonts()
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    yield app
    # The offscreen platform retains Python MIME ownership until shutdown.
    QApplication.clipboard().clear()
    app.processEvents()

@pytest.fixture
def window(application):
    widget = AlephWindow(settings=False)
    widget.show()
    application.processEvents()
    yield widget
    if widget.worker:
        widget.worker.cancel.set()
        while widget.worker:
            application.processEvents()
            QTest.qWait(20)
    widget.dirty = False
    widget.close()

@pytest.fixture
def sample_pdf(application, tmp_path):
    path = tmp_path / 'test-hebrew.pdf'
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setResolution(72)
    painter = QPainter(writer)
    painter.setFont(QFont('Arial', 24))
    painter.drawText(QRectF(20, 100, 510, 70), Qt.AlignmentFlag.AlignRight, 'שלום עולם')
    writer.newPage()
    painter.drawImage(QRectF(20, 100, 510, 125), QImage(str(ASSETS / 'demo-rashi.png')))
    painter.end()
    del writer
    return path

def wait_job(window, application):
    deadline = time.monotonic() + 90
    while window.worker and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(30)
    assert window.worker is None
    assert not window.errors

def test_pdf_render_extract_crop_and_rotations(sample_pdf):
    document = Document(str(sample_pdf))
    assert document.pages == 2
    text = document.extract(0)
    assert 'שלום' in text and 'עולם' in text
    assert document.extract(1) == ''
    whole = document.render(1, 144)
    crop = document.render(1, 144, box=(.5, 0, 1, .5))
    assert abs(crop.width * 2 - whole.width) <= 1
    assert document.render(1, 144, rotation=90).size == whole.size[::-1]

def test_selection_worker_and_edit_history(window, application):
    window.open_demo()
    application.processEvents()
    view = window.view
    start = view.mapFromScene(QPointF(80, 245))
    end = view.mapFromScene(QPointF(1610, 615))
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    box = view.normalized_selection()
    assert box and abs(box[0] - 80/1700) < .005
    window.script.setCurrentIndex(1)
    window.layout_mode.setCurrentIndex(1)
    window.start_current()
    wait_job(window, application)
    assert len(window.results) == 1
    assert 'ברוכים הבאים' in window.editor.toPlainText()
    cursor = window.editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText('\nבדיקה')
    corrected = window.editor.toPlainText()
    assert window.current_result.text == corrected
    window.variants.setCurrentIndex(1)
    assert 'בדיקה' not in window.editor.toPlainText()
    window.variants.setCurrentIndex(0)
    assert window.editor.toPlainText() == corrected
    window.copy_text()
    assert QApplication.clipboard().text() == corrected
    assert 'dir="rtl"' in QApplication.clipboard().mimeData().html()
    application.processEvents()
    window.grab().save(str(Path(__file__).parent / 'ui-recognition.png'))

def test_batch_pdf(window, application, sample_pdf):
    window.open_document(str(sample_pdf))
    window.page_range.setText('1-2')
    window.enhanced.setChecked(False)
    window.script.setCurrentIndex(0)
    window.start_batch()
    wait_job(window, application)
    assert [result.page for result in window.results] == [0, 1]
    assert 'שלום' in window.results[0].text
    assert len(window.results[1].text) > 20
    window.history.setCurrentIndex(0)
    assert window.editor.toPlainText() == window.results[0].text

def test_cleaning_undo(window):
    window.editor.setPlainText('שָׁלוֹם\nעוֹלָם\n\nספר')
    window.transform_text(vowels=False)
    assert window.editor.toPlainText() == 'שלום\nעולם\n\nספר'
    window.editor.undo()
    assert 'ָ' in window.editor.toPlainText()
