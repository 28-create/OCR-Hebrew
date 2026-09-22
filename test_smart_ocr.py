import sys
import threading
from pathlib import Path
from dataclasses import replace
sys.path.insert(0, str(Path(__file__).parent / 'aleph'))
from PIL import Image, ImageDraw
import pytest
import core
from ocr.engine import models, restore_boxes, combined, score
from ocr.segmentation import segment
from ocr.running_elements import filter_batch
from benchmarks.compare import metrics


def layout_image():
    image = Image.new('RGB', (1000, 1200), 'white')
    draw = ImageDraw.Draw(image)
    for left, right in ((40, 330), (450, 940)):
        for top in (160, 430):
            for y in range(top, top + 110, 35):
                draw.rectangle((left, y, right, y + 19), fill='black')
    return image


def test_unequal_columns_paragraphs_and_rtl():
    regions = segment(layout_image())
    assert len(regions) == 4
    assert regions[0].box[0] > 400 and regions[1].box[0] > 400
    assert regions[2].box[2] < 400 and regions[3].box[2] < 400
    assert regions[0].box[1] < regions[1].box[1]
    assert regions[2].box[1] < regions[3].box[1]


def test_models_separate_languages():
    assert models(core.Options()) == ['heb', 'heb_rashi', 'heb+heb_rashi']
    assert models(core.Options(languages=('heb', 'fra'))) == ['heb+fra']
    assert models(core.Options(script='rashi')) == ['heb_rashi']
    assert models(core.Options(languages=('eng',))) == ['eng']
    with pytest.raises(ValueError):
        models(core.Options(languages=()))


def test_auto_script_requires_rashi_to_win_clearly():
    square = core.Candidate('שלום עולם', 95, [], '', 2, model='heb')
    rashi = core.Candidate('שלום עולם', 96, [], '', 2, model='heb_rashi')
    assert score(square, [square, rashi], 'auto') > score(rashi, [square, rashi], 'auto')
    assert score(square, [square, rashi], 'rashi') < score(rashi, [square, rashi], 'rashi')


def test_spanning_title_does_not_interleave_columns():
    image = layout_image()
    ImageDraw.Draw(image).rectangle((100, 45, 900, 64), fill='black')
    regions = segment(image)
    assert len(regions) == 5
    assert regions[0].box[1] < 80
    assert regions[1].box[0] > 400 and regions[2].box[0] > 400
    assert regions[3].box[2] < 400 and regions[4].box[2] < 400


def test_adaptive_raw_reused_and_no_latin(monkeypatch):
    calls, drafts = [], []
    def fake(image, lang, psm, cancel, label):
        calls.append((lang, psm))
        return core.Candidate('שלום עולם', 97, [], label, 2)
    monkeypatch.setattr(core, 'run_tesseract', fake)
    result = core.recognize(layout_image(), core.Options(deskew=False), threading.Event(), draft_callback=drafts.append)
    assert len(calls) == 4
    assert all(lang == 'heb' for lang, _ in calls)
    assert len(drafts) == 1 and len(result) == 2
    assert len(result[0].blocks) == 4
    assert result[1].text == drafts[0].text


def test_uncertain_block_compares_models_and_preserves_raw(monkeypatch):
    calls = []
    def fake(image, lang, psm, cancel, label):
        calls.append(lang)
        return core.Candidate('שלום' if lang == 'heb_rashi' else 'שלים', 96 if lang == 'heb_rashi' else 60, [], label, 1)
    monkeypatch.setattr(core, 'run_tesseract', fake)
    result = core.recognize(layout_image(), core.Options(deskew=False), threading.Event())
    assert 'heb_rashi' in calls and 'heb+heb_rashi' in calls
    assert 'שלום' in result[0].text and 'שלים' in result[1].text
    assert all(b.model == 'heb_rashi' for b in result[0].blocks)


def test_word_geometry_maps_border_crop_and_scale():
    candidate = core.Candidate('שלום', 90, [], '', 1, [('שלום', 24/148, 24/98, 50/148, 20/98, 90)])
    restore_boxes(candidate, (100, 50), (148, 98), 0, (300, 200, 400, 250), (1000, 800))
    assert candidate.boxes[0][1:5] == pytest.approx((.3, .25, .05, .025))


def make_result(page):
    blocks = [core.BlockResult((10, 10, 300, 40), 0, 'header_candidate', Image.new('RGB', (1,1)), [core.Candidate('שער הכונות', 90, [], '', 2)]),
              core.BlockResult((10, 200, 300, 240), 1, 'heading', Image.new('RGB', (1,1)), [core.Candidate('פרק ראשון', 90, [], '', 2)]),
              core.BlockResult((10, 960, 60, 990), 2, 'footer_candidate', Image.new('RGB', (1,1)), [core.Candidate(str(185 + page), 90, [], '', 1)])]
    return core.Result(page, '', [combined(blocks, 'Smart'), combined([replace(b) for b in blocks], 'Raw')])


def test_repeated_headers_pagination_and_internal_titles():
    results = [make_result(i) for i in range(3)]
    filter_batch(results, core.Options())
    assert all(r.text == 'פרק ראשון' for r in results)
    assert 'שער הכונות' in results[0].candidates[1].text
    assert results[0].candidates[0].blocks[0].exclusion_reason


def test_single_page_or_include_repeated_preserves_everything():
    result = make_result(0)
    filter_batch([result], core.Options())
    assert 'שער הכונות' in result.text and '185' in result.text
    results = [make_result(i) for i in range(3)]
    filter_batch(results, core.Options(include_repeated=True))
    assert all('שער הכונות' in r.text for r in results)


def test_metrics_report_missing_order_and_real_edits():
    assert metrics('שלום עולם', 'שלום עולם')['cer'] == 0
    assert metrics('שָׁלוֹם', 'שלום')['cer_without_nikud'] == 0
    assert metrics('שָׁלוֹם', 'שלום')['accuracy_without_nikud'] == 1
    assert metrics('א ב', 'ב א', ['א', 'ב'])['reading_order'] is False
    assert metrics('א ב', 'א', ['א', 'ב'])['reading_order'] is False
    assert metrics('א ב', 'א ב', ['א', 'ב'])['reading_order'] is True
