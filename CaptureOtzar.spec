# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('C:/Users/Mimran/Documents/Codex/2026-09-14/je-veux-faire-un-nouvel-outil/work/release-stage/assets', 'assets')]
datas += collect_data_files('pypdfium2')
datas += collect_data_files('pypdfium2_raw')


a = Analysis(
    ['C:/Users/Mimran/Documents/Codex/2026-09-14/je-veux-faire-un-nouvel-outil/work/aleph/app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CaptureOtzar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='C:/Users/Mimran/Documents/Codex/2026-09-14/je-veux-faire-un-nouvel-outil/work/version_info.txt',
    icon=['C:/Users/Mimran/Documents/Codex/2026-09-14/je-veux-faire-un-nouvel-outil/work/release-stage/assets/app.ico'],
)
