@echo off
setlocal
cd /d "%~dp0"

echo.
echo   ================================
echo      PongPro  -  run from source
echo   ================================
echo.
echo   Installs pygame and numpy if they are missing, then starts the game.
echo.

rem ------------------------------------------------------------------
rem Find an interpreter.
rem
rem The Python Launcher is tried first on purpose: on Windows "python" is
rem an App Execution Alias, so when Python is NOT installed it opens the
rem Microsoft Store instead of running anything, which makes this script
rem look like it hung on somebody else's PC.  "py -3" has no such alias.
rem ------------------------------------------------------------------
set "PY="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :deps

python -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=python"

:deps
if defined PY goto :install

echo   [X] Python 3.11 or newer was not found on this computer.
echo.
echo       Install it from https://www.python.org/downloads/ and be sure
echo       to tick "Add python.exe to PATH" in the installer.
echo.
echo       You do not need Python to PLAY the game - just double-click
echo       Builds\PongPro.exe instead.
echo.
pause
exit /b 1

:install
echo   [1/3] Interpreter : %PY%
echo   [2/3] Checking for pygame and numpy ...
%PY% -c "import pygame, numpy" >nul 2>&1
if not errorlevel 1 goto :run

echo         Installing ^(internet connection required^) ...
%PY% -m pip install --upgrade "pygame>=2.6" "numpy>=1.26"
if not errorlevel 1 goto :verify

rem No write access to the system Python - common on school and work
rem machines - so fall back to installing for this user only.
echo         Retrying for the current user only ...
%PY% -m pip install --user --upgrade "pygame>=2.6" "numpy>=1.26"
if not errorlevel 1 goto :verify

echo.
echo   [X] The dependencies could not be installed.
echo       Check your internet connection and run this file again.
echo.
pause
exit /b 1

:verify
%PY% -c "import pygame, numpy" >nul 2>&1
if not errorlevel 1 goto :run

echo   [X] pygame and numpy are still not importable after installing.
echo       Try installing them by hand:
echo.
echo           %PY% -m pip install pygame numpy
echo.
pause
exit /b 1

:run
echo   [3/3] Starting PongPro ...
echo.
%PY% main.py
set "EXITCODE=%ERRORLEVEL%"
if "%EXITCODE%"=="0" exit /b 0

echo.
echo   [X] PongPro exited with code %EXITCODE%.
echo       The traceback is above - the game needs pygame 2.6+ and numpy.
echo.
pause
exit /b %EXITCODE%
