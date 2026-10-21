"""User-data persistence (settings, stats, replays)."""

from __future__ import annotations

from .store import (
    REPLAY_VERSION,
    STATS_VERSION,
    Storage,
    default_stats,
)

__all__ = ["Storage", "default_stats", "STATS_VERSION", "REPLAY_VERSION"]
