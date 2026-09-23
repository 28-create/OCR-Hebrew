"""Lightweight offline visual script classifier; never uses OCR confidence."""
from dataclasses import dataclass
from functools import lru_cache
import numpy as np
from PIL import Image, ImageOps


@dataclass(frozen=True)
class ScriptClassification:
    label: str
    confidence: float
    features: tuple[float, ...]
    distances: dict[str, float]


def _run_lengths(mask, axis):
    values = []
    lines = mask if axis == 1 else mask.T
    for line in lines:
        edges = np.diff(np.pad(line.astype(np.int8), (1, 1)))
        starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
        values.extend((ends - starts).tolist())
    return np.asarray(values or [0], dtype=float)


def visual_features(image):
    gray = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=.3)
    gray.thumbnail((800, 500))
    array = np.asarray(gray, dtype=float)
    ink = array < min(190, float(np.percentile(array, 70)) * .82)
    yy, xx = np.where(ink)
    if len(xx) < 20:
        return (0.0,) * 9
    ink = ink[yy.min():yy.max()+1, xx.min():xx.max()+1]
    count = max(1, int(ink.sum()))
    horizontal = np.count_nonzero(ink[:, 1:] & ink[:, :-1]) / count
    vertical = np.count_nonzero(ink[1:] & ink[:-1]) / count
    h_runs, v_runs = _run_lengths(ink, 1), _run_lengths(ink, 0)
    gx = np.abs(np.diff(array, axis=1)).mean()
    gy = np.abs(np.diff(array, axis=0)).mean()
    return (float(ink.mean()), horizontal, vertical, horizontal / max(vertical, 1e-6),
            float(np.median(h_runs)), float(np.quantile(h_runs, .8)),
            float(np.median(v_runs)), float(np.quantile(v_runs, .8)),
            float(gx / max(gy, 1e-6)))


def _distance(left, right):
    return float(np.mean([abs(a-b) / max(abs(a), abs(b), .05) for a, b in zip(left, right)]))


@lru_cache(maxsize=1)
def _references():
    from core import ASSETS
    with Image.open(ASSETS / 'demo-square.png') as square:
        square_features = visual_features(square.convert('RGB'))
    with Image.open(ASSETS / 'demo-rashi.png') as rashi:
        rashi_features = visual_features(rashi.convert('RGB'))
    return {'square': square_features, 'rashi': rashi_features}


def classify_script(image):
    features = visual_features(image)
    references = _references()
    distances = {name: _distance(features, reference) for name, reference in references.items()}
    best, other = sorted(distances, key=distances.get)
    margin = (distances[other] - distances[best]) / max(distances[other], .001)
    # A large relative margin is meaningless when the block is far from both
    # reference families. Real old-print blocks therefore remain uncertain.
    label = best if margin >= .18 and distances[best] <= .12 else 'uncertain'
    if image.width >= 600:
        labels = []
        for index in range(3):
            part = image.crop((image.width * index // 3, 0, image.width * (index + 1) // 3, image.height))
            local = visual_features(part)
            values = {name: _distance(local, reference) for name, reference in references.items()}
            nearest, second = sorted(values, key=values.get)
            local_margin = (values[second] - values[nearest]) / max(values[second], .001)
            if local_margin >= .25 and values[nearest] <= .12:
                labels.append(nearest)
        if {'square', 'rashi'} <= set(labels):
            label = 'mixed'
    return ScriptClassification(label, max(0.0, min(1.0, margin)), features, distances)
