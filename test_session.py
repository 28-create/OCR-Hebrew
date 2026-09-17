from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'aleph'))
from PIL import Image
from PySide6.QtCore import Qt, QRect
from PySide6.QtWidgets import QApplication
from core import Candidate, Document, probable_overlap, without_nikud
from domain.text import edit_hidden
from widgets import init_fonts
from ui.main_window import MainWindow
from ui.i18n import TEXT, tr
import pytest


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    init_fonts()
    window = MainWindow()
    yield window
    window.dirty = False
    window.close()
    QApplication.clipboard().clear()
    app.processEvents()


def test_hidden_nikud_edit_preserves_unaffected_marks():
    canonical = 'שָׁלוֹם עוֹלָם'
    assert edit_hidden(canonical, 'שלום עולם חדש') == canonical + ' חדש'
    assert edit_hidden(canonical, 'שלום לכולם').startswith('שָׁלוֹם ')
    assert edit_hidden(canonical, 'עולם') == 'עוֹלָם'
    assert edit_hidden(canonical, '') == ''


def test_approximate_overlap_returns_canonical_offsets():
    text = 'מֹשֶׁה אֶל הָעָם ויאמר'
    count, end = probable_overlap('אמר משה אל העם', text)
    assert count == 3 and text[:end] == 'מֹשֶׁה אֶל הָעָם'
    assert probable_overlap('אמר משה אל העם', 'משה אל העס ויאמר')[0] == 3


def seed(window):
    window.current_image = Image.new('RGB', (100, 100), 'white')
    window.show_final([Candidate('שָׁלוֹם עוֹלָם', 90, [], 'Smart', 2), Candidate('שלום עולמ', 80, [], 'Raw', 2)])


def test_one_window_switch_preserves_everything(window):
    seed(window)
    window.nikud.setCurrentIndex(1)
    window.editor.setPlainText('שלום עולם חדש')
    before = (window.internal_text, window.current_image, window.items, window.language.currentData(), window.nikud.currentData())
    window.toggle_mode()
    assert window.professional and not window.advanced.isHidden()
    assert (window.internal_text, window.current_image, window.items, window.language.currentData(), window.nikud.currentData()) == before
    window.toggle_mode()
    assert 'ָ' in window.internal_text
    assert not window.open_button.isHidden()
    assert not window.window_button.isHidden()
    assert not window.paste_button.isHidden()
    for index in range(3):
        window.display.setCurrentIndex(index)
        assert not window.open_button.isHidden()


def test_global_language_and_close_strings(window):
    for code in ('he', 'fr', 'en'):
        window.language.setCurrentIndex(window.language.findData(code))
        assert window.open_button.text() == tr('open', code)
        window.toggle_mode()
        assert window.language.currentData() == code
        assert window.t('close_body') == tr('close_body', code)
        assert window.layoutDirection() == (Qt.LayoutDirection.RightToLeft if code == 'he' else Qt.LayoutDirection.LeftToRight)
    assert all(len(translations) == 3 and all(translations) for translations in TEXT.values())


def test_history_retains_image_corrections_and_raw(window):
    seed(window)
    window.editor.setPlainText('תיקון')
    window.select_variant(1)
    assert window.editor.toPlainText() == 'שלום עולמ'
    window.select_variant(0)
    assert window.editor.toPlainText() == 'תיקון'
    window.restore_history(1)
    assert window.current_image.size == (100, 100)
    assert window.editor.toPlainText() == 'תיקון'
    window.settings.setValue('retain_image', False)
    seed(window)
    assert window.items[-1].image is None
    window.restore_history(len(window.items))
    assert window.current_image is None


def test_pages_default_all_and_custom(window, tmp_path):
    file = tmp_path / 'pages.tiff'
    Image.new('RGB', (50,50), 'white').save(file, save_all=True, append_images=[Image.new('RGB', (50,50), 'white') for _ in range(3)])
    window.open_document(str(file))
    assert window.document.pages == 4
    assert window.selected_pages() == [0,1,2,3]
    window.scope.setCurrentIndex(2)
    window.page_range.setText('1-2, 4')
    assert window.selected_pages() == [0,1,3]
    window.scope.setCurrentIndex(1)
    window.page = 2
    assert window.selected_pages() == [2]


def test_final_does_not_overwrite_draft_corrections(window):
    window.current_image = Image.new('RGB', (100,100), 'white')
    window.show_draft(Candidate('שלום', 80, [], 'Raw', 1))
    window.editor.setPlainText('שלום מתוקן')
    window.show_final([Candidate('שלום אחר', 90, [], 'Smart', 2)])
    assert window.internal_text == 'שלום מתוקן'


def test_defaults_and_font_export(window, tmp_path):
    from core import save_text
    import zipfile
    assert window.make_options().languages == ('heb', 'heb_rashi')
    window.settings.setValue('font', 'Times New Roman')
    window.settings.setValue('font_size', 24)
    window.apply_font()
    path = tmp_path / 'font.docx'
    save_text(str(path), 'שלום', 'Times New Roman', 24)
    with zipfile.ZipFile(path) as archive:
        xml = archive.read('word/document.xml').decode()
    assert 'w:cs="Times New Roman"' in xml and 'w:szCs w:val="48"' in xml


def test_close_dialog_uses_global_language(window, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    window.language.setCurrentIndex(window.language.findData('en'))
    window.internal_text, window.dirty = 'שלום', True
    observed = []
    def fake_exec(dialog):
        observed.append((dialog.windowTitle(), dialog.text()))
        return 0
    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert observed == [(tr('close_title', 'en'), tr('close_body', 'en'))]


@pytest.mark.parametrize('ratio', [1, 1.5, 2])
def test_capture_dim_selection_and_hidpi(window, ratio):
    from quick import CaptureOverlay
    from PySide6.QtGui import QPixmap, QColor
    class Screen:
        def geometry(self):
            return QRect(-200, 0, 200, 160)
    screenshot = QPixmap(int(200 * ratio), int(160 * ratio))
    screenshot.fill(QColor('white'))
    screenshot.setDevicePixelRatio(ratio)
    overlay = CaptureOverlay(Screen(), screenshot)
    overlay.selection = QRect(50, 60, 100, 70)
    rendered = overlay.grab().toImage()
    assert rendered.pixelColor(90, 90).red() > 245
    assert rendered.pixelColor(10, 90).red() < 200
    overlay.close()
