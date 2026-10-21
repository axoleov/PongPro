"""Remove regenerable build output and throwaway dev scratch.

Kept separate from the build so the two never get confused: this only ever
*deletes*, and only things that can be reproduced by another command in the
README.  Anything a player or a fresh clone needs is never on this list.

Run with ``--dry-run`` (the default) to see what would go; ``--apply`` to
actually delete.  The dry-run default is deliberate - an irreversible delete
should require saying so out loud.

What is removed, and how to get it back:

  build/            PyInstaller intermediate output  -> build_release.bat
  dist/             the previous packaged build      -> build_release.bat
  tools/shots/      rendered screenshots             -> python tools\\shots.py
  __pycache__/      bytecode caches                  -> recreated on import
  .scratch_layout/  stray scratch dir from an old run -> nothing (it is litter)
  tools/sizes.py, tools/crop.py, tools/probe_*.py,
  tools/icon_sizes.py                                -> one-off investigation
                                                        scripts, already
                                                        superseded by tests
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Whole directories that are pure build output or litter.
_DIRS = (
    "build",
    "dist",
    "tools/shots",
    ".scratch_layout",
)

#: One-off scripts written while investigating specific bugs or designing the
#: icon.  Their findings are now pinned by tests (test_controls.py covers the
#: axis/label work; test_layout.py covers the screen geometry), so keeping
#: them would be keeping a second, weaker copy of a real check.
_FILES = (
    "tools/sizes.py",        # written to size this very cleanup
    "tools/crop.py",         # screenshot cropping, unused once shots settled
    "tools/icon_sizes.py",   # icon legibility strip, one-time design check
    "tools/probe_axes.py",   # axis sign investigation -> now test_paddle.py
    "tools/probe_paddle.py", # paddle drift investigation -> now test_paddle.py
)


def _find_caches() -> list[Path]:
    return [p for p in ROOT.rglob("__pycache__") if p.is_dir()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually delete (default is a dry run)")
    args = parser.parse_args()

    plan: list[tuple[str, Path]] = []
    for rel in _DIRS:
        path = ROOT / rel
        if path.exists():
            plan.append((f"dir  {rel}", path))
    for rel in _FILES:
        path = ROOT / rel
        if path.exists():
            plan.append((f"file {rel}", path))
    for cache in _find_caches():
        plan.append((f"dir  {cache.relative_to(ROOT)}", cache))

    if not plan:
        print("nothing to clean")
        return 0

    freed = 0
    for label, path in plan:
        if path.is_file():
            freed += path.stat().st_size
        else:
            for dirpath, _dirs_, files in os.walk(path):
                for name in files:
                    try:
                        freed += (Path(dirpath) / name).stat().st_size
                    except OSError:
                        pass

    mode = "removing" if args.apply else "would remove"
    print(f"{mode} {len(plan)} entries (~{freed / 1024 / 1024:.1f} MB):\n")
    for label, _path in plan:
        print(f"  {label}")

    if not args.apply:
        print("\nDRY RUN - re-run with --apply to delete.")
        return 0

    failures = 0
    for _label, path in plan:
        try:
            if path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path, ignore_errors=True)
        except OSError as exc:
            failures += 1
            print(f"FAILED {path}: {exc}")

    print(f"\ndone ({failures} failures)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
