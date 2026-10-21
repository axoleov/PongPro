"""Copy the fresh PyInstaller build into ``Builds/`` for committing.

``dist/`` is gitignored (it is regenerable output), but the built game has to
*ship* somewhere the repository will track, so this copies it to ``Builds/``.

Two checks run before the copy finishes, because both fail silently otherwise:

1. The source build must be newer than every source file.  Committing a stale
   exe is worse than committing none - the repository would advertise a game
   that does not match the code beside it.
2. The destination must not be swallowed by ``.gitignore``.  The ignore file
   deliberately contains ``build/``, and a case-insensitive filesystem plus a
   directory called ``Builds/`` is exactly the kind of near-miss that quietly
   drops 67 MB of files from a push while ``git add`` reports success.

Copies are verified by file count and total bytes, not just by "no error".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dist" / "PongPro"
DST = ROOT / "Builds" / "PongPro"


def measure(path: Path) -> tuple[int, int]:
    """(total bytes, file count) for a whole subtree."""
    total = 0
    count = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
                count += 1
            except OSError:
                pass
    return total, count


def newest_source_mtime() -> float:
    newest = 0.0
    for pattern in ("src/**/*.py", "main.py", "pongpro.spec"):
        for path in ROOT.glob(pattern):
            if path.is_file():
                newest = max(newest, path.stat().st_mtime)
    return newest


def check_not_ignored(path: Path) -> bool:
    """True if git would refuse to track ``path``."""
    result = subprocess.run(
        ["git", "check-ignore", "-v", str(path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"IGNORED by git: {path.relative_to(ROOT)}")
        print(f"  rule: {result.stdout.strip()}")
        return True
    return False


def main() -> int:
    exe = SRC / "PongPro.exe"
    if not exe.exists():
        print(f"missing build: {exe.relative_to(ROOT)}")
        print("run tools\\build_release.bat first")
        return 1

    if SRC.stat().st_mtime < newest_source_mtime():
        print("STALE: source files are newer than the build")
        print("rebuild with tools\\build_release.bat before committing")
        return 1

    if DST.exists():
        shutil.rmtree(DST)
    DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC, DST)

    # Checked against the *destination*: dist/ is meant to be ignored, so
    # asking about it would always "fail".  Builds/ must not be, or the push
    # silently omits the game while git add reports success.
    if check_not_ignored(DST / "PongPro.exe"):
        return 1

    src_bytes, src_count = measure(SRC)
    dst_bytes, dst_count = measure(DST)

    print(f"copied {src_count} files / {src_bytes:,} bytes -> "
          f"{DST.relative_to(ROOT)}")
    print(f"verify {dst_count} files / {dst_bytes:,} bytes")

    if (src_bytes, src_count) != (dst_bytes, dst_count):
        print("MISMATCH: the copy is incomplete")
        return 1

    if not (DST / "PongPro.exe").exists():
        print("MISMATCH: PongPro.exe did not survive the copy")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
