"""Exercise the final bundled executable outside the source directory."""
from pathlib import Path
import json
import os
import subprocess
import hashlib
from PIL import Image
import pefile

root = Path(__file__).resolve().parent
output = root.parent / 'outputs'
exe = root / 'release-stage' / 'onedir' / 'AlephOCR' / 'AlephOCR.exe'
portable = output / 'AlephOCR.exe'
installer = output / 'AlephOCR-Setup.exe'
assert exe.is_file() and portable.is_file() and installer.is_file(), 'Build the release first'
icon = Image.open(root / 'aleph/assets/app.ico')
assert icon.ico.sizes() == {(size, size) for size in (16, 24, 32, 48, 64, 128, 256)}


def embedded_icons(path):
    pe = pefile.PE(str(path))
    try:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
        images = next(entry for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries if entry.id == 3)
        return {hashlib.sha256(pe.get_data(language.data.struct.OffsetToData,
                                           language.data.struct.Size)).hexdigest()
                for name in images.directory.entries for language in name.directory.entries}
    finally:
        pe.close()


icon_sets = [embedded_icons(path) for path in (exe, portable, installer)]
assert all(icons == icon_sets[0] for icons in icon_sets)
assert len(icon_sets[0]) == 7
print('Seven identical embedded icon sizes in both EXEs and the installer.', flush=True)
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
for label, executable in (('installed', exe), ('portable', portable)):
    report_path = root / f'executable-self-test-{label}.json'
    process = subprocess.run([str(executable), str(pdf), '--self-test-report', str(report_path)], cwd=isolated, env=environment,
                             timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    print(f'{label} OCR exit:', process.returncode, flush=True)
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
print('Both executables and the user interface verified.', flush=True)
print(f'Installer ready: {installer.name} ({installer.stat().st_size:,} bytes)', flush=True)
