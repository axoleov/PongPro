"""Durable persistence: settings, lifetime statistics and last-match replay.

Writes are atomic (temp file + ``os.replace``) so a crash mid-save can never
truncate a file, and every payload carries a ``version`` integer so future
releases can migrate old data instead of discarding it.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from ..core import paths
from ..core.settings import SETTINGS_VERSION, Settings
from ..economy.wallet import WALLET_VERSION, default_wallet

log = logging.getLogger(__name__)

#: v2: ``record_match`` used to fold a match in with
#: ``total_hits += stored + hits``, which *doubled* the lifetime counter on
#: every game.  v1 figures are 2**n growth rather than a count, so there is
#: nothing worth preserving there - see ``_migrate_stats``.
STATS_VERSION = 2
REPLAY_VERSION = 1


def default_stats() -> dict[str, Any]:
    """Schema of a fresh player profile."""
    return {
        "version": STATS_VERSION,
        "first_run_unix": time.time(),
        "matches_played": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "by_difficulty": {},  # {"easy": {"played": n, "won": n}, ...}
        "longest_rally": 0,
        "total_goals": 0,
        "total_hits": 0,
        "fastest_ball": 0.0,
        "playtime_seconds": 0.0,
        "last_match": None,
        # FOCUS personal bests.  Flat keys rather than a nested dict so they
        # ride the same merge-over-defaults and the same corrupt-value guard
        # as every other figure, which is why adding them needs no version
        # bump: an older profile simply reads them as zero once.
        "focus_best_time": 0.0,
        "focus_best_returns": 0,
    }


class Storage:
    """Reads/writes user data under the per-user application data folder."""

    def __init__(self, directory: Path | None = None) -> None:
        self.dir = directory or paths.user_data_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.dir / "settings.json"
        self.stats_file = self.dir / "stats.json"
        self.replay_file = self.dir / "last_replay.json"
        #: Coins, inventory and equipped cosmetics.  Separate from
        #: ``stats.json`` so a migration that drops unknown keys can never
        #: destroy a player's purchases.
        self.shop_file = self.dir / "shop.json"

    # -- generic atomic JSON ----------------------------------------------
    def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            log.warning("Discarding non-object JSON at %s", path)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to read %s: %s", path, exc)
            # Corrupt file -> keep a copy for support, start clean.
            try:
                path.replace(path.with_suffix(path.suffix + ".corrupt"))
            except OSError:
                pass
        return None

    def _write_json(self, path: Path, payload: dict[str, Any]) -> bool:
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            return True
        except OSError as exc:
            log.error("Failed to save %s: %s", path, exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    # -- settings ---------------------------------------------------------
    def load_settings(self) -> Settings:
        raw = self._read_json(self.settings_file)
        if not raw:
            settings = Settings()
            settings.validate()
            return settings
        settings = Settings.from_dict(raw)
        if raw.get("version") not in (None, SETTINGS_VERSION):
            log.info("Migrating settings from v%s to v%s",
                     raw.get("version"), SETTINGS_VERSION)
        return settings

    def save_settings(self, settings: Settings) -> bool:
        settings.validate()
        return self._write_json(self.settings_file, settings.to_dict())

    # -- stats ------------------------------------------------------------
    def load_stats(self) -> dict[str, Any]:
        stats = default_stats()
        raw = self._read_json(self.stats_file)
        if raw:
            stats = _migrate_stats(raw)
        return stats

    def save_stats(self, stats: dict[str, Any]) -> bool:
        stats["version"] = STATS_VERSION
        return self._write_json(self.stats_file, stats)

    def record_match(self, *, winner: int | None, mode: str,
                     difficulty: str | None,
                     score: tuple[int, int], rally: int, hits: int,
                     goals: int, duration: float,
                     fastest: float) -> dict[str, Any]:
        """Fold one finished match into the lifetime profile and persist it.

        ``winner`` may be None: a FOCUS run has no winner, so it records the
        lifetime tallies (returns, goals, playtime) without touching the
        win/loss/draw bookkeeping.  Counting it as a draw would quietly wreck
        the win rate of someone who is actually doing well at the mode.
        """
        stats = self.load_stats()
        stats["matches_played"] += 1
        if winner is None:
            pass
        elif winner == 0:
            stats["wins"] += 1
        elif winner == 1:
            stats["losses"] += 1
        else:
            stats["draws"] += 1
        if mode == "solo" and difficulty:
            bucket = stats["by_difficulty"].setdefault(
                difficulty, {"played": 0, "won": 0, "lost": 0}
            )
            bucket["played"] += 1
            if winner == 0:
                bucket["won"] += 1
            elif winner == 1:
                bucket["lost"] += 1
        stats["longest_rally"] = max(int(stats["longest_rally"]), rally)
        # Additive, not self-referential: the old ``+= stored + hits`` doubled
        # the lifetime counter on every match, so the menu's TOTAL RETURNS read
        # 3440914 after twenty games and kept doubling from there.
        stats["total_hits"] += max(0, int(hits))
        stats["total_goals"] += max(0, int(goals))
        stats["fastest_ball"] = max(float(stats["fastest_ball"]), fastest)
        stats["playtime_seconds"] = float(stats["playtime_seconds"]) + max(0.0, duration)
        stats["last_match"] = {
            "unix": time.time(),
            "score": list(score),
            "mode": mode,
            "difficulty": difficulty,
            "rally": rally,
            "duration": duration,
        }
        self.save_stats(stats)
        return stats

    def record_focus(self, *, time: float, returns: int) -> dict[str, Any]:
        """Raise the FOCUS personal bests where this run beats them.

        Returns the whole profile so a caller can show "NEW BEST" without a
        second read.  Both bests move independently: a long, clumsy run can
        set the clock while a short, sharp one sets the returns.
        """
        stats = self.load_stats()
        stats["focus_best_time"] = max(
            float(stats["focus_best_time"]), max(0.0, float(time)))
        stats["focus_best_returns"] = max(
            int(stats["focus_best_returns"]), max(0, int(returns)))
        self.save_stats(stats)
        return stats

    # -- wallet (coins / inventory / loadout) ------------------------------
    def load_wallet(self) -> dict[str, Any]:
        """Raw wallet document, merged over the current schema.

        Validation of *item ids* happens in
        :meth:`pongpro.economy.wallet.Wallet.from_dict`, which is the single
        place that knows the catalog.  Storage only guarantees the shape.
        """
        payload = default_wallet()
        raw = self._read_json(self.shop_file)
        if raw:
            for key, value in raw.items():
                if key in payload and key != "version":
                    payload[key] = value
        payload["version"] = WALLET_VERSION
        for numeric in ("coins", "lifetime_earned", "lifetime_spent",
                        "purchases"):
            try:
                payload[numeric] = max(0, int(payload[numeric]))
            except (TypeError, ValueError):
                payload[numeric] = 0
        if not isinstance(payload.get("owned"), list):
            payload["owned"] = []
        if not isinstance(payload.get("equipped"), dict):
            payload["equipped"] = {}
        return payload

    def save_wallet(self, payload: dict[str, Any]) -> bool:
        payload = dict(payload)
        payload["version"] = WALLET_VERSION
        return self._write_json(self.shop_file, payload)

    # -- replay -----------------------------------------------------------
    def save_replay(self, payload: dict[str, Any]) -> bool:
        payload = dict(payload)
        payload["version"] = REPLAY_VERSION
        return self._write_json(self.replay_file, payload)

    def load_replay(self) -> dict[str, Any] | None:
        raw = self._read_json(self.replay_file)
        if not raw:
            return None
        if raw.get("version") != REPLAY_VERSION:
            log.info("Replay version mismatch (%s), ignoring", raw.get("version"))
            return None
        if not isinstance(raw.get("frames"), list) or not raw["frames"]:
            return None
        return raw


def _migrate_stats(raw: dict[str, Any]) -> dict[str, Any]:
    """Merge stored stats over the current schema, dropping unknown keys."""
    stats = default_stats()
    version = raw.get("version", 1)
    if not isinstance(version, int) or version < 1:
        version = 1
    for key, value in raw.items():
        if key in stats and key != "version":
            stats[key] = value
    # Forward-migration hooks go here, e.g.:
    # if version < 3: stats["new_field"] = default
    if version < 2:
        # v1 summed the counter into itself, so a twenty-match profile read
        # "total_hits": 3440914 (~800 real returns) and would have doubled
        # again with every further match.  The stored figure encodes the
        # *bug*, not the player, so restart both lifetime tallies.  Wins,
        # losses, playtime, longest rally and the per-difficulty table are
        # untouched: none of them were affected.
        #
        # Applied on read rather than on load-and-write, so opening the menu
        # never dirties the file; the first recorded match stamps the profile
        # v2 and the correction sticks.
        stats["total_hits"] = 0
        stats["total_goals"] = 0
    stats["version"] = STATS_VERSION
    # Guard against hand-edited/corrupt values so a bad save can't crash UI.
    for numeric in ("matches_played", "wins", "losses", "draws",
                    "longest_rally", "total_goals", "total_hits",
                    "focus_best_returns"):
        try:
            stats[numeric] = max(0, int(stats[numeric]))
        except (TypeError, ValueError):
            stats[numeric] = 0
    try:
        stats["playtime_seconds"] = max(0.0, float(stats["playtime_seconds"]))
        stats["fastest_ball"] = max(0.0, float(stats["fastest_ball"]))
        stats["focus_best_time"] = max(0.0, float(stats["focus_best_time"]))
    except (TypeError, ValueError):
        stats["playtime_seconds"] = 0.0
        stats["fastest_ball"] = 0.0
        stats["focus_best_time"] = 0.0
    if not isinstance(stats.get("by_difficulty"), dict):
        stats["by_difficulty"] = {}
    return stats
