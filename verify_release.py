"""Exercise the final bundled executable outside the source directory."""
from pathlib import Path
import json
import os
import subprocess
from PIL import Image

root = Path(__file__).resolve().parent
output = root.parent / 'outputs'
exe = root / 'release-stage' / 'onedir' / 'AlephOCR' / 'AlephOCR.exe'
installer = output / 'AlephOCR-Setup.exe'
assert exe.is_file() and installer.is_file(), 'Build the installer first'
isolated = root / 'isolated-test'
isolated.mkdir(exist_ok=True)
environment = os.environ.copy()
environment['QT_QPA_PLATFORM'] = 'offscreen'
environment['PATH'] = os.environ.get('WINDIR', 'C:/Windows') + '/System32'
environment.pop('PYTHONPATH', None)
environment.pop('TESSDATA_PREFIX', None)
pdf = isolated / 'two-pages.pdf'
Image.open(root / 'aleph/assets/demo-square.png').convert('RGB').save(
    pdf, save_all=True, append_images=[Image.open(root / 'aleph/assets/demo-rashi.png').convert('RGB')], resolution=150)
report_path = root / 'executable-self-test.json'
process = subprocess.run([str(exe), str(pdf), '--self-test-report', str(report_path)], cwd=isolated, env=environment,
                         timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
print('Executable OCR exit:', process.returncode, flush=True)
assert process.returncode == 0
report = json.loads(report_path.read_text(encoding='utf-8'))
assert report['ok'] and report['pdf']['pages'] == 2
assert 'ברוכים הבאים' in report['checks'][0]['text']
assert 'נכתב' in report['checks'][1]['text']
assert report['pdf']['size'][0] > 1000
print(json.dumps(report, ensure_ascii=True), flush=True)
screenshot = root / 'executable-preview.png'
process = subprocess.run([str(exe), '--quick-smoke-test', '--screenshot', str(screenshot)], cwd=isolated, env=environment,
                         timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
print('Executable UI exit:', process.returncode, flush=True)
assert process.returncode == 0 and screenshot.stat().st_size > 10000
print('Executable and user interface verified.', flush=True)
print(f'Installer ready: {installer.name} ({installer.stat().st_size:,} bytes)', flush=True)
