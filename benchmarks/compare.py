"""Offline, fixed-baseline OCR comparison. Never changes the corpus."""
from pathlib import Path
import argparse
import json
import re
import subprocess
import sys
import threading
import time
import types
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from statistics import mean, median
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'aleph'))
import core

BASELINE = 'aacd56032ec90b38c8564f79d542ec10e59cc4e3'
TARGETS = {'paragraph': .01, 'column': .015, 'page': .02, 'notes': .04}


def distance(left, right):
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        new = [i]
        for j, b in enumerate(right, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = new
    return row[-1]


def normalize(text, marks=True):
    value = unicodedata.normalize('NFC', text)
    if not marks:
        value = core.without_nikud(value)
    return re.sub(r'\s+', ' ', value).strip()


def metrics(expected, actual, anchors=()):
    def cer(marks):
        left, right = normalize(expected, marks), normalize(actual, marks)
        if not left:
            raise ValueError('Ground truth must not be empty')
        return distance(left, right) / len(left)
    positions = [normalize(actual).find(normalize(anchor)) for anchor in anchors]
    order = (all(p >= 0 for p in positions) and all(a < b for a, b in zip(positions, positions[1:]))) if len(anchors) >= 2 else None
    cer_without_nikud = cer(False)
    return {'cer': cer(True), 'cer_without_nikud': cer_without_nikud,
            'accuracy_without_nikud': 1 - cer_without_nikud, 'reading_order': order}


def error_analysis(expected, actual, anchors=()):
    """Classify measured edits without guessing linguistic corrections."""
    left, right = normalize(expected), normalize(actual)
    edits = Counter(substitution=0, omission=0, insertion=0, incorrect_space=0)
    features = Counter(punctuation=0, gershayim=0, geresh=0, nikud=0)
    letter_pairs = Counter()

    def feature(char):
        if char == '״':
            features['gershayim'] += 1
        elif char == '׳':
            features['geresh'] += 1
        elif unicodedata.combining(char):
            features['nikud'] += 1
        elif unicodedata.category(char).startswith('P'):
            features['punctuation'] += 1

    def removed(char):
        if char.isspace():
            edits['incorrect_space'] += 1
        else:
            edits['omission'] += 1
            feature(char)

    def added(char):
        if char.isspace():
            edits['incorrect_space'] += 1
        else:
            edits['insertion'] += 1
            feature(char)

    for tag, i, j, k, m in SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if tag == 'delete':
            for char in left[i:j]:
                removed(char)
        elif tag == 'insert':
            for char in right[k:m]:
                added(char)
        elif tag == 'replace':
            source, output = left[i:j], right[k:m]
            common = min(len(source), len(output))
            for before, after in zip(source[:common], output[:common]):
                if before.isspace() or after.isspace():
                    edits['incorrect_space'] += 1
                else:
                    edits['substitution'] += 1
                    feature(before)
                    feature(after)
                    if '\u05d0' <= before <= '\u05ea' and '\u05d0' <= after <= '\u05ea':
                        letter_pairs[f'{before}/{after}'] += 1
            for char in source[common:]:
                removed(char)
            for char in output[common:]:
                added(char)

    expected_lines = [normalize(line) for line in expected.splitlines() if normalize(line)]
    actual_lines = [normalize(line) for line in actual.splitlines() if normalize(line)]
    expected_words, actual_words = left.split(), right.split()
    actual_set = set(actual_words)
    reversed_words = sum(1 for word in set(expected_words) if len(word) > 2 and word not in actual_set and word[::-1] in actual_set)
    positions = [right.find(normalize(anchor)) for anchor in anchors]
    block_order_errors = int(len(anchors) >= 2 and not (all(p >= 0 for p in positions) and all(a < b for a, b in zip(positions, positions[1:]))))
    return {
        **dict(edits),
        'merged_line_candidates': max(0, len(expected_lines) - len(actual_lines)),
        'split_line_candidates': max(0, len(actual_lines) - len(expected_lines)),
        'reversed_words': reversed_words,
        'block_order_errors': block_order_errors,
        **dict(features),
        'letter_substitution_pairs': dict(letter_pairs.most_common()),
        'expected_lines': len(expected_lines),
        'actual_lines': len(actual_lines),
    }


def confidence_bucket(value):
    if value >= 95:
        return '95-100'
    if value >= 90:
        return '90-95'
    if value >= 80:
        return '80-90'
    return '<80'


def baseline_engine():
    source = subprocess.check_output(['git', 'show', f'{BASELINE}:aleph/core.py'], cwd=ROOT).decode('utf-8')
    module = types.ModuleType('aleph_baseline')
    module.__file__ = str(ROOT / 'aleph/core.py')
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def synthetic():
    truth = json.loads((ROOT / 'corpus-v02/truth.json').read_text(encoding='utf-8'))
    demo = json.loads((core.ASSETS / 'demo-truth.json').read_text(encoding='utf-8'))
    cases = []
    for script in ('square', 'rashi'):
        expected = demo[script] if isinstance(demo[script], str) else '\n'.join(demo[script])
        cases.append({'name': script, 'image': core.ASSETS / f'demo-{script}.png', 'expected': expected, 'script': script})
    for name in ('mixed', 'nikud', 'low_contrast', 'skew', 'columns'):
        cases.append({'name': name, 'image': ROOT / f'corpus-v02/{name}.png', 'expected': '\n'.join(truth[name]),
                      'script': 'auto' if name in ('mixed', 'low_contrast') else 'square',
                      'layout': 'columns' if name == 'columns' else 'block',
                      'languages': ('heb', 'heb_rashi', 'eng', 'fra') if name == 'mixed' else ('heb', 'heb_rashi')})
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--real', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--max-regression', type=float, default=.02)
    args = parser.parse_args()
    old = baseline_engine()
    cases = synthetic()
    if args.real:
        cases = json.loads(args.real.read_text(encoding='utf-8'))['cases']
        for case in cases:
            case['expected'] = (args.real.parent / case['truth']).read_text(encoding='utf-8-sig')
            case['document'] = args.real.parent / case['document']
    rows = []
    for case in cases:
        if 'document' in case:
            image = core.Document(str(case['document'])).render(case.get('page', 1) - 1, 360, case.get('box'))
        else:
            image = Image.open(case['image']).convert('RGB')
        row = {'name': case['name'], 'kind': case.get('kind', 'synthetic'),
               'book': case.get('book', Path(case.get('document', 'synthetic')).stem),
               'truth_verified': case.get('truth_verified', not args.real)}
        for name, engine in [('before', old), ('after', core)]:
            options = dict(script=case.get('script', 'auto'), layout=case.get('layout', 'block'))
            languages = tuple(case.get('languages', ('heb', 'heb_rashi')))
            if 'languages' in engine.Options.__dataclass_fields__:
                options['languages'] = languages
            else:
                options['english'] = bool(set(languages) & {'eng', 'fra'})
            started = time.perf_counter()
            candidate = engine.recognize(image, engine.Options(**options), threading.Event())[0]
            row[name] = {**metrics(case['expected'], candidate.text, case.get('anchors', ())),
                         'errors': error_analysis(case['expected'], candidate.text, case.get('anchors', ())),
                         'seconds': time.perf_counter() - started,
                         'block_count': len(getattr(candidate, 'blocks', ())) or 1,
                         'engine_confidence': candidate.confidence,
                         'models': [block.model for block in getattr(candidate, 'blocks', ())],
                         'detected_scripts': [block.detected_script for block in getattr(candidate, 'blocks', ())],
                         'script_confidences': [block.script_confidence for block in getattr(candidate, 'blocks', ())],
                         'segmentation_score': getattr(candidate, 'segmentation_score', 1),
                         'segmentation_issues': getattr(candidate, 'segmentation_issues', []),
                         'text': candidate.text}
        row['cer_regression'] = row['after']['cer'] - row['before']['cer']
        target = TARGETS.get(row['kind'])
        row['target_cer_without_nikud'] = target
        row['target_passed'] = target is None or row['after']['cer_without_nikud'] <= target
        rows.append(row)
        print(f"{case['name']}: CER {row['before']['cer']:.3f} -> {row['after']['cer']:.3f}", flush=True)
    accuracy_gate = all(r['cer_regression'] <= args.max_regression and not (r['before']['reading_order'] is True and r['after']['reading_order'] is False) for r in rows)
    books = {}
    for book in sorted({row['book'] for row in rows}):
        values = [row['after']['cer_without_nikud'] for row in rows if row['book'] == book]
        books[book] = {'cases': len(values), 'mean_cer_without_nikud': mean(values),
                       'median_cer_without_nikud': median(values)}
    calibration = {}
    for bucket in ('95-100', '90-95', '80-90', '<80'):
        values = [row['after']['cer_without_nikud'] for row in rows
                  if confidence_bucket(row['after']['engine_confidence']) == bucket]
        calibration[bucket] = {'samples': len(values), 'mean_error_rate': mean(values) if values else None}
    report = {'baseline_commit': BASELINE, 'real': bool(args.real), 'targets': TARGETS,
              'cases': rows, 'books': books, 'confidence_calibration': calibration,
              'all_truth_verified': all(r['truth_verified'] for r in rows),
              'accuracy_gate_passed': accuracy_gate,
              'gate_passed': accuracy_gate and all(r['truth_verified'] for r in rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['gate_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
