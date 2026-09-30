from pathlib import Path
import json
import sys
import threading
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).parent / 'aleph'))
import pytest
from PIL import Image
from core import ASSETS, Options, Document, clean_text, parse_pages, recognize, save_text, Cancelled


def test_hebrew_unicode_and_vowels():
    assert clean_text('\u200fשָׁלוֹם\r\nעוֹלָם', vowels=False) == 'שלום\nעולם'
    assert clean_text('שלום\nעולם\n\nספר חדש', join_lines=True) == 'שלום עולם\n\nספר חדש'
    assert clean_text('שנת 2026 abc רש״י') == 'שנת 2026 abc רש״י'


def test_page_ranges():
    assert parse_pages('1-3, 2, 5', 6) == [0, 1, 2, 4]
    assert parse_pages('', 3) == [0, 1, 2]
    for invalid in ['0', '7', '4-2', '1,,3', '-2', 'a', '1-900000000']:
        with pytest.raises(ValueError):
            parse_pages(invalid, 6)


def test_image_crop_rotation(tmp_path):
    image = Image.new('RGB', (100, 60), 'white')
    image.paste('red', (50, 0, 100, 60))
    path = tmp_path / 'test.png'
    image.save(path)
    doc = Document(str(path))
    crop = doc.render(0, box=(.5, 0, 1, 1))
    assert crop.size == (50, 60)
    assert crop.getpixel((10, 10)) == (255, 0, 0)
    assert doc.render(0, rotation=90).size == (60, 100)


def test_rtl_docx_and_utf8(tmp_path):
    text = 'שלום עולם\nרש״י — 2026 & <בדיקה>'
    docx = tmp_path / 'result.docx'
    save_text(str(docx), text)
    with zipfile.ZipFile(docx) as archive:
        xml = ET.fromstring(archive.read('word/document.xml'))
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    assert '\n'.join(node.text for node in xml.findall('.//w:t', ns)) == text
    assert len(xml.findall('.//w:bidi', ns)) == 2
    target = tmp_path / 'result.txt'
    save_text(str(target), text)
    assert target.read_text(encoding='utf-8-sig') == text


def test_cancel_before_ocr():
    event = threading.Event()
    event.set()
    with pytest.raises(Cancelled):
        recognize(Image.new('RGB', (600, 150), 'white'), Options(), event)


@pytest.mark.parametrize('script', ['square', 'rashi'])
def test_real_hebrew_and_rashi_recognition(script):
    truth = json.loads((ASSETS / 'demo-truth.json').read_text(encoding='utf-8'))[script]
    candidates = recognize(Image.open(ASSETS / f'demo-{script}.png'), Options(script=script, layout='block'), threading.Event())
    actual = candidates[0].text
    # Compare character edits, ignoring typographic quote differences and spacing.
    def comparable(text):
        return ''.join(c for c in text if '\u05d0' <= c <= '\u05ea')
    expected, got = comparable(truth), comparable(actual)
    row = list(range(len(got) + 1))
    for i, a in enumerate(expected, 1):
        new = [i]
        for j, b in enumerate(got, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j-1] + (a != b)))
        row = new
    accuracy = 1 - row[-1] / max(1, len(expected))
    print(json.dumps({'script': script, 'character_accuracy_on_demo': accuracy, 'actual': actual, 'confidence': candidates[0].confidence}, ensure_ascii=True))
    assert len(candidates) == 1
    assert accuracy >= .9, f'{script}: {accuracy:.1%}: {actual}'
