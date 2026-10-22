# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PongPro (Windows, **onefile**).

Build with:  pyinstaller --noconfirm --clean pongpro.spec

We ship a *single* ``PongPro.exe``: double-click it on any Windows PC with no
Python, no folder to lose, nothing to install.  PyInstaller packs the
interpreter, pygame and NumPy into the executable itself.

The costs are accepted knowingly: the bootloader unpacks into a temp directory
on every launch (a second or two of cold start) and executables built this way
are more likely to trip antivirus heuristics, because malware uses the same
format.  There are no binary assets to collect because every sound and the
music loop are synthesised with NumPy at start-up.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()

# numpy is imported at runtime by the audio/physics modules; collecting its
# submodules keeps the freeze analysis honest across versions.
hiddenimports = collect_submodules("numpy")

# The entry point imports scenes lazily through the state machine, so pull in
# the whole package explicitly.
hiddenimports += collect_submodules("pongpro")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc_data"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Optional: give the exe a real icon when one is present.
icon = ROOT / "packaging" / "pongpro.ico"

# onefile: the payloads are handed straight to EXE (no exclude_binaries, no
# COLLECT), so everything lands inside the one executable instead of an
# _internal/ folder beside it.  runtime_tmpdir=None is what makes the
# bootloader unpack to the system temp directory at launch.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PongPro",
    icon=str(icon) if icon.exists() else None,  # packaging/pongpro.ico (optional)
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,     # single self-contained file
    console=False,           # windowed game: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
)
