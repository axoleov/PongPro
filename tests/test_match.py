"""Match rules: scoring, phases, win conditions, deuce and statistics."""

from __future__ import annotations

import unittest

from pongpro.core.constants import MatchPhase
from pongpro.core.events import EventBus, EventType
from pongpro.gameplay.match import (
    SUDDEN_DEATH_SCORE,
    Match,
    MatchConfig,
)

FAST = MatchConfig(serve_delay=0.3, goal_pause=0.3)


def make_match(**kwargs) -> tuple[Match, EventBus]:
    config = MatchConfig(serve_delay=0.3, goal_pause=0.3, **kwargs)
    bus = EventBus(history=32)
    return Match(config, bus), bus


def tick(match: Match, seconds: float, step: float = 1 / 120) -> list:
    events = []
    remaining = seconds
    while remaining > 1e-9:
        dt = min(step, remaining)
        events.extend(match.update(dt))
        remaining -= dt
    return events


class PhaseTests(unittest.TestCase):
    def test_starts_in_countdown(self) -> None:
        match, _ = make_match()
        self.assertIs(match.phase, MatchPhase.COUNTDOWN)
        self.assertGreater(match.timer, 0.0)

    def test_countdown_labels_descend(self) -> None:
        match, _ = make_match()
        labels = set()
        while match.phase is MatchPhase.COUNTDOWN:
            label = match.countdown_label()
            if label:
                labels.add(label)
            tick(match, 1 / 120)
        self.assertEqual(labels, {"3", "2", "1"})
        self.assertIs(match.phase, MatchPhase.PLAYING)

    def test_serve_events_emitted_with_counts(self) -> None:
        match, _ = make_match()
        events = tick(match, 0.5)
        serves = [e for e in events if e.type is EventType.SERVE]
        self.assertTrue(any(e.get("launch") for e in serves))
        self.assertTrue(any(e.get("countdown") is not None for e in serves))

    def test_goal_pauses_then_recountdowns(self) -> None:
        match, _ = make_match()
        tick(match, 1.0)
        match.on_goal(0, 500.0)
        self.assertIs(match.phase, MatchPhase.GOAL)
        self.assertGreater(match.hit_stop, 0.0)
        tick(match, FAST.goal_pause + 0.05)
        self.assertIs(match.phase, MatchPhase.COUNTDOWN)

    def test_hit_stop_decays(self) -> None:
        match, _ = make_match()
        match.on_goal(0, 400.0)
        self.assertGreater(match.hit_stop, 0.0)
        tick(match, 1.0)
        self.assertEqual(match.hit_stop, 0.0)


class ScoringTests(unittest.TestCase):
    def test_goal_increments_score(self) -> None:
        match, _ = make_match(target_score=21)
        match.on_goal(1, 500.0)
        self.assertEqual(match.score, [0, 1])
        self.assertEqual(match.stats.total_goals, 1)

    def test_server_alternates_after_goal(self) -> None:
        match, _ = make_match(target_score=21)
        match.on_goal(1, 500.0)
        self.assertEqual(match.server, 0)
        match.on_goal(0, 500.0)
        self.assertEqual(match.server, 1)

    def test_rally_tracking_and_statistics(self) -> None:
        match, _ = make_match(target_score=21)
        for i in range(7):
            match.on_paddle_hit(i % 2, 400.0 + i * 10)
        self.assertEqual(match.rally, 7)
        self.assertEqual(match.stats.longest_rally, 7)
        self.assertEqual(match.stats.total_hits, 7)
        self.assertAlmostEqual(match.stats.fastest_ball, 460.0)

    def test_rally_resets_after_goal(self) -> None:
        match, _ = make_match(target_score=21)
        match.on_paddle_hit(0, 500.0)
        match.on_paddle_hit(1, 500.0)
        match.on_goal(0, 500.0)
        self.assertEqual(match.rally, 0)
        self.assertEqual(match.stats.longest_rally, 2)

    def test_goal_after_match_over_is_ignored(self) -> None:
        match, _ = make_match(target_score=1)
        match.on_goal(0, 500.0)
        score = list(match.score)
        match.on_goal(1, 500.0)
        self.assertEqual(match.score, score)


class WinConditionTests(unittest.TestCase):
    def test_target_score_wins_outright(self) -> None:
        match, _ = make_match(target_score=5)
        match.score = [4, 1]
        match.on_goal(0, 500.0)
        self.assertTrue(match.match_over)
        self.assertEqual(match.winner, 0)
        self.assertIs(match.phase, MatchPhase.MATCH_OVER)

    def test_deuce_requires_two_point_lead(self) -> None:
        match, _ = make_match(target_score=5)
        match.score = [4, 4]
        match.on_goal(0, 500.0)
        self.assertFalse(match.match_over)
        self.assertEqual(match.score, [5, 4])
        match.on_goal(0, 500.0)
        self.assertTrue(match.match_over)

    def test_deuce_detection(self) -> None:
        match, _ = make_match(target_score=5)
        self.assertFalse(match.is_deuce())
        match.score = [4, 4]
        self.assertTrue(match.is_deuce())

    def test_target_one_ends_immediately(self) -> None:
        match, _ = make_match(target_score=1)
        match.on_goal(0, 500.0)
        self.assertTrue(match.match_over)

    def test_sudden_death_ceiling(self) -> None:
        match, _ = make_match(target_score=5)
        match.score = [SUDDEN_DEATH_SCORE - 1, SUDDEN_DEATH_SCORE - 1]
        match.on_goal(0, 500.0)
        self.assertTrue(match.match_over)

    def test_match_point_flag(self) -> None:
        match, _ = make_match(target_score=5)
        match.score = [4, 2]
        self.assertEqual(match.match_point_for, 0)
        match.score = [4, 4]
        self.assertIsNone(match.match_point_for)
        match.score = [5, 4]  # deuce: the leader is on match point again
        self.assertEqual(match.match_point_for, 0)
        match.score = [6, 4]
        self.assertEqual(match.match_point_for, 0)

    def test_match_point_event_emitted_once(self) -> None:
        match, _ = make_match(target_score=5)
        match.score = [4, 2]
        # Match *returns* logical events; the gameplay scene publishes them.
        events = match.on_paddle_hit(0, 500.0)
        events += match.on_paddle_hit(1, 500.0)
        announced = [e for e in events if e.type is EventType.MATCH_POINT]
        self.assertEqual(len(announced), 1)
        self.assertEqual(announced[0].get("player"), 0)

    def test_match_end_emitted(self) -> None:
        match, _ = make_match(target_score=3)
        events = match.on_goal(1, 500.0)
        self.assertFalse(any(e.type is EventType.MATCH_END for e in events))
        match.score = [1, 2]
        events = match.on_goal(1, 500.0)
        self.assertTrue(any(e.type is EventType.MATCH_END for e in events))

    def test_score_string_and_clock(self) -> None:
        match, _ = make_match(target_score=5)
        match.score = [3, 2]
        self.assertEqual(match.score_string(), "3 - 2")
        tick(match, FAST.serve_delay + 0.05)  # run out the serve countdown
        self.assertIs(match.phase, MatchPhase.PLAYING)
        match.stats.duration = 0.0  # clock only counts active play
        tick(match, 2.0)
        self.assertAlmostEqual(match.stats.duration, 2.0, delta=0.02)
        self.assertEqual(match.time_label(), "00:02")


class ConfigTests(unittest.TestCase):
    def test_build_config_helper(self) -> None:
        from pongpro.core.constants import Difficulty, GameMode
        from pongpro.gameplay.match import build_config

        config = build_config(GameMode.SOLO, Difficulty.ELITE, 7, True, False)
        self.assertEqual(config.target_score, 7)
        self.assertEqual(config.difficulty, Difficulty.ELITE)
        self.assertFalse(config.english)


if __name__ == "__main__":
    unittest.main()
