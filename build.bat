@echo off
REM Windows batch script to build MelkoLeaf executable
echo ============================================================
echo MelkoLeaf Build Script
echo ============================================================
echo.
echo Building MelkoLeaf executable...
echo This will:
echo   1. Obfuscate code with PyArmor
echo   2. Build executable with PyInstaller
echo   3. Include all dependencies (ttkbootstrap, pystray, etc.)
echo.
python build.py
if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================================
    echo Build completed successfully!
    echo Executable location: dist\MelkoLeaf.exe
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo Build failed! Check the error messages above.
    echo ============================================================
)
pause

