"""Exercise the final bundled executable outside the source directory."""
from pathlib import Path
import json
import os
import subprocess

root = Path(__file__).resolve().parent
output = root.parent / 'outputs'
exe = output / 'AlephOCR.exe'
isolated = root / 'isolated-test'
isolated.mkdir(exist_ok=True)
environment = os.environ.copy()
environment['QT_QPA_PLATFORM'] = 'offscreen'
environment['PATH'] = os.environ.get('WINDIR', 'C:/Windows') + '/System32'
environment.pop('PYTHONPATH', None)
environment.pop('TESSDATA_PREFIX', None)
pdf = next((root / 'tests-sep15-c').rglob('test-hebrew.pdf'))
report_path = root / 'executable-self-test.json'
process = subprocess.run([str(exe), str(pdf), '--self-test-report', str(report_path)], cwd=isolated, env=environment,
                         timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
print('Executable OCR exit:', process.returncode, flush=True)
assert process.returncode == 0
report = json.loads(report_path.read_text(encoding='utf-8'))
assert report['ok'] and report['pdf']['pages'] == 2
assert 'ברוכים הבאים' in report['checks'][0]['text']
assert 'נכתב' in report['checks'][1]['text']
assert 'שלום' in report['pdf']['text']
print(json.dumps(report, ensure_ascii=True), flush=True)
screenshot = root / 'executable-preview.png'
process = subprocess.run([str(exe), '--quick-smoke-test', '--screenshot', str(screenshot)], cwd=isolated, env=environment,
                         timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
print('Executable UI exit:', process.returncode, flush=True)
assert process.returncode == 0 and screenshot.stat().st_size > 10000
print('Executable and user interface verified.', flush=True)
