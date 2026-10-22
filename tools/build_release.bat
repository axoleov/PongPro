@echo off
rem Build a Windows distribution of PongPro (onefile, windowed).
rem
rem Usage:  tools\build_release.bat
rem Output: dist\PongPro.exe   (single self-contained executable)
rem         Builds\PongPro.exe (copy that git actually tracks)

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

if not exist "dist\PongPro.exe" (
    echo BUILD FAILED: dist\PongPro.exe not found
    exit /b 1
)

echo.
echo BUILD OK: dist\PongPro.exe

rem Copies to Builds\ and proves every file there is trackable by git.
rem This gate exists because the first release shipped without it and git
rem silently dropped 63 .pyd files behind "*.py[cod]".
python tools\stage_build.py || exit /b 1

endlocal
