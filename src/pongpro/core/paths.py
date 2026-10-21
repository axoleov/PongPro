"""Filesystem locations for logs, saves and bundled data.

Resolves correctly both when running from a source checkout and when frozen
by PyInstaller (``sys.frozen`` is set), which is the usual source of
"works on my machine" bugs in shipped games.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "PongPro"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Root of the source checkout (or the bundle dir when frozen)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # src/pongpro/core/paths.py -> parents[3] == repo root
    return Path(__file__).resolve().parents[3]


def bundle_dir() -> Path:
    """Directory containing read-only game data shipped with the build."""
    if is_frozen():
        return project_root()
    return project_root() / "assets"


def user_data_dir() -> Path:
    """Per-user writable directory (``%LOCALAPPDATA%\\PongPro`` on Windows).

    Falls back to ``./PongProData`` next to the executable when the environment
    variable is missing (locked-down environments, CI, portable builds).
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    else:  # pragma: no cover - convenience for non-Windows dev runs
        base = os.environ.get("XDG_DATA_HOME")
        if base:
            base = str(Path(base))
        else:
            base = str(Path.home() / ".local" / "share")
    root = Path(base) if base else (project_root() / "PongProData")
    path = root / APP_DIR_NAME
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = project_root() / APP_DIR_NAME
        path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    """Directory for rotating log files and crash reports."""
    path = user_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return user_data_dir() / "settings.json"


def stats_path() -> Path:
    return user_data_dir() / "stats.json"


def replay_path() -> Path:
    return user_data_dir() / "last_replay.json"


def shop_path() -> Path:
    """Coins, inventory and the equipped loadout.

    Kept out of ``stats.json`` on purpose: that document's migration drops
    unknown keys, so an older build could silently erase purchases.
    """
    return user_data_dir() / "shop.json"
