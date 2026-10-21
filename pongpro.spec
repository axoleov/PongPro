# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PongPro (Windows, onedir).

Build with:  pyinstaller --noconfirm --clean pongpro.spec

We ship **onedir** rather than onefile on purpose: onefile extracts to a temp
dir on every launch (slow start, AV false-positives), while onedir starts
instantly and is trivially debuggable.  There are no binary assets to collect
because every sound and the music loop are synthesised with NumPy at start-up.
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PongPro",
    icon=str(icon) if icon.exists() else None,  # packaging/pongpro.ico (optional)
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed game: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PongPro",
)
