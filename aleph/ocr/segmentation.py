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
        threshold = max(line_height * .85, typical_gap * 1.65)
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
    # Notes stay distinct and follow the text, while preserving RTL within each.
    regions.sort(key=lambda r: (r.kind == 'notes', r.order))
    return [Region(r.box, i, r.kind) for i, r in enumerate(regions)]
