#!/usr/bin/env python3
"""PongPro launcher for source checkouts: ``python main.py``.

Adds ``src/`` to ``sys.path`` so the project runs without installation.
Prefer ``pip install -e .`` (see pyproject.toml) for day-to-day development.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


def _enable_dpi_awareness() -> None:
    """Windows: render at native resolution instead of a blurred stretch."""
    if os.name != "nt":
        return
    try:
        import ctypes

        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
            return
        except Exception:  # noqa: BLE001
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except Exception:  # noqa: BLE001
            pass
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    _enable_dpi_awareness()
    from pongpro.__main__ import main as package_main

    return package_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
