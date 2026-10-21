"""Test package: puts ``src/`` on ``sys.path`` before any test imports."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Headless by default: tests never touch a real display or audio device.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

# Redirect per-user persistence into a scratch directory so unit tests never
# read or write the real player profile (%LOCALAPPDATA%\PongPro).
import tempfile  # noqa: E402

_DATA_ROOT = tempfile.mkdtemp(prefix="pongpro_tests_")
os.environ["LOCALAPPDATA"] = _DATA_ROOT
os.environ.setdefault("XDG_DATA_HOME", _DATA_ROOT)
