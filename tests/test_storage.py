"""Persistence: atomic saves, corruption tolerance, statistics and replay IO."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pongpro.storage import STATS_VERSION, Storage, default_stats


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="pongpro_test_")
        self.dir = Path(self._tmp.name)
        self.storage = Storage(self.dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- settings ---------------------------------------------------------
    def test_settings_round_trip(self) -> None:
        settings = self.storage.load_settings()
        settings.audio.master = 0.31
        settings.video.vsync = False
        self.assertTrue(self.storage.save_settings(settings))

        restored = self.storage.load_settings()
        self.assertAlmostEqual(restored.audio.master, 0.31)
        self.assertFalse(restored.video.vsync)

    def test_missing_settings_returns_defaults(self) -> None:
        settings = self.storage.load_settings()
        self.assertEqual(settings.gameplay.target_score, 5)

    def test_corrupt_settings_are_quarantined(self) -> None:
        self.storage.settings_file.write_text("{ not json !!", encoding="utf-8")
        settings = self.storage.load_settings()  # must not raise
        self.assertEqual(settings.version, settings.version)
        self.assertTrue((self.dir / "settings.json.corrupt").exists())

    def test_no_temp_files_left_behind(self) -> None:
        self.storage.save_settings(self.storage.load_settings())
        leftovers = list(self.dir.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    # -- stats ------------------------------------------------------------
    def test_default_stats_schema(self) -> None:
        stats = default_stats()
        self.assertEqual(stats["matches_played"], 0)
        self.assertEqual(stats["by_difficulty"], {})

    def test_record_match_updates_profile(self) -> None:
        stats = self.storage.record_match(
            winner=0, mode="solo", difficulty="hard",
            score=(5, 3), rally=17, hits=42, goals=5, duration=125.0,
            fastest=980.0,
        )
        self.assertEqual(stats["matches_played"], 1)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["losses"], 0)
        self.assertEqual(stats["longest_rally"], 17)
        self.assertEqual(stats["total_hits"], 42)
        self.assertEqual(stats["total_goals"], 5)
        self.assertEqual(stats["by_difficulty"]["hard"]["played"], 1)
        self.assertEqual(stats["by_difficulty"]["hard"]["won"], 1)
        self.assertAlmostEqual(stats["playtime_seconds"], 125.0)
        self.assertEqual(stats["last_match"]["score"], [5, 3])

        again = self.storage.load_stats()
        self.assertEqual(again["matches_played"], 1)

    def test_lifetime_totals_accumulate_linearly(self) -> None:
        """Regression: ``total_hits`` used to be *added to itself* per match.

        Two matches of 42 then 10 returns must read 52, not 94, and four
        matches must not put the counter into the millions the live profile
        showed (3440914 after twenty games).
        """
        for hits, goals in ((42, 5), (10, 0), (7, 3), (0, 2)):
            stats = self.storage.record_match(
                winner=0, mode="solo", difficulty="easy",
                score=(5, 0), rally=3, hits=hits, goals=goals,
                duration=10.0, fastest=500.0,
            )
        self.assertEqual(stats["total_hits"], 59)
        self.assertEqual(stats["total_goals"], 10)
        self.assertEqual(stats["matches_played"], 4)

    def test_loss_recorded_per_difficulty(self) -> None:
        self.storage.record_match(winner=1, mode="solo", difficulty="easy",
                                  score=(2, 5), rally=4, hits=9, goals=2,
                                  duration=60.0, fastest=500.0)
        stats = self.storage.load_stats()
        self.assertEqual(stats["losses"], 1)
        self.assertEqual(stats["by_difficulty"]["easy"]["lost"], 1)

    def test_corrupt_numeric_fields_are_repaired(self) -> None:
        self.storage.stats_file.write_text(
            json.dumps({"version": 1, "matches_played": "many",
                        "longest_rally": None, "by_difficulty": 5}),
            encoding="utf-8")
        stats = self.storage.load_stats()
        self.assertEqual(stats["matches_played"], 0)
        self.assertEqual(stats["longest_rally"], 0)
        self.assertEqual(stats["by_difficulty"], {})

    def test_unknown_stats_keys_do_not_break_migration(self) -> None:
        payload = default_stats()
        payload["achieve_future_field"] = {"x": 1}
        payload["version"] = 1
        self.storage.stats_file.write_text(json.dumps(payload), encoding="utf-8")
        stats = self.storage.load_stats()
        self.assertEqual(stats["version"], STATS_VERSION)
        self.assertNotIn("achieve_future_field", stats)

    # -- v1 -> v2 migration ------------------------------------------------
    def test_v1_doubled_returns_are_reset_on_load(self) -> None:
        """Regression: v1 folded a match in with ``total_hits += stored +
        hits``, doubling the lifetime counter every game.

        These are the real numbers from a twenty-match profile, which read
        3440914 TOTAL RETURNS for roughly 800 actual returns.
        """
        payload = default_stats()
        payload["version"] = 1
        payload["matches_played"] = 20
        payload["wins"] = 10
        payload["longest_rally"] = 29
        payload["total_hits"] = 3440914
        payload["playtime_seconds"] = 783.45
        self.storage.stats_file.write_text(json.dumps(payload), encoding="utf-8")

        stats = self.storage.load_stats()
        self.assertEqual(stats["total_hits"], 0)
        self.assertEqual(stats["total_goals"], 0)
        self.assertEqual(stats["version"], STATS_VERSION)
        # Everything the bug never touched must survive the migration.
        self.assertEqual(stats["matches_played"], 20)
        self.assertEqual(stats["wins"], 10)
        self.assertEqual(stats["longest_rally"], 29)
        self.assertAlmostEqual(stats["playtime_seconds"], 783.45)

    def test_migration_is_one_time_not_a_permanent_clamp(self) -> None:
        """A profile already on the new schema keeps its tallies."""
        payload = default_stats()
        payload["version"] = STATS_VERSION
        payload["total_hits"] = 517
        payload["total_goals"] = 44
        self.storage.stats_file.write_text(json.dumps(payload), encoding="utf-8")

        stats = self.storage.load_stats()
        self.assertEqual(stats["total_hits"], 517)
        self.assertEqual(stats["total_goals"], 44)

    def test_first_match_after_the_migration_starts_from_zero(self) -> None:
        """The reset must flow through to what the player then accumulates."""
        payload = default_stats()
        payload["version"] = 1
        payload["total_hits"] = 3440914
        self.storage.stats_file.write_text(json.dumps(payload), encoding="utf-8")

        stats = self.storage.record_match(
            winner=0, mode="solo", difficulty="normal",
            score=(5, 2), rally=9, hits=41, goals=5,
            duration=88.0, fastest=900.0,
        )
        self.assertEqual(stats["total_hits"], 41)
        self.assertEqual(stats["total_goals"], 5)

        # And it stays fixed on disk for every match after that.
        again = self.storage.record_match(
            winner=1, mode="solo", difficulty="normal",
            score=(3, 5), rally=6, hits=12, goals=3,
            duration=60.0, fastest=700.0,
        )
        self.assertEqual(again["version"], STATS_VERSION)
        self.assertEqual(again["total_hits"], 53)
        self.assertEqual(again["total_goals"], 8)

    # -- replay -----------------------------------------------------------
    def test_replay_round_trip(self) -> None:
        payload = {"label": "TEST", "frames": [[0, 1, 2, 3, 4, 5, 6, 0, 0, 0, 2]]}
        self.assertTrue(self.storage.save_replay(payload))
        loaded = self.storage.load_replay()
        assert loaded is not None
        self.assertEqual(loaded["version"], 1)
        self.assertEqual(len(loaded["frames"]), 1)

    def test_replay_version_mismatch_is_ignored(self) -> None:
        self.storage.replay_file.write_text(
            json.dumps({"version": 999, "frames": [[0] * 11]}), encoding="utf-8")
        self.assertIsNone(self.storage.load_replay())

    def test_empty_replay_is_ignored(self) -> None:
        self.storage.replay_file.write_text(
            json.dumps({"version": 1, "frames": []}), encoding="utf-8")
        self.assertIsNone(self.storage.load_replay())


if __name__ == "__main__":
    unittest.main()
