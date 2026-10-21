"""Report the size of a directory tree before it gets committed.

Committing binaries to git is irreversible in practice (history keeps every
byte forever), so the size is measured rather than guessed.  GitHub rejects
any single file over 100 MB and warns above 50 MB, so both thresholds are
called out explicitly alongside the largest individual files.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GITHUB_WARN_MB = 50
GITHUB_HARD_MB = 100


def measure(path: Path) -> tuple[int, int, list[tuple[int, Path]]]:
    """(total bytes, file count, [(size, path), ...] per file)."""
    total = 0
    files: list[tuple[int, Path]] = []
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            full = Path(dirpath) / name
            try:
                size = full.stat().st_size
            except OSError:
                continue
            total += size
            files.append((size, full))
    return total, len(files), files


def fmt(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}"
        n /= 1024.0
    return f"{n} B"


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "PongPro"
    if not target.exists():
        print(f"missing: {target}")
        return 1

    total, count, files = measure(target)
    mb = total / 1024 / 1024
    print(f"{target.name}: {count} files, {fmt(total)}")
    print()

    print("largest 8 files:")
    for size, path in sorted(files, reverse=True)[:8]:
        print(f"  {fmt(size):>10}  {path.relative_to(target)}")

    print()
    if mb > GITHUB_HARD_MB:
        print(f"OVER GITHUB'S {GITHUB_HARD_MB} MB SINGLE-FILE LIMIT")
        return 1
    if mb > GITHUB_WARN_MB:
        print(f"note: total exceeds GitHub's {GITHUB_WARN_MB} MB soft warning "
              f"({fmt(total)})")
    else:
        print("within GitHub's comfortable range")
    return 0


if __name__ == "__main__":
    sys.exit(main())
