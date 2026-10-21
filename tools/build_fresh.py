"""Report source vs build timestamps, to catch a stale packaged exe.

A PyInstaller ``dist`` build is a snapshot: it goes stale the moment any
source file changes.  For a demo (a class project, a viva, a showcase) a
stale exe is the single most likely way the *old* game gets shown while the
student talks about the *new* one, so compare the newest source file against
the packaged binary and say plainly which one is ahead.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "PongPro" / "PongPro.exe"


def _newest(patterns: tuple[str, ...]) -> tuple[Path, float] | None:
    best: tuple[Path, float] | None = None
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            mtime = path.stat().st_mtime
            if best is None or mtime > best[1]:
                best = (path, mtime)
    return best


def main() -> int:
    source = _newest(("src/**/*.py", "main.py", "pongpro.spec"))
    if source is None:
        print("no source files found")
        return 1

    src_path, src_mtime = source
    stamp = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")  # noqa: E731

    print(f"newest source : {src_path.relative_to(ROOT)}  {stamp(src_mtime)}")

    if not EXE.exists():
        print(f"packaged exe  : MISSING  ({EXE.relative_to(ROOT)})")
        print("\nACTION: build one before the demo:")
        print("        pyinstaller --noconfirm --clean pongpro.spec")
        return 1

    exe_mtime = EXE.stat().st_mtime
    print(f"packaged exe  : {EXE.relative_to(ROOT)}  {stamp(exe_mtime)}")

    if src_mtime > exe_mtime:
        age_h = (src_mtime - exe_mtime) / 3600.0
        print(f"\nSTALE: source is {age_h:.1f}h newer than the exe.")
        print("       The packaged game does NOT include the latest changes.")
        print("ACTION: pyinstaller --noconfirm --clean pongpro.spec")
        return 1

    print("\nOK: the exe is at least as new as every source file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
