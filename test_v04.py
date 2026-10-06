"""Regression gates for the stable v0.4 capture and raw-text contract."""
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).parent / 'aleph'))
from PIL import Image
from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QTabWidget
import pytest

import core
from core import ASSETS, Candidate, Options
from ocr.faithful import recognize_faithful
from ui.main_window import MainWindow, QSettings
from ui.settings import SettingsDialog
from domain.session import RawReading
from widgets import init_fonts


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    init_fonts()
    w = MainWindow()
    w.show()
    app.processEvents()
    yield w
    if w.worker:
        w.worker.cancel.set()
        while w.worker:
            app.processEvents()
            QTest.qWait(20)
    w.close()
    QApplication.clipboard().clear()


def wait_ocr(window):
    app = QApplication.instance()
    deadline = time.monotonic() + 40
    while window.worker and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(20)
    assert window.worker is None


def test_one_model_one_rectangle_exact_raw_and_cache(monkeypatch):
    seen = []
    def raw_engine(image, lang, psm, cancel, label, preserve_text=False, dpi=360):
        seen.append((image.tobytes(), lang, psm, preserve_text, dpi))
        return Candidate('וְלְמָה גֶּזר עַלִיהֶם...\nכַּשעְלֶה סנֶחריב', 80, [], label, 4)
    monkeypatch.setattr(core, 'run_tesseract', raw_engine)
    monkeypatch.setattr('ocr.segmentation.segment', lambda *args: pytest.fail('automatic segmentation ran'))
    image = Image.new('RGB', (103, 71), '#eeccaa')
    options = Options(script='rashi', layout='block', dpi=300, pipeline='faithful')
    result = core.recognize(image, options, threading.Event())
    assert len(result) == 1 and result[0].text == 'וְלְמָה גֶּזר עַלִיהֶם...\nכַּשעְלֶה סנֶחריב'
    assert seen == [(core.preprocess(image, False).tobytes(), 'heb_rashi', 6, True, 300)]
    result[0].text = 'une correction inventée'
    reused = recognize_faithful(image, options, threading.Event())
    assert reused.text != result[0].text and len(seen) == 1


def test_window_is_normal_and_capture_waits_for_user(window):
    # An old preference must not silently restore the v0.3 always-on-top state.
    window.settings.setValue('always_on_top', True)
    window.apply_preferences()
    assert not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    window.capture.arm()
    assert window.capture.state == 'ready'
    assert window.capture.overlays == []
    assert window.capture.ready_bar.isVisible()
    window.capture.cancel()
    assert window.capture.state == 'idle'
    assert window.capture.ready_bar is None
    assert window.isVisible()


def test_actual_ocr_keeps_raw_separate_from_edits_and_png(window, tmp_path, monkeypatch):
    image = Image.open(ASSETS / 'demo-square.png').convert('RGB')
    window.receive_capture(image, QRect(30, 40, 200, 100))
    record = window.current_record
    assert record.raw_text == '' and record.image.tobytes() == image.tobytes()
    destination = tmp_path / 'source.png'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(destination), 'PNG (*.png)'))
    window.save_image()
    assert Image.open(destination).tobytes() == image.tobytes()
    window.recognize()
    wait_ocr(window)
    assert 'ברוכים הבאים' in record.raw_text
    original = record.raw_text
    window.editor.setPlainText('édition manuelle')
    assert record.edited_text == 'édition manuelle'
    assert record.raw_text == original
    window.show_record(0)
    assert record.image.tobytes() == image.tobytes()


def test_hide_niqqud_preserves_canonical_copy_and_raw(window):
    record = window._add_record(Image.new('RGB', (30, 20), 'white'), 'nikud.png')
    record.reading = RawReading('שָׁלוֹם עוֹלָם', 'heb', 90)
    record.edited_text = record.raw_text
    window.settings.setValue('v04_nikud', 'hide')
    window.apply_preferences()
    assert window.editor.toPlainText() == 'שלום עולם'
    window.editor.setPlainText('שלום עולם חדש')
    assert record.edited_text == 'שָׁלוֹם עוֹלָם חדש'
    window.copy_text()
    assert QApplication.clipboard().text() == record.edited_text
    window.settings.setValue('v04_nikud', 'remove')
    window.apply_preferences()
    assert record.edited_text == 'שלום עולם חדש'
    assert record.raw_text == 'שָׁלוֹם עוֹלָם'


def test_manual_selection_creates_one_new_source_block(window, monkeypatch):
    image = Image.new('RGB', (100, 100), 'white')
    image.paste('red', (25, 25, 75, 75))
    record = window._add_record(image, 'page.png')
    captured = []
    def one_call(image, lang, psm, cancel, label, preserve_text=False, dpi=360):
        captured.append(image.copy())
        return Candidate('טקסט', 80, [], label, 1)
    monkeypatch.setattr(core, 'run_tesseract', one_call)
    window.image_panel.selection = QRectF(25, 25, 50, 50)
    window.recognize()
    wait_ocr(window)
    assert len(window.records) == 2
    assert window.records[0] is record
    assert window.current_record.image.size == (50, 50)
    assert captured[0].tobytes() == core.preprocess(image.crop((25, 25, 75, 75)), False).tobytes()
    assert window.current_record.raw_text == 'טקסט'


def test_pdf_requires_a_manual_region(window, tmp_path):
    path = tmp_path / 'single-page.pdf'
    Image.new('RGB', (160, 110), 'white').save(path, 'PDF')
    window.open_document(str(path))
    assert window.document.is_pdf
    window.recognize()
    assert window.worker is None
    assert window.status.text() == window.t('select_block_first')


def test_rerun_preserves_the_first_raw_reading(window, monkeypatch):
    calls = []
    def engine(image, lang, psm, cancel, label, preserve_text=False, dpi=360):
        calls.append(lang)
        return Candidate('הטקסט הראשון' if lang == 'heb' else 'טקסט חדש', 80, [], label, 2)
    monkeypatch.setattr(core, 'run_tesseract', engine)
    first = window._add_record(Image.new('RGB', (37, 29), '#abc123'), 'sample.png')
    window.recognize()
    wait_ocr(window)
    assert first.raw_text == 'הטקסט הראשון'
    window.settings.setValue('v04_script', 'rashi')
    window.recognize()
    wait_ocr(window)
    assert len(window.records) == 2 and calls == ['heb', 'heb_rashi']
    assert first.raw_text == 'הטקסט הראשון'
    assert window.current_record.raw_text == 'טקסט חדש'


def test_settings_are_grouped_and_main_bar_is_simple(window):
    dialog = SettingsDialog(window)
    tabs = dialog.findChild(QTabWidget)
    assert tabs.count() == 5
    assert window.settings.value('v04_script', 'square') == 'square'
    assert not hasattr(window, 'display')
    assert not hasattr(window, 'resolution_combo')
    assert window.zoom_out.width() == 32 and window.zoom_in.width() == 32
    dialog.close()


def test_capture_window_reports_grab_failure_without_crashing(window):
    window.capture.capture_window()
    assert window.capture.state == 'ready'
    window.capture._foreground_window()
    assert window.capture.state == 'idle'
    assert window.status.text() == f'{window.t("error")} · {window.t("capture_failed")}'


def test_duplicate_suspicion_warns_but_never_deletes(window, monkeypatch):
    def engine(image, lang, psm, cancel, label, preserve_text=False, dpi=360):
        return Candidate('בראשית ברא אלוהים את השמים ואת הארץ', 90, [], label, 7)
    monkeypatch.setattr(core, 'run_tesseract', engine)
    window._add_record(Image.new('RGB', (40, 30), 'white'), 'first.png')
    window.recognize()
    wait_ocr(window)
    assert window.current_record.overlap_words == 0
    window._add_record(Image.new('RGB', (40, 30), 'white'), 'second.png')
    window.recognize()
    wait_ocr(window)
    assert len(window.records) == 2
    assert window.current_record.overlap_words == 7
    assert window.t('duplicate') in window.status.text()
    assert window.current_record.raw_text == 'בראשית ברא אלוהים את השמים ואת הארץ'


def test_delete_record_keeps_neighbours_and_clears_last(window):
    first = window._add_record(Image.new('RGB', (30, 20), 'white'), 'a.png')
    first.edited_text = 'texte un'
    second = window._add_record(Image.new('RGB', (30, 20), 'white'), 'b.png')
    second.edited_text = 'texte deux'
    window.show_record(0)
    window.delete_record(0)
    assert len(window.records) == 1
    assert window.current_record is second
    assert window.editor.toPlainText() == 'texte deux'
    window.delete_record(0)
    assert window.records == [] and window.current_record is None
    assert window.editor.toPlainText() == ''
