@echo off
REM build.bat — Build Auri.exe for Windows
REM Run from repo root in an activated venv:
REM   pip install pyinstaller==6.13.0
REM   build.bat

setlocal
echo [Auri Build] Checking PyInstaller...
pyinstaller --version
if errorlevel 1 (
    echo ERROR: pyinstaller not found. Run: pip install pyinstaller==6.13.0
    exit /b 1
)
echo [Auri Build] Cleaning previous build...
if exist build\ rmdir /s /q build
if exist dist\ rmdir /s /q dist
echo [Auri Build] Running PyInstaller...
pyinstaller auri.spec
if errorlevel 1 (
    echo ERROR: Build failed. See output above.
    exit /b 1
)
echo.
echo ============================================================
echo  SUCCESS: dist\Auri.exe
echo  First launch takes 15-20 seconds to extract.
echo  Subsequent launches are faster.
echo ============================================================
pause
