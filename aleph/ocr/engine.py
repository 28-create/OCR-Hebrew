"""Block OCR, adaptive candidates, explicit source geometry and raw reuse."""
from dataclasses import replace
from collections import Counter
from difflib import SequenceMatcher
import math
import re
from .segmentation import segment, assess_segmentation
from .script_classifier import classify_script


def models(options):
    allowed = set(options.languages)
    if not allowed or not allowed <= {'heb', 'heb_rashi', 'eng', 'fra'}:
        raise ValueError('Select at least one supported OCR language.')
    latin = [x for x in ('eng', 'fra') if x in allowed]
    preferred = {'square': ['heb'], 'rashi': ['heb_rashi'], 'auto': ['heb', 'heb_rashi'], 'mixed': ['heb', 'heb_rashi']}[options.script]
    hebrew = [x for x in preferred if x in allowed]
    if not hebrew:
        hebrew = [x for x in ('heb', 'heb_rashi') if x in allowed]
    choices = ['+'.join([h] + latin) for h in hebrew] if hebrew else ['+'.join(latin)]
    if options.script in {'auto', 'mixed'} and {'heb', 'heb_rashi'} <= allowed:
        choices.append('+'.join(['heb', 'heb_rashi'] + latin))
    return choices


def restore_boxes(candidate, original_size, prepared_size, angle, region, page_size):
    """Invert deskew, expansion and border before mapping the crop to page space."""
    pw, ph = prepared_size
    ow, oh = original_size
    cw, ch = pw - 48, ph - 48
    cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    x0, y0, _, _ = region
    width, height = page_size
    output = []
    for word, x, y, w, h, confidence in candidate.boxes:
        points = []
        for px, py in ((x, y), (x+w, y), (x, y+h), (x+w, y+h)):
            dx, dy = px * pw - 24 - cw / 2, py * ph - 24 - ch / 2
            points.append((min(ow, max(0, cos * dx - sin * dy + ow / 2)) + x0,
                           min(oh, max(0, sin * dx + cos * dy + oh / 2)) + y0))
        lx, rx = min(p[0] for p in points), max(p[0] for p in points)
        ty, by = min(p[1] for p in points), max(p[1] for p in points)
        output.append((word, lx / width, ty / height, (rx-lx) / width, (by-ty) / height, confidence))
    candidate.boxes = output


def combined(blocks, label):
    from core import Candidate
    included = [b for b in blocks if b.included]
    words = sum(b.candidates[b.selected].words for b in included)
    result = Candidate('\n\n'.join(b.candidates[b.selected].text for b in included if b.candidates[b.selected].text),
        sum(b.candidates[b.selected].confidence * b.candidates[b.selected].words for b in included) / max(1, words),
        list(dict.fromkeys(w for b in included for w in b.candidates[b.selected].uncertain)), label, words,
        [box for b in included for box in b.candidates[b.selected].boxes], blocks=blocks,
        decisions=[decision for b in included for decision in b.candidates[b.selected].decisions])
    return result


def word_decisions(block, selected):
    """Expose candidate agreement per word without rewriting recognized text."""
    from core import WordDecision
    chosen = block.candidates[selected]
    words = chosen.text.split()
    alternatives = [Counter({word: 1}) for word in words]
    for peer in block.candidates:
        if peer is chosen:
            continue
        peer_words = peer.text.split()
        for tag, i, j, k, m in SequenceMatcher(None, words, peer_words, autojunk=False).get_opcodes():
            if tag == 'equal':
                for offset, word in enumerate(peer_words[k:m]):
                    alternatives[i + offset][word] += 1
            elif tag == 'replace':
                for offset, word in enumerate(peer_words[k:m][:j-i]):
                    alternatives[i + offset][word] += 1
    decisions = []
    denominator = max(1, len(block.candidates))
    for index, word in enumerate(words):
        choices = alternatives[index]
        strength = choices[word] / denominator
        box = chosen.boxes[index] if index < len(chosen.boxes) else None
        confidence = box[5] if box else chosen.confidence
        bbox = tuple(box[1:5]) if box else None
        decisions.append(WordDecision(
            word, [text for text, _ in choices.most_common() if text != word],
            confidence, strength, block.order, bbox,
            strength < .67 or word in chosen.uncertain,
        ))
    return decisions


def score(candidate, peers, script='auto'):
    # Confidence dominates. Stability and character plausibility are supporting
    # signals, not a dictionary or a claim to understand Hebrew semantics.
    stable = max((SequenceMatcher(None, candidate.text, p.text).ratio() for p in peers if p is not candidate), default=1)
    plausible = sum(c.isalnum() or c.isspace() or '\u0590' <= c <= '\u05ff' for c in candidate.text) / max(1, len(candidate.text))
    return candidate.confidence + 1.2 * stable + plausible


def recognize_blocks(image, options, cancel, progress, raw=None, draft_callback=None):
    from core import Candidate, BlockResult, Cancelled, preprocess, run_tesseract, hebrew_typography, repair_mixed_rtl
    choices = models(options)
    if cancel.is_set():
        raise Cancelled()
    regions = segment(image, options.layout)
    segmentation_quality = assess_segmentation(image, regions)
    blocks = []
    # Reuse only a raw result produced for this exact image/options by the worker.
    reuse = {b.box: b for b in raw.blocks} if raw else {}
    for region in regions:
        if cancel.is_set():
            raise Cancelled()
        progress(f'OCR {region.order + 1}/{len(regions)}')
        crop = image.crop(region.box)
        classification = classify_script(crop) if options.script in {'auto', 'mixed'} else None
        psm = 7 if options.layout == 'line' else 6

        def read(model, binary=False, mode=psm):
            transform = {}
            prepared = preprocess(crop, options.deskew, binary, transform=transform)
            candidate = run_tesseract(prepared, model, mode, cancel, 'Local contrast' if binary else 'Grayscale')
            candidate.model = model
            restore_boxes(candidate, crop.size, prepared.size, transform.get('angle', 0), region.box, image.size)
            if options.typography == 'auto':
                candidate.text = hebrew_typography(candidate.text)
                if {'eng', 'fra'} & set(options.languages):
                    candidate.text = repair_mixed_rtl(candidate.text)
            return candidate

        first = reuse[region.box].candidates[0] if region.box in reuse else read(choices[0])
        block = BlockResult(region.box, region.order, region.kind, crop, [first], model=first.model,
                            detected_script=classification.label if classification else options.script,
                            script_confidence=classification.confidence if classification else 1)
        blocks.append(block)
    raw_blocks = [replace(b, candidates=list(b.candidates)) for b in blocks]
    raw_result = combined(raw_blocks, 'OCR brut')
    raw_result.segmentation_score = segmentation_quality.score
    raw_result.segmentation_issues = list(segmentation_quality.issues)
    if draft_callback:
        draft_callback(raw_result)
    if not options.enhanced:
        return [raw_result]
    for block in blocks:
        if cancel.is_set():
            raise Cancelled()
        # Easy blocks require no second engine call. Uncertain blocks compare
        # square/Rashi independently and then local contrast/alternative PSM.
        first = block.candidates[0]
        if first.confidence < 94 or not first.text:
            crop = block.image
            region = next(r for r in regions if r.box == block.box)
            for model in choices[1:]:
                block.candidates.append(read(model))
            preferred = max(block.candidates, key=lambda c: score(c, block.candidates, options.script))
            block.candidates.append(read(preferred.model, True))
            if max(c.confidence for c in block.candidates) < 75:
                block.candidates.append(read(preferred.model, False, 3))
        block.selected = max(range(len(block.candidates)), key=lambda i: (bool(block.candidates[i].text), score(block.candidates[i], block.candidates, options.script)))
        best = block.candidates[block.selected]
        uncertain = list(best.uncertain)
        for other in block.candidates:
            if other is best or abs(best.confidence - other.confidence) > 15:
                continue
            words, peer = best.text.split(), other.text.split()
            for tag, i, j, _, _ in SequenceMatcher(None, words, peer).get_opcodes():
                if tag != 'equal':
                    uncertain.extend(words[i:j])
        # Do not mutate the raw candidate: it remains independently selectable.
        best = replace(best, uncertain=list(dict.fromkeys(uncertain)))
        block.candidates[block.selected] = best
        best.decisions = word_decisions(block, block.selected)
        block.model, block.score = best.model, score(best, block.candidates, options.script)
    smart = combined(blocks, 'Smart OCR')
    smart.segmentation_score = segmentation_quality.score
    smart.segmentation_issues = list(segmentation_quality.issues)
    return [smart, raw_result]
