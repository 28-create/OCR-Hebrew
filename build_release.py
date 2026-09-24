"""Build the offline Windows installation package with one command."""
from pathlib import Path
import importlib.metadata
import json
import os
import runpy
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
DIST = STAGE / 'onedir'
VERSION = runpy.run_path(str(SOURCE / 'version.py'))['VERSION']


def write_version_info():
    components = tuple(int(part) for part in VERSION.split('.'))
    if len(components) > 4 or not components:
        raise ValueError(f'Invalid Windows version: {VERSION}')
    windows_version = components + (0,) * (4 - len(components))
    (ROOT / 'version_info.txt').write_text(
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={windows_version}, prodvers={windows_version}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[StringFileInfo([StringTable('040c04b0', [\n"
        "    StringStruct('CompanyName', 'Aleph OCR'),\n"
        "    StringStruct('FileDescription', 'Aleph OCR - OCR hébreu et Rachi hors ligne'),\n"
        f"    StringStruct('FileVersion', '{VERSION}'),\n"
        "    StringStruct('InternalName', 'AlephOCR'),\n"
        "    StringStruct('OriginalFilename', 'AlephOCR.exe'),\n"
        "    StringStruct('ProductName', 'Aleph OCR'),\n"
        f"    StringStruct('ProductVersion', '{VERSION}')\n"
        "  ])]), VarFileInfo([VarStruct('Translation', [1036, 1200])])]\n)\n",
        encoding='utf-8',
    )


def compiler_path():
    configured = os.environ.get('INNO_SETUP_ISCC')
    candidates = [Path(configured)] if configured else []
    candidates += [ROOT / 'tools/Inno Setup 6/ISCC.exe',
                   Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Inno Setup 6/ISCC.exe',
                   Path(os.environ.get('PROGRAMFILES(X86)', '')) / 'Inno Setup 6/ISCC.exe',
                   Path(os.environ.get('PROGRAMFILES', '')) / 'Inno Setup 6/ISCC.exe']
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError('Inno Setup 6 compiler (ISCC.exe) required; set INNO_SETUP_ISCC')


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def prepare():
    subprocess.run([sys.executable, str(ROOT / 'make_logo.py')], check=True)
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
    write_version_info()
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--distpath', str(DIST), '--workpath', str(ROOT / 'pyinstaller-build-v03'),
               str(ROOT / 'AlephOCR.spec')]
    subprocess.run(command, check=True)
    installed_app = DIST / 'AlephOCR'
    if not (installed_app / 'AlephOCR.exe').is_file():
        raise RuntimeError('PyInstaller did not produce the application folder')
    subprocess.run([str(compiler_path()), '/Q', f'/DProductVersion={VERSION}',
                    f'/DSourceDir={installed_app}', f'/DOutputDir={OUTPUT}',
                    str(ROOT / 'AlephOCR-Setup.iss')], cwd=ROOT, check=True)
    if not (OUTPUT / 'AlephOCR-Setup.exe').is_file():
        raise RuntimeError('Inno Setup did not produce AlephOCR-Setup.exe')
    portable_command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                        '--distpath', str(OUTPUT), '--workpath', str(ROOT / 'pyinstaller-build-portable'),
                        str(ROOT / 'AlephOCR-portable.spec')]
    subprocess.run(portable_command, check=True)
    if not (OUTPUT / 'AlephOCR.exe').is_file():
        raise RuntimeError('PyInstaller did not produce the portable executable')
    copy(ASSETS / 'logo.png', OUTPUT / 'AlephOCR-logo.png')
    copy(ASSETS / 'logo.svg', OUTPUT / 'AlephOCR-logo.svg')
    with zipfile.ZipFile(OUTPUT / 'AlephOCR-sources.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in SOURCE.rglob('*.py'):
            archive.write(file, 'work/aleph/' + file.relative_to(SOURCE).as_posix())
        for file in ASSETS.rglob('*'):
            if file.is_file():
                archive.write(file, 'work/aleph/assets/' + file.relative_to(ASSETS).as_posix())
        for name in ['build_release.py', 'AlephOCR.spec', 'AlephOCR-portable.spec', 'AlephOCR-Setup.iss', 'fetch_assets.py', 'verify_release.py', 'version_info.txt',
                     'test_core.py', 'test_app.py', 'test_quick.py', 'test_smart_ocr.py', 'test_session.py',
                     'conftest.py', 'pytest.ini', 'make_demo.py', 'make_logo.py', 'make_benchmark_corpus.py', 'run_benchmark.py']:
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
    print(f'Installer and portable executable ready in {OUTPUT}', flush=True)


if __name__ == '__main__':
    prepare()
    build()
