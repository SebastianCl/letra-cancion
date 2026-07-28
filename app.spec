# -*- mode: python ; coding: utf-8 -*-
"""
Especificación de PyInstaller para Letra Canción
Genera un ejecutable de una sola carpeta con todos los recursos incluidos
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Colectar datos de PyQt6
pyqt_data = collect_data_files('PyQt6')

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=pyqt_data + [
        ('src/ui', 'src/ui'),
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'qasync',
        'aiohttp',
        'keyboard',
        'deep_translator',
        'winsdk',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LetraCancion',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Sin consola (GUI puro)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/letra-cancion.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LetraCancion',
)
