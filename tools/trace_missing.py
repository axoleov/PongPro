"""Find files that exist in the local build but never reached git.

The initial push shipped a game that crashed on another machine with
``No module named '_socket'``.  The local ``Builds/`` copy was complete and
byte-identical to ``dist/``, and the push succeeded, so the corruption was
upstream of both: something filtered files *out* of the commit while ``git
add`` reported success.

The classic culprit is ``*.py[cod]``, the stock CPython cache-ignore pattern.
It reads as "compiled bytecode" but the bracket also matches ``.pyd`` - the
compiled C extension modules a frozen interpreter needs at run time.  Nothing
in normal Python work sees this, because ``.pyd`` files are build output you
never commit.  A frozen build is the one place they are load-bearing.

This reports every such file, so the gap is measured rather than guessed at.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DST = ROOT / "Builds"


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT,
                            capture_output=True, text=True)
    return result.stdout


def main() -> int:
    if not DST.exists():
        print("no Builds/ directory to inspect")
        return 1

    # What git actually holds for the build tree.
    tracked = {
        line for line in git("ls-files", "--", "Builds").splitlines() if line
    }

    # What is on disk.
    on_disk = {
        str(p.relative_to(ROOT).as_posix())
        for p in DST.rglob("*")
        if p.is_file()
    }

    missing = sorted(on_disk - tracked)
    print(f"on disk : {len(on_disk)} files")
    print(f"tracked : {len(tracked)} files")
    print(f"missing : {len(missing)} files\n")

    if not missing:
        print("nothing missing - the commit covers the whole build")
        return 0

    # Explain the first one with git's own words, which names the offending
    # rule and its line number instead of leaving us to guess.
    sample = missing[0]
    result = subprocess.run(["git", "check-ignore", "-v", sample],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode == 0:
        print("why the first file is excluded:")
        print(f"  {result.stdout.strip()}\n")
    else:
        print(f"why the first file is missing:")
        print(f"  {sample} is NOT ignored - it simply has not been")
        print(f"  added to the index yet (git add).\n")

    # Group by suffix so the shape of the loss is obvious at a glance.
    by_suffix: dict[str, int] = {}
    for rel in missing:
        by_suffix[Path(rel).suffix or "(none)"] = \
            by_suffix.get(Path(rel).suffix or "(none)", 0) + 1
    print("missing by extension:")
    for suffix, count in sorted(by_suffix.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>4}  {suffix}")

    print("\nfirst 15 missing files:")
    for rel in missing[:15]:
        print(f"  {rel}")

    # Is the game's startup path specifically affected?
    critical = [
        "_socket.pyd",
        "select.pyd",
        "_queue.pyd",
        "math.pyd",
        "_ctypes.pyd",
    ]
    print("\nrun-time critical extensions:")
    for name in critical:
        hits = [m for m in missing if m.endswith(name)]
        present = [m for m in tracked if m.endswith(name)]
        state = "MISSING" if hits else ("tracked" if present else "absent")
        print(f"  {name:<16} {state}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
