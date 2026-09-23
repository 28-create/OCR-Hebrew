"""Conservative whitespace layout analysis; coordinates refer to the input image.

This is not a trained layout classifier. Ambiguous elements are preserved.
No fixed centre split, no unconditional top/bottom cropping.
"""
from dataclasses import dataclass
import numpy as np
from PIL import ImageOps


@dataclass(frozen=True)
class Region:
    box: tuple[int, int, int, int]
    order: int
    kind: str = 'body'


@dataclass(frozen=True)
class SegmentationQuality:
    score: float
    issues: tuple[str, ...]
    number_of_columns: int


def assess_segmentation(image, regions):
    issues, penalty = [], 0.0
    if not regions:
        return SegmentationQuality(0, ('no_text_blocks',), 0)
    area = max(1, image.width * image.height)
    body = [region for region in regions if region.kind not in {'header_candidate', 'footer_candidate', 'notes'}]
    for region in body:
        x0, y0, x1, y1 = region.box
        ratio = (x1-x0) * (y1-y0) / area
        if x1-x0 < image.width * .08:
            issues.append('very_narrow_block'); penalty += .12
        if y1-y0 > image.height * .78 and ratio > .35:
            issues.append('very_tall_block'); penalty += .16
    for index, left in enumerate(regions):
        for right in regions[index+1:]:
            x0, y0 = max(left.box[0], right.box[0]), max(left.box[1], right.box[1])
            x1, y1 = min(left.box[2], right.box[2]), min(left.box[3], right.box[3])
            if x1 > x0 and y1 > y0:
                overlap = (x1-x0) * (y1-y0) / max(1, min((left.box[2]-left.box[0])*(left.box[3]-left.box[1]), (right.box[2]-right.box[0])*(right.box[3]-right.box[1])))
                if overlap > .12:
                    issues.append('overlapping_blocks'); penalty += .18
    centers = sorted((region.box[0] + region.box[2]) / 2 for region in body)
    columns = 0
    last = None
    for center in centers:
        if last is None or center-last > image.width * .18:
            columns += 1
            last = center
    if len(body) == 1 and image.height > image.width * 1.15 and body[0].box[2]-body[0].box[0] > image.width * .7:
        issues.append('possible_unsplit_page'); penalty += .22
    return SegmentationQuality(max(0, 1-penalty), tuple(dict.fromkeys(issues)), columns)


def runs(mask):
    edges = np.diff(np.pad(np.asarray(mask, dtype=np.int8), (1, 1)))
    return list(zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist()))


def segment(image, layout='auto'):
    if layout == 'line':
        return [Region((0, 0, *image.size), 0)]
    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    gray.thumbnail((1600, 2200))
    array = np.asarray(gray)
    ink = array < min(185, float(np.percentile(array, 80)) * .8)
    h, w = ink.shape
    ys, xs = np.where(ink)
    if not len(xs):
        return []
    occupied = runs(ink.sum(axis=1) > max(1, w * .002))
    line_height = max(3, float(np.median([b - a for a, b in occupied])))
    found = []

    def visit(x0, y0, x1, y1, depth=0):
        area = ink[y0:y1, x0:x1]
        yy, xx = np.where(area)
        if not len(xx):
            return
        x0, y0, x1, y1 = x0 + int(xx.min()), y0 + int(yy.min()), x0 + int(xx.max()) + 1, y0 + int(yy.max()) + 1
        area = ink[y0:y1, x0:x1]
        if depth >= 12:
            found.append((x0, y0, x1, y1))
            return
        width, height = x1 - x0, y1 - y0
        # A spanning title/header can bridge an otherwise persistent gutter.
        # Isolate that edge band first, leaving the entire body intact for RTL
        # column traversal (not right paragraph, left paragraph interleaving).
        if height > line_height * 8:
            for a, b in runs(area.sum(axis=0) <= line_height * 1.5):
                if b - a < max(line_height, width * .03) or a < width * .16 or b > width * .84:
                    continue
                bridges = np.flatnonzero(area[:, a:b].any(axis=1))
                if not len(bridges):
                    continue
                if bridges[-1] < height * .18:
                    after = np.flatnonzero(~area.any(axis=1) & (np.arange(height) > bridges[-1]))
                    if len(after):
                        cut = int(after[0])
                        visit(x0, y0, x1, y0 + cut, depth + 1)
                        visit(x0, y0 + cut, x1, y1, depth + 1)
                        return
                elif bridges[0] > height * .82:
                    before = np.flatnonzero(~area.any(axis=1) & (np.arange(height) < bridges[0]))
                    if len(before):
                        cut = int(before[-1])
                        visit(x0, y0, x1, y0 + cut, depth + 1)
                        visit(x0, y0 + cut, x1, y1, depth + 1)
                        return
        # Persistent gutters, not single inter-word spaces. Demand enough ink and
        # vertical extent on both sides before splitting into RTL columns.
        gutters = []
        if height >= 2 * line_height:
            for a, b in runs(area.sum(axis=0) <= max(0, height * .001)):
                if b - a < max(line_height * .9, width * .025) or a < width * .16 or b > width * .84:
                    continue
                left, right = area[:, :a], area[:, b:]
                rows_l, rows_r = left.any(axis=1), right.any(axis=1)
                overlap = np.count_nonzero(rows_l & rows_r) / max(1, min(np.count_nonzero(rows_l), np.count_nonzero(rows_r)))
                if overlap >= .55 and left.sum() > 30 and right.sum() > 30:
                    gutters.append((b - a, a, b))
        if gutters:
            _, a, b = max(gutters)
            visit(x0 + b, y0, x1, y1, depth + 1)
            visit(x0, y0, x0 + a, y1, depth + 1)
            return
        lines = runs(area.sum(axis=1) > max(1, width * .002))
        gaps = [(lines[i][1], lines[i + 1][0]) for i in range(len(lines) - 1)]
        typical_gap = float(np.median([b - a for a, b in gaps])) if gaps else 0
        # Printed Hebrew often has tall joined glyph bands: using almost one
        # glyph-height here hid genuine paragraph whitespace. A paragraph gap
        # must instead exceed the ordinary line gap, with a small noise floor.
        threshold = max(line_height * .35, typical_gap * 1.8)
        # A short user-selected passage should stay intact unless it contains a
        # truly large separator; small glyph/descender variations are not blocks.
        if len(lines) <= 8:
            threshold = max(threshold, line_height * 1.5)
        divisions = [(a, b) for a, b in gaps if b - a > threshold]
        if divisions:
            last = 0
            for a, b in divisions:
                visit(x0, y0 + last, x1, y0 + a, depth + 1)
                last = b
            visit(x0, y0 + last, x1, y1, depth + 1)
        else:
            found.append((x0, y0, x1, y1))

    visit(0, 0, w, h)
    if len(found) == 1:
        # Keep the original framing of small passages: avoids changing a proven
        # paragraph input simply because segmentation is enabled.
        return [Region((0, 0, *image.size), 0)]
    sx, sy = image.width / w, image.height / h
    regions = []
    for order, (x0, y0, x1, y1) in enumerate(found):
        local = ink[y0:y1, x0:x1]
        rows = runs(local.any(axis=1))
        size = np.median([b - a for a, b in rows]) if rows else line_height
        kind = 'notes' if y0 > h * .65 and size < line_height * .8 else 'body'
        if (y1 < h * .14 or y0 > h * .88) and y1 - y0 < h * .10:
            kind = 'header_candidate' if y1 < h * .14 else 'footer_candidate'
        elif len(rows) == 1 and size > line_height * 1.3:
            kind = 'heading'
        pad = max(3, int(line_height * .20))
        box = (max(0, int((x0 - pad) * sx)), max(0, int((y0 - pad) * sy)),
               min(image.width, int((x1 + pad) * sx)), min(image.height, int((y1 + pad) * sy)))
        regions.append(Region(box, order, kind))
    # Reading order is body, scholarly notes, then pagination/scanner metadata.
    # Preserve RTL discovery order inside each group.
    def reading_group(region):
        if region.kind == 'notes':
            return 1
        if region.kind == 'footer_candidate':
            return 2
        return 0
    regions.sort(key=lambda r: (reading_group(r), r.order))
    return [Region(r.box, i, r.kind) for i, r in enumerate(regions)]
