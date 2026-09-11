# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all('playwright')

block_cipher = None

app_hiddenimports = [
    'app.main_window',
    'app.main_window_v209',
    'app.main_window_v210',
    'app.db',
    'app.excel_service',
    'app.rpa.browser',
    'app.rpa.publisher',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=playwright_binaries,
    datas=playwright_datas + [
        ('config/selectors.json', 'config'),
        ('samples/相似品批量任务模板.xlsx', 'samples'),
        ('assets/DouRPA.ico', 'assets'),
        ('assets/DouRPA.png', 'assets'),
    ],
    hiddenimports=playwright_hiddenimports + app_hiddenimports,
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
    [],
    exclude_binaries=True,
    name='DouRPA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/DouRPA.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DouRPA',
)
