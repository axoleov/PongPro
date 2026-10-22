"""Copy the fresh PyInstaller build into ``Builds/`` for committing.

``dist/`` is gitignored (it is regenerable output), but the finished game has
to *ship* somewhere the repository will track, so this copies the executable
into ``Builds/``.

Three checks run before this reports success, because all three otherwise fail
silently:

1. The build must be newer than every source file.  Committing a stale exe is
   worse than committing none - the repository would advertise a game that does
   not match the code beside it.
2. The bytes must survive the copy, compared as (file count, total size).
3. **Every** file under ``Builds/`` must be trackable by git.  This is the
   check that was missing: the original script asked about one path (the exe)
   and stopped, while the stock rule ``*.py[cod]`` was quietly swallowing 63
   ``.pyd`` files out of a folder build.  ``git add`` still reported success, so
   the push went out green and the game crashed on someone else's machine.
   Checking a single file can never catch a class of file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dist" / "PongPro.exe"
DST = ROOT / "Builds" / "PongPro.exe"


def measure(path: Path) -> tuple[int, int]:
    """(total bytes, file count) for a file or a whole subtree."""
    if path.is_file():
        return path.stat().st_size, 1
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


def untracked_files(root: Path) -> list[str]:
    """Files under ``root`` that git would refuse to track.

    ``git check-ignore`` exits 0 when the path *is* ignored and 1 when it is
    not, and ``-v`` names the offending rule and its line number so a failure
    explains itself instead of just pointing at a filename.
    """
    blocked: list[str] = []
    paths: list[Path] = [root] if root.is_file() else sorted(root.rglob("*"))
    for path in paths:
        if not path.is_file():
            continue
        result = subprocess.run(
            ["git", "check-ignore", "-v", str(path)],
            cwd=ROOT, capture_output=True, text=True,
        )
        if result.returncode == 0:
            rule = result.stdout.strip()
            blocked.append(f"  {path.relative_to(ROOT)}\n    {rule}")
    return blocked


def main() -> int:
    if not SRC.exists():
        print(f"missing build: {SRC.relative_to(ROOT)}")
        print("run tools\\build_release.bat first")
        return 1

    if SRC.stat().st_mtime < newest_source_mtime():
        print("STALE: source files are newer than the build")
        print("rebuild with tools\\build_release.bat before committing")
        return 1

    DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC, DST)

    src_bytes, src_count = measure(SRC)
    dst_bytes, dst_count = measure(DST)
    print(f"copied {src_count} file / {src_bytes:,} bytes -> "
          f"{DST.relative_to(ROOT)}")

    if (src_bytes, src_count) != (dst_bytes, dst_count):
        print("MISMATCH: the copy is incomplete")
        return 1

    # Checked against *everything* in Builds/, not a single hand-picked path:
    # a rule that hides one file will usually hide its siblings too.
    blocked = untracked_files(ROOT / "Builds")
    if blocked:
        print(f"WOULD NOT PUSH: {len(blocked)} file(s) in Builds/ are ignored:")
        print("\n".join(blocked))
        print("fix .gitignore - git add would report success and drop them")
        return 1

    print(f"OK: 1 file, {dst_bytes:,} bytes, not ignored by git")
    return 0


if __name__ == "__main__":
    sys.exit(main())
