@echo off
rem Build a Windows distribution of PongPro (onedir, windowed).
rem
rem Usage:  tools\build_release.bat
rem Output: dist\PongPro\PongPro.exe

setlocal
cd /d "%~dp0.."

python -m pip install --quiet --upgrade pyinstaller || exit /b 1

rem The .ico is generated rather than checked in, so make sure it exists
rem before PyInstaller looks for it - the spec silently ships the default
rem icon otherwise, and the build still reports success.
if not exist "packaging\pongpro.ico" (
    echo packaging\pongpro.ico is missing - generating it
    python tools\make_icon.py || exit /b 1
)

python -m PyInstaller --noconfirm --clean pongpro.spec || exit /b 1

if not exist "dist\PongPro\PongPro.exe" (
    echo BUILD FAILED: dist\PongPro\PongPro.exe not found
    exit /b 1
)

echo.
echo BUILD OK: dist\PongPro\PongPro.exe
endlocal
