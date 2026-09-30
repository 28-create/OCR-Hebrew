"""Compare the existing raw path and v0.4 faithful path on the same real crop."""
from pathlib import Path
import argparse
import json
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'aleph'))
from PIL import Image
from core import Document, Options, recognize
from compare import metrics


def run_case(image, expected, script):
    options = dict(script=script, layout='block', dpi=360, deskew=False,
                   typography='none', enhanced=False)
    readings = {}
    for name, pipeline in [('v03_raw', 'experimental'), ('v04_faithful', 'faithful')]:
        started = time.perf_counter()
        candidate = recognize(image, Options(**options, pipeline=pipeline), threading.Event())[0]
        readings[name] = {**metrics(expected, candidate.text), 'text': candidate.text,
                          'model': candidate.model or (candidate.blocks[0].model if candidate.blocks else ''),
                          'seconds': round(time.perf_counter() - started, 3)}
    readings['cer_delta'] = readings['v04_faithful']['cer'] - readings['v03_raw']['cer']
    return readings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'benchmarks/reports/v04-faithful.json')
    args = parser.parse_args()
    local = ROOT / 'benchmarks/local'
    cases = json.loads((local / 'cases.json').read_text(encoding='utf-8'))['cases']
    report = {'comparison': 'previous raw engine vs v0.4 faithful output', 'cases': []}
    for case in cases:
        document = Document(str(local / case['document']))
        image = document.render(case['page'] - 1, 360, case.get('box'))
        expected = (local / case['truth']).read_text(encoding='utf-8-sig')
        row = {'name': case['name'], 'kind': case['kind'],
               'truth_verified': case.get('truth_verified', False),
               'source_size': image.size,
               **run_case(image, expected, 'rashi' if case.get('script') == 'rashi' else 'square')}
        report['cases'].append(row)
        print(f"{row['name']}: CER {row['v03_raw']['cer']:.3f} -> {row['v04_faithful']['cer']:.3f}", flush=True)
    truth = json.loads((ROOT / 'aleph/assets/demo-truth.json').read_text(encoding='utf-8'))
    fixtures = [('square-paragraph', ROOT / 'aleph/assets/demo-square.png', truth['square'], 'square'),
                ('rashi-paragraph', ROOT / 'aleph/assets/demo-rashi.png', truth['rashi'], 'rashi'),
                ('nikud-paragraph', ROOT / 'corpus-v02/nikud.png',
                 '\n'.join(json.loads((ROOT / 'corpus-v02/truth.json').read_text(encoding='utf-8'))['nikud']), 'square')]
    for name, path, expected, script in fixtures:
        with Image.open(path) as original:
            image = original.convert('RGB')
        report['cases'].append({'name': name, 'kind': 'synthetic', 'truth_verified': False,
                                'source_size': image.size, **run_case(image, expected, script)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Report: {args.output}', flush=True)


if __name__ == '__main__':
    main()
