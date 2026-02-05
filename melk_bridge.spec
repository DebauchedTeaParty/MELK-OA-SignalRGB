# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Add obfuscated directory to Python path so imports work
obfuscated_path = Path('C:\\Users\\iamro\\Documents\\GitHub\\MELK-OA-SignalRGB\\build\\obfuscated')
if str(obfuscated_path) not in sys.path:
    sys.path.insert(0, str(obfuscated_path))

# Collect all data and binaries for pystray and PIL
pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all('pystray')
pil_datas, pil_binaries, pil_hiddenimports = collect_all('PIL')

block_cipher = None

a = Analysis(
    ['C:\\Users\\iamro\\Documents\\GitHub\\MELK-OA-SignalRGB\\build\\obfuscated\\start_melk_bridge.py'],
    pathex=['C:\\Users\\iamro\\Documents\\GitHub\\MELK-OA-SignalRGB\\build\\obfuscated'],
    binaries=pystray_binaries + pil_binaries,
    datas=[
        ('C:\\Users\\iamro\\Documents\\GitHub\\MELK-OA-SignalRGB\\build\\obfuscated\\icons', 'icons'),
        ('C:\\Users\\iamro\\Documents\\GitHub\\MELK-OA-SignalRGB\\build\\obfuscated\\pyarmor_runtime_000000', 'pyarmor_runtime_000000'),
    ] + pystray_datas + pil_datas,
    hiddenimports=[
        'melk_ble',
        'melk_bridge',
        'melk_tray',
        'melk_gui',
        'pystray',
        'pystray._base',
        'pystray._win32',
        'pystray._util',
        'PIL',
        'PIL._tkinter_finder',
        'PIL.Image',
        'PIL.ImageTk',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        'tkinter.scrolledtext',
        'ttkbootstrap',
        'ttkbootstrap.constants',
        'zeroconf',
        'flask',
        'flask_cors',
        'bleak',
        'btledstrip',
        'pyarmor_runtime',
    ] + pystray_hiddenimports + pil_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MelkoLeaf',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Hide console window - output will be shown in GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='C:\\Users\\iamro\\Documents\\GitHub\\MELK-OA-SignalRGB\\icons\\rgb.png',
    uac_admin=False,
)
