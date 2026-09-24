"""Measure the closest visible gap from each side stroke to the Aleph's main stroke."""

from collections import deque
from pathlib import Path
import sys

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parent / 'logo-proposals'


def components(mask):
    height, width = mask.shape
    seen = np.zeros_like(mask)
    found = []
    for y, x in zip(*np.where(mask)):
        if seen[y, x]:
            continue
        queue = deque([(int(y), int(x))])
        seen[y, x] = True
        points = []
        while queue:
            row, col = queue.popleft()
            points.append((row, col))
            for nr, nc in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
                if 0 <= nr < height and 0 <= nc < width and mask[nr, nc] and not seen[nr, nc]:
                    seen[nr, nc] = True
                    queue.append((nr, nc))
        if len(points) > 5:
            found.append(np.array(points, dtype=np.int16))
    return found


def border(points, shape):
    region = np.zeros(shape, dtype=bool)
    region[points[:, 0], points[:, 1]] = True
    inner = region.copy()
    inner[1:] &= region[:-1]
    inner[:-1] &= region[1:]
    inner[:, 1:] &= region[:, :-1]
    inner[:, :-1] &= region[:, 1:]
    return np.argwhere(region & ~inner)


def closest(first, second):
    minimum = float('inf')
    for start in range(0, len(first), 128):
        delta = first[start:start + 128, None, :].astype(np.int32) - second[None, :, :].astype(np.int32)
        minimum = min(minimum, int(np.min(np.sum(delta * delta, axis=2))))
    return minimum ** 0.5


def measure(path):
    pixels = np.array(Image.open(path).convert('RGB'))
    mask = (pixels[:, :, 0] > 230) & (pixels[:, :, 1] > 225) & (pixels[:, :, 2] > 210)
    parts = sorted(components(mask), key=len, reverse=True)[:3]
    if len(parts) != 3:
        raise ValueError(f'Expected exactly three white strokes in {path}, found {len(parts)}')
    center = parts[0]
    sides = sorted(parts[1:], key=lambda part: part[:, 1].mean())
    center_edge = border(center, mask.shape)
    return [closest(border(part, mask.shape), center_edge) for part in sides]


if __name__ == '__main__':
    for letter in sys.argv[1:] or 'ABCD':
        left, right = measure(ROOT / f'{letter}-512.png')
        print(f'{letter}: left {left / 4:.2f}, right {right / 4:.2f} SVG units')
