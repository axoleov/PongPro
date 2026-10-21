"""Verify the installed distribution: import, metadata and CLI entry point."""

import os
import subprocess
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


def main() -> int:
    import importlib.metadata as md

    import pongpro

    print("import ok:", pongpro.__file__)
    print("version:", pongpro.__version__, "| dist:", md.version("pongpro"))

    try:
        dist = md.distribution("pongpro")
        entry = [e for e in dist.entry_points if e.name == "pongpro"]
        print("console script:", entry[0].value if entry else "MISSING")
    except md.PackageNotFoundError:
        print("console script: package not found")

    # A short headless run through -m proves the packaged entry point works.
    proc = subprocess.run(
        [sys.executable, "-m", "pongpro", "--frames", "120", "--skip-splash",
         "--quiet"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ},
    )
    print("python -m pongpro --frames 120: rc =", proc.returncode)
    if proc.returncode != 0:
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
