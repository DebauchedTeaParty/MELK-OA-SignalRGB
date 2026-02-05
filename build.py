"""
Build script for MELK-OA Bridge executable.
Obfuscates code with PyArmor, then builds executable with PyInstaller.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Configuration
SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_DIR = SCRIPT_DIR / "build"
DIST_DIR = SCRIPT_DIR / "dist"
OBFUSCATED_DIR = BUILD_DIR / "obfuscated"
SPEC_FILE = SCRIPT_DIR / "melk_bridge.spec"

# Files to obfuscate
FILES_TO_OBFUSCATE = ["melk_bridge.py", "melk_ble.py", "melk_tray.py", "melk_gui.py"]

# Files to include (not obfuscated)
FILES_TO_INCLUDE = ["start_melk_bridge.py"]

# Directories to include
DIRS_TO_INCLUDE = ["icons"]


def clean_build():
    """Clean previous build artifacts."""
    print("[BUILD] Cleaning previous build...")
    for dir_path in [BUILD_DIR, DIST_DIR, OBFUSCATED_DIR]:
        if dir_path.exists():
            shutil.rmtree(dir_path)
    if SPEC_FILE.exists():
        SPEC_FILE.unlink()
    print("[BUILD] Clean complete.")


def find_pyarmor_command():
    """Find the correct way to invoke PyArmor."""
    # Try direct command first (if pyarmor is in PATH)
    try:
        result = subprocess.run(
            ["pyarmor", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return ["pyarmor"]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    # Try finding pyarmor in Python scripts directory
    try:
        import site
        import pyarmor
        # Try to find pyarmor executable
        scripts_dirs = site.getsitepackages()
        for scripts_dir in scripts_dirs:
            pyarmor_exe = Path(scripts_dir).parent / "Scripts" / "pyarmor.exe"
            if pyarmor_exe.exists():
                return [str(pyarmor_exe)]
    except:
        pass
    
    # Try using pyarmor via Python -c
    try:
        import pyarmor
        # Return None to use Python API
        return None
    except ImportError:
        pass
    
    return None


def check_dependencies():
    """Check if required build tools are installed."""
    print("[BUILD] Checking dependencies...")
    missing = []
    
    pyarmor_cmd = find_pyarmor_command()
    if pyarmor_cmd:
        print("[BUILD] ✓ PyArmor found (command line)")
    else:
        try:
            import pyarmor
            print("[BUILD] ✓ PyArmor found (Python API)")
        except ImportError:
            missing.append("pyarmor")
            print("[BUILD] ✗ PyArmor not found")
    
    try:
        import PyInstaller
        print("[BUILD] ✓ PyInstaller found")
    except ImportError:
        missing.append("pyinstaller")
        print("[BUILD] ✗ PyInstaller not found")
    
    if missing:
        print(f"[BUILD] ERROR: Missing dependencies: {', '.join(missing)}")
        print(f"[BUILD] Install with: pip install {' '.join(missing)}")
        return False, None
    
    return True, pyarmor_cmd


def obfuscate_code(pyarmor_cmd):
    """Obfuscate Python files using PyArmor."""
    print("[BUILD] Obfuscating code with PyArmor...")
    
    # Create obfuscated directory
    OBFUSCATED_DIR.mkdir(parents=True, exist_ok=True)
    
    # Copy non-obfuscated files first
    for file_name in FILES_TO_INCLUDE:
        src = SCRIPT_DIR / file_name
        if src.exists():
            shutil.copy2(src, OBFUSCATED_DIR / file_name)
            print(f"[BUILD] Copied {file_name}")
    
    # Copy directories
    for dir_name in DIRS_TO_INCLUDE:
        src_dir = SCRIPT_DIR / dir_name
        if src_dir.exists():
            dst_dir = OBFUSCATED_DIR / dir_name
            shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
            print(f"[BUILD] Copied directory {dir_name}/")
    
    # Try using PyArmor Python API if command line doesn't work
    if not pyarmor_cmd:
        try:
            import pyarmor
            print("[BUILD] Using PyArmor Python API...")
            # Use pyarmor.cli module
            import pyarmor.cli as cli
            import sys as sys_module
            
            # Use pyarmor API directly
            for file_name in FILES_TO_OBFUSCATE:
                src = SCRIPT_DIR / file_name
                if not src.exists():
                    print(f"[BUILD] WARNING: {file_name} not found, skipping")
                    continue
                
                print(f"[BUILD] Obfuscating {file_name}...")
                try:
                    # Save original argv
                    old_argv = sys_module.argv[:]
                    try:
                        # Build command line arguments for pyarmor
                        sys_module.argv = [
                            'pyarmor', 'gen',
                            '--output', str(OBFUSCATED_DIR),
                            str(src)
                        ]
                        cli.main()
                    finally:
                        sys_module.argv = old_argv
                    print(f"[BUILD] ✓ Obfuscated {file_name}")
                except Exception as e:
                    print(f"[BUILD] ERROR: Failed to obfuscate {file_name}: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
            print("[BUILD] Obfuscation complete.")
            return True
        except ImportError as e:
            print(f"[BUILD] ERROR: PyArmor not available: {e}")
            print("[BUILD] Try: pip install pyarmor")
            return False
    
    # Use command line
    for file_name in FILES_TO_OBFUSCATE:
        src = SCRIPT_DIR / file_name
        if not src.exists():
            print(f"[BUILD] WARNING: {file_name} not found, skipping")
            continue
        
        print(f"[BUILD] Obfuscating {file_name}...")
        try:
            # Build command
            cmd = pyarmor_cmd + ["gen", "--output", str(OBFUSCATED_DIR)]
            
            # Try with advanced options first
            cmd_advanced = cmd + ["--enable-rft", "--enable-bcc", str(src)]
            result = subprocess.run(
                cmd_advanced,
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                # Try without advanced options
                print(f"[BUILD] Advanced options not supported, trying basic obfuscation...")
                cmd_basic = cmd + [str(src)]
                result = subprocess.run(
                    cmd_basic,
                    cwd=SCRIPT_DIR,
                    capture_output=True,
                    text=True,
                    check=True
                )
            
            print(f"[BUILD] ✓ Obfuscated {file_name}")
        except subprocess.CalledProcessError as e:
            print(f"[BUILD] ERROR: Failed to obfuscate {file_name}")
            print(f"[BUILD] Command: {' '.join(cmd_advanced if 'cmd_advanced' in locals() else cmd_basic)}")
            print(f"[BUILD] Return code: {e.returncode}")
            if e.stdout:
                print(f"[BUILD] stdout: {e.stdout}")
            if e.stderr:
                print(f"[BUILD] stderr: {e.stderr}")
            return False
    
    print("[BUILD] Obfuscation complete.")
    return True


def create_spec_file():
    """Create PyInstaller spec file."""
    print("[BUILD] Creating PyInstaller spec file...")
    
    icon_path = SCRIPT_DIR / "icons" / "rgb.png"
    
    # Use repr() to properly escape paths for Python strings
    start_script = repr(str(OBFUSCATED_DIR / "start_melk_bridge.py"))
    icons_dir = repr(str(OBFUSCATED_DIR / "icons"))
    icon_str = repr(str(icon_path)) if icon_path.exists() else "None"
    
    # Add obfuscated directory to pathex so PyInstaller can find obfuscated modules
    obfuscated_path = repr(str(OBFUSCATED_DIR))
    
    # Check for pyarmor_runtime directory and include it
    pyarmor_runtime_dirs = []
    if OBFUSCATED_DIR.exists():
        for item in OBFUSCATED_DIR.iterdir():
            if item.is_dir() and 'pyarmor_runtime' in item.name:
                pyarmor_runtime_dirs.append(repr(str(item)))
    
    # Build datas list - include icons and pyarmor runtime
    datas_list = [f"({icons_dir}, 'icons')"]
    for rt_dir in pyarmor_runtime_dirs:
        rt_name = Path(rt_dir.strip("'\"")).name
        datas_list.append(f"({rt_dir}, '{rt_name}')")
    datas_str = ",\n        ".join(datas_list) if datas_list else ""
    
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Add obfuscated directory to Python path so imports work
obfuscated_path = Path({obfuscated_path})
if str(obfuscated_path) not in sys.path:
    sys.path.insert(0, str(obfuscated_path))

# Collect all data and binaries for pystray and PIL
pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all('pystray')
pil_datas, pil_binaries, pil_hiddenimports = collect_all('PIL')

block_cipher = None

a = Analysis(
    [{start_script}],
    pathex=[{obfuscated_path}],
    binaries=pystray_binaries + pil_binaries,
    datas=[
        {datas_str},
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
    hooksconfig={{}},
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
    icon={icon_str},
    uac_admin=False,
)
"""
    
    SPEC_FILE.write_text(spec_content)
    print(f"[BUILD] ✓ Created {SPEC_FILE.name}")
    return True


def build_executable():
    """Build executable using PyInstaller."""
    print("[BUILD] Building executable with PyInstaller...")
    
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "PyInstaller",
                "--clean",
                "--noconfirm",
                str(SPEC_FILE)
            ],
            cwd=SCRIPT_DIR,
            check=True
        )
        print("[BUILD] ✓ Executable built successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[BUILD] ERROR: Failed to build executable")
        print(f"[BUILD] Return code: {e.returncode}")
        return False


def main():
    """Main build process."""
    print("=" * 60)
    print("MelkoLeaf Build Script")
    print("=" * 60)
    print()
    
    # Check dependencies
    deps_ok, pyarmor_cmd = check_dependencies()
    if not deps_ok:
        sys.exit(1)
    
    # Clean previous builds
    clean_build()
    
    # Obfuscate code
    if not obfuscate_code(pyarmor_cmd):
        print("[BUILD] ERROR: Obfuscation failed")
        sys.exit(1)
    
    # Create spec file
    if not create_spec_file():
        print("[BUILD] ERROR: Failed to create spec file")
        sys.exit(1)
    
    # Build executable
    if not build_executable():
        print("[BUILD] ERROR: Failed to build executable")
        sys.exit(1)
    
    # Final message
    exe_path = DIST_DIR / "MelkoLeaf.exe"
    if exe_path.exists():
        print()
        print("=" * 60)
        print("BUILD SUCCESSFUL!")
        print("=" * 60)
        print(f"Executable: {exe_path}")
        print(f"Size: {exe_path.stat().st_size / (1024*1024):.2f} MB")
        print()
        print("The executable is ready to use.")
    else:
        print("[BUILD] ERROR: Executable not found after build")
        sys.exit(1)


if __name__ == "__main__":
    main()

