"""Canonical Hebrew text is never replaced by its hidden-marks projection."""
from difflib import SequenceMatcher
import re
import unicodedata

MARKS = re.compile('[\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]')


def edit_hidden(canonical, visible):
    clusters = []
    for character in unicodedata.normalize('NFC', canonical):
        if MARKS.fullmatch(character) and clusters:
            clusters[-1] += character
        else:
            clusters.append(character)
    plain = ''.join(MARKS.sub('', cluster) for cluster in clusters)
    if len(plain) != len(clusters):
        # Isolated leading marks have no visible anchor; retain them separately.
        prefix = ''.join(c for c in clusters if not MARKS.sub('', c))
        clusters = [c for c in clusters if MARKS.sub('', c)]
    else:
        prefix = ''
    result = [prefix]
    for kind, i, j, a, b in SequenceMatcher(None, plain, visible, autojunk=False).get_opcodes():
        result.append(''.join(clusters[i:j]) if kind == 'equal' else visible[a:b])
    return ''.join(result)


def overlap(previous, following, minimum=3):
    def words(text):
        return [(MARKS.sub('', m.group()).lower(), m.end()) for m in re.finditer(r'[\w\u0590-\u05ff״׳]+', text)]
    left, right = words(previous), words(following)
    for count in range(min(18, len(left), len(right)), minimum - 1, -1):
        a, b = [w for w, _ in left[-count:]], [w for w, _ in right[:count]]
        # Require most words to be exact and allow small OCR character errors.
        exact = sum(x == y for x, y in zip(a, b))
        similarity = SequenceMatcher(None, ' '.join(a), ' '.join(b), autojunk=False).ratio()
        if exact >= count - max(1, count // 5) and similarity >= .90:
            return count, right[count - 1][1]
    return 0, 0
