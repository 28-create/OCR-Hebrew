"""Build the offline Windows executable; run with the project virtual environment."""
from pathlib import Path
import importlib.metadata
import json
import shutil
import subprocess
import sys
import zipfile
import pefile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
SOURCE = ROOT / 'aleph'
STAGE = ROOT / 'release-stage'
OUTPUT = PROJECT / 'outputs'
ASSETS = STAGE / 'assets'


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def prepare():
    OUTPUT.mkdir(exist_ok=True)
    engine = SOURCE / 'assets/tesseract'
    available = {item.name.lower(): item for item in engine.iterdir() if item.is_file()}
    pending, seen = ['tesseract.exe'], set()
    while pending:
        name = pending.pop().lower()
        if name in seen or name not in available:
            continue
        seen.add(name)
        file = available[name]
        copy(file, ASSETS / 'tesseract' / file.name)
        binary = pefile.PE(str(file), fast_load=True)
        binary.parse_data_directories(directories=[1, 13])
        pending.extend(item.dll.decode() for kind in ['DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT'] for item in getattr(binary, kind, []))
        binary.close()
    for file in (engine / 'tessdata').glob('*.traineddata'):
        copy(file, ASSETS / 'tesseract/tessdata' / file.name)
    for name in ['demo.png', 'demo-square.png', 'demo-rashi.png', 'demo-truth.json', 'logo.svg', 'logo.png', 'app.ico', 'sources.json']:
        copy(SOURCE / 'assets' / name, ASSETS / name)
    for file in (SOURCE / 'assets/licenses').rglob('*'):
        if file.is_file():
            copy(file, ASSETS / 'licenses' / file.relative_to(SOURCE / 'assets/licenses'))
    for package in ['PySide6-Essentials', 'shiboken6', 'numpy', 'pillow', 'pypdfium2']:
        distribution = importlib.metadata.distribution(package)
        for file in distribution.files or []:
            if any(word in str(file).lower() for word in ['license', 'copying', 'notice']):
                resolved = Path(distribution.locate_file(file))
                if resolved.is_file():
                    copy(resolved, ASSETS / 'licenses' / package / Path(str(file)))
    print(f'Prepared {len(seen)} engine binaries.', flush=True)


def build():
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--distpath', str(OUTPUT), '--workpath', str(ROOT / 'pyinstaller-build-v03'),
               str(ROOT / 'AlephOCR.spec')]
    subprocess.run(command, check=True)
    copy(ASSETS / 'logo.png', OUTPUT / 'AlephOCR-logo.png')
    copy(ASSETS / 'logo.svg', OUTPUT / 'AlephOCR-logo.svg')
    with zipfile.ZipFile(OUTPUT / 'AlephOCR-sources.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in SOURCE.rglob('*.py'):
            archive.write(file, 'work/aleph/' + file.relative_to(SOURCE).as_posix())
        for file in ASSETS.rglob('*'):
            if file.is_file():
                archive.write(file, 'work/aleph/assets/' + file.relative_to(ASSETS).as_posix())
        for name in ['build_release.py', 'fetch_assets.py', 'verify_release.py', 'version_info.txt',
                     'test_core.py', 'test_app.py', 'test_quick.py', 'test_smart_ocr.py', 'test_session.py',
                     'conftest.py', 'pytest.ini', 'make_demo.py', 'make_benchmark_corpus.py', 'run_benchmark.py']:
            archive.write(ROOT / name, 'work/' + name)
        for file in (ROOT / 'benchmarks').rglob('*'):
            if file.is_file() and 'reports' not in file.parts and 'local' not in file.parts:
                archive.write(file, 'work/benchmarks/' + file.relative_to(ROOT / 'benchmarks').as_posix())
        for file in (ROOT / 'corpus-v02').rglob('*'):
            if file.is_file():
                archive.write(file, 'work/corpus-v02/' + file.relative_to(ROOT / 'corpus-v02').as_posix())
        archive.write(ROOT / 'requirements.txt', 'requirements.txt')
        archive.write(ROOT / 'SOURCE-README.md', 'README.md')
        archive.write(ROOT / 'LICENSE.txt', 'LICENSE.txt')
    with zipfile.ZipFile(OUTPUT / 'AlephOCR-licences.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in (ASSETS / 'licenses').rglob('*'):
            if file.is_file():
                archive.write(file, file.relative_to(ASSETS / 'licenses').as_posix())
        archive.write(ROOT / 'LICENSE.txt', 'AlephOCR-MIT.txt')
        archive.write(ROOT / 'THIRD-PARTY.txt', 'COMPOSANTS.txt')
    print('Build and source archive complete.', flush=True)


if __name__ == '__main__':
    prepare()
    build()
