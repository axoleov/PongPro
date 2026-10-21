"""FOCUS mode: life budget, the life orb, and how a run differs from a duel.

FOCUS is the one mode that is not a contest, so almost every rule it has is
the *absence* of a rule the other three share.  That makes it easy to break
silently - nothing else exercises the "no winner" path through the match, the
results screen or the profile - so this file pins down each of those absences
explicitly rather than by inference:

* a run has a life budget instead of a score, and spends it one at a time;
* the only pickup is the life orb, which is never bought, never owned and
  never listed in the shop;
* the orb repairs up to the run's *own* starting count, so "First to N" is
  always exactly N lives;
* ball speed recovers only part-way, and never below the base serve;
* conceding emits no winner at all, so the profile's win rate cannot drift.

Everything here is headless: no surfaces, no audio device, no profile on disk.
"""

from __future__ import annotations

import unittest

from pongpro.core.constants import (
    BASE_BALL_SPEED,
    FOCUS_LIFE_BONUS,
    FOCUS_LIFE_FIRST_DELAY,
    FOCUS_LIFE_GAP_MAX,
    FOCUS_LIFE_GAP_MIN,
    FOCUS_SERVE_DELAY,
    FOCUS_SPEED_RECOVERY,
    MAX_BALL_SPEED,
    Color,
    GameMode,
    MatchPhase,
)
from pongpro.core.events import EventBus, EventType
from pongpro.core.rng import Rng
from pongpro.economy.catalog import ITEMS_BY_ID, PowerEffect, ShopCategory, items_in
from pongpro.gameplay.bubbles import (
    RESPAWN_GAP_MAX,
    RESPAWN_GAP_MIN,
    FIRST_SPAWN_DELAY,
    BubbleField,
)
from pongpro.gameplay.entities import Ball, default_court
from pongpro.gameplay.focus import LIFE_ORB, FocusRun, life_orb_field
from pongpro.gameplay.match import Match, MatchConfig

STEP = 1.0 / 120.0


def make_match(**kwargs) -> tuple[Match, EventBus]:
    config = MatchConfig(serve_delay=0.3, goal_pause=0.3, **kwargs)
    bus = EventBus(history=32)
    return Match(config, bus), bus


def tick(match: Match, seconds: float) -> list:
    events = []
    remaining = seconds
    while remaining > 1e-9:
        dt = min(STEP, remaining)
        events.extend(match.update(dt))
        remaining -= dt
    return events


def play(match: Match) -> None:
    """Advance to PLAYING so a goal/concession is legal."""
    while match.phase is not MatchPhase.PLAYING and match.phase is not MatchPhase.MATCH_OVER:
        tick(match, STEP)
        if match.match_over:
            return


# ---------------------------------------------------------------------------
# Life budget
# ---------------------------------------------------------------------------
class FocusRunTests(unittest.TestCase):
    def test_starts_with_the_chosen_budget(self) -> None:
        run = FocusRun(lives=7, max_lives=7)
        self.assertEqual(run.lives, 7)
        self.assertEqual(run.max_lives, 7)
        self.assertEqual(run.lost, 0)
        # A fresh run is already at its cap, so the first orb would pay coins.
        self.assertTrue(run.full)
        self.assertFalse(run.last_life)

    def test_a_budget_below_one_is_clamped(self) -> None:
        """"First to 1" is the degenerate case and must still be playable."""
        run = FocusRun(lives=0, max_lives=0)
        self.assertEqual(run.lives, 1)
        self.assertEqual(run.max_lives, 1)
        self.assertTrue(run.last_life)

    def test_cap_cannot_start_below_the_budget(self) -> None:
        run = FocusRun(lives=5, max_lives=3)
        self.assertEqual(run.max_lives, 5)

    def test_each_concession_spends_exactly_one_life(self) -> None:
        run = FocusRun(lives=3, max_lives=3)
        self.assertFalse(run.concede())
        self.assertEqual(run.lives, 2)
        self.assertEqual(run.lost, 1)
        self.assertFalse(run.concede())
        self.assertTrue(run.concede())
        self.assertEqual(run.lives, 0)
        self.assertEqual(run.lost, 3)

    def test_last_life_warns_before_the_run_ends(self) -> None:
        run = FocusRun(lives=2, max_lives=2)
        run.concede()
        self.assertTrue(run.last_life)

    def test_the_run_ends_at_zero_and_never_below(self) -> None:
        run = FocusRun(lives=1, max_lives=1)
        self.assertTrue(run.concede())
        self.assertEqual(run.lives, 0)
        # A stray second call must not drive the counter negative.
        run.concede()
        self.assertEqual(run.lives, 0)

    def test_a_restore_repairs_one_life(self) -> None:
        run = FocusRun(lives=2, max_lives=5)
        self.assertTrue(run.restore())
        self.assertEqual(run.lives, 3)
        self.assertFalse(run.full)
        self.assertFalse(run.last_life)

    def test_a_restore_stops_at_the_run_own_cap(self) -> None:
        """An orb is a repair, never an extra credit.

        Whatever the player picked in the menu is the whole budget; letting
        orbs push the cap up would make "First to 5" mean something else by
        minute four.
        """
        run = FocusRun(lives=4, max_lives=5)
        self.assertTrue(run.restore())
        self.assertEqual(run.lives, 5)
        self.assertTrue(run.full)
        self.assertFalse(run.restore(), "an orb at full health must not stack")
        self.assertEqual(run.lives, 5)
        self.assertEqual(run.lost, 0, "a refused restore is not a concession")

    def test_a_finished_run_cannot_be_revived(self) -> None:
        """A run at zero lives is over; an orb must not bring it back.

        The match has already transitioned to MATCH_OVER, so a revive would
        describe a state the phase machine has left behind.
        """
        run = FocusRun(lives=1, max_lives=1)
        self.assertTrue(run.concede())
        self.assertEqual(run.lives, 0)
        self.assertFalse(run.restore())
        self.assertEqual(run.lives, 0)


# ---------------------------------------------------------------------------
# Ball-speed recovery
# ---------------------------------------------------------------------------
class SpeedRecoveryTests(unittest.TestCase):
    def test_recovery_is_the_configured_fraction(self) -> None:
        run = FocusRun(lives=3, max_lives=3)
        self.assertAlmostEqual(run.recovered_speed(1000.0),
                               1000.0 * FOCUS_SPEED_RECOVERY)

    def test_recovery_never_drops_below_the_base_serve(self) -> None:
        """Conceding three seconds in must not make the next life easier.

        A run that opens at BASE_BALL_SPEED and immediately concedes would
        otherwise re-serve *slower* than its own first serve, rewarding the
        mistake.
        """
        run = FocusRun(lives=3, max_lives=3)
        self.assertEqual(run.recovered_speed(BASE_BALL_SPEED), BASE_BALL_SPEED)
        self.assertEqual(run.recovered_speed(1.0), BASE_BALL_SPEED)

    def test_a_fast_ball_stays_harder_after_recovery(self) -> None:
        run = FocusRun(lives=3, max_lives=3)
        recovered = run.recovered_speed(900.0)
        self.assertGreater(recovered, BASE_BALL_SPEED)
        self.assertLess(recovered, 900.0)
        self.assertLess(recovered, MAX_BALL_SPEED)

    def test_recovery_is_monotonic_in_the_incoming_speed(self) -> None:
        run = FocusRun(lives=3, max_lives=3)
        slow = run.recovered_speed(600.0)
        fast = run.recovered_speed(1200.0)
        self.assertGreater(fast, slow)


# ---------------------------------------------------------------------------
# The life orb: the one pickup that is never sold
# ---------------------------------------------------------------------------
class LifeOrbTests(unittest.TestCase):
    def test_the_orb_is_not_in_the_buyable_catalog(self) -> None:
        """It must be impossible to own, equip or browse this powerup.

        The shop is documented as "every buyable item"; keeping the orb out
        of ``ITEMS_BY_ID`` is what stops a profile from ever holding one, and
        it is why FOCUS needs no shop filtering.
        """
        self.assertNotIn(LIFE_ORB.id, ITEMS_BY_ID)
        self.assertNotIn(LIFE_ORB, items_in(ShopCategory.POWERUP))

    def test_the_orb_still_declares_a_recognisable_effect(self) -> None:
        """The enum member is what the scene matches on at collection time."""
        self.assertIs(LIFE_ORB.data.effect, PowerEffect.LIFE)

    def test_the_orb_is_free_and_legendary(self) -> None:
        self.assertEqual(LIFE_ORB.price, 0)
        self.assertEqual(LIFE_ORB.category, ShopCategory.POWERUP)

    def test_the_orb_carries_a_two_glyph_hud_label(self) -> None:
        """The HUD pill reserves exactly two glyphs, same as every powerup."""
        self.assertEqual(len(LIFE_ORB.data.glyph), 2)
        self.assertTrue(LIFE_ORB.data.glyph.strip())
        self.assertEqual(LIFE_ORB.data.accent, Color.GOLD)

    def test_the_field_offers_only_the_orb(self) -> None:
        field = life_orb_field(default_court(), Rng(5))
        self.assertIsInstance(field, BubbleField)
        pool = getattr(field, "_pool", ())
        self.assertEqual(tuple(pool), (LIFE_ORB,))


# ---------------------------------------------------------------------------
# Pickup cadence
# ---------------------------------------------------------------------------
class OrbCadenceTests(unittest.TestCase):
    def _field(self) -> BubbleField:
        return life_orb_field(default_court(), Rng(11))

    def _advance(self, field: BubbleField, seconds: float) -> None:
        for _ in range(int(round(seconds / STEP))):
            field.update(STEP, playing=True)

    def test_no_orb_during_the_opening(self) -> None:
        """The player has to survive long enough for it to be a reward."""
        field = self._field()
        self._advance(field, FOCUS_LIFE_FIRST_DELAY - 1.0)
        self.assertIsNone(field.bubble)

    def test_the_first_orb_arrives_after_the_first_delay(self) -> None:
        field = self._field()
        self._advance(field, FOCUS_LIFE_FIRST_DELAY + 0.5)
        self.assertIsNotNone(field.bubble)

    def test_gaps_are_rare_and_bounded(self) -> None:
        field = self._field()
        self._advance(field, FOCUS_LIFE_FIRST_DELAY + 0.5)
        assert field.bubble is not None
        field.bubble.life = 0.0
        field.collect(None, None)
        # The orb is a *pickup*; if it simply expires, a fresh one follows
        # after the configured gap rather than instantly.
        gap = getattr(field, "_gap_min", None)
        span = getattr(field, "_gap_span", None)
        self.assertIsNotNone(gap)
        self.assertIsNotNone(span)
        self.assertGreaterEqual(gap, FOCUS_LIFE_GAP_MIN - 1e-9)
        self.assertLessEqual(gap + span, FOCUS_LIFE_GAP_MAX + 1e-9)

    def test_the_orb_field_is_far_slower_than_a_duel_field(self) -> None:
        """A duel's pickups are a fight; FOCUS's are an errand."""
        duel = BubbleField((), default_court(), Rng(1))
        focus = self._field()
        self.assertGreater(getattr(focus, "_gap_min"),
                           getattr(duel, "_gap_min"))
        self.assertGreater(getattr(focus, "_first_delay"),
                           FIRST_SPAWN_DELAY)
        self.assertGreater(getattr(duel, "_gap_min"), RESPAWN_GAP_MIN - 1e-9)
        self.assertLessEqual(getattr(duel, "_gap_min"),
                             RESPAWN_GAP_MAX + 1e-9)


# ---------------------------------------------------------------------------
# Match: no score, no winner, just lives
# ---------------------------------------------------------------------------
class FocusMatchTests(unittest.TestCase):
    def test_a_focus_match_is_built_with_the_life_budget(self) -> None:
        match, _ = make_match(mode=GameMode.FOCUS, target_score=5)
        self.assertIsNotNone(match.focus)
        assert match.focus is not None
        self.assertEqual(match.focus.lives, 5)
        self.assertEqual(match.focus.max_lives, 5)
        self.assertEqual(match.stats.lives_left, 5)

    def test_a_duel_has_no_life_budget(self) -> None:
        match, _ = make_match(mode=GameMode.SOLO, target_score=5)
        self.assertIsNone(match.focus)
        self.assertEqual(match.stats.lives_left, 0)

    def test_the_opener_uses_the_configured_countdown(self) -> None:
        """The first countdown teaches the keys, so it keeps the normal beat.

        Only the *recovery* countdown after a lost life is shortened - which
        ``test_the_recovery_countdown_is_the_shorter_one`` contrasts directly.
        """
        match, _ = make_match(mode=GameMode.FOCUS, target_score=5)
        self.assertAlmostEqual(match.timer, match.config.serve_delay)
        self.assertIs(match.phase, MatchPhase.COUNTDOWN)

    def test_a_concession_spends_a_life_without_scoring(self) -> None:
        match, _ = make_match(mode=GameMode.FOCUS, target_score=5)
        play(match)
        events = match.on_concede(0, 500.0, serve_side=1)
        self.assertEqual(match.score, [0, 0], "a run has no score")
        self.assertEqual(match.focus.lives, 4)
        self.assertEqual(match.stats.lives_left, 4)
        self.assertEqual(match.stats.total_goals, 1)
        self.assertEqual(len(events), 1)

    def test_a_concession_records_the_failing_side_not_a_scorer(self) -> None:
        """The GOAL payload carries both names for the one failing paddle."""
        match, _ = make_match(mode=GameMode.FOCUS, target_score=5)
        play(match)
        events = match.on_concede(1, 600.0, serve_side=0)
        goal = next(e for e in events if e.type is EventType.GOAL)
        self.assertEqual(goal.get("side"), 1)
        self.assertEqual(goal.get("scorer"), 1)
        self.assertEqual(match.last_scorer, 1)

    def test_the_serve_direction_is_honoured(self) -> None:
        match, _ = make_match(mode=GameMode.FOCUS, target_score=5)
        play(match)
        match.on_concede(0, 500.0, serve_side=1)
        self.assertEqual(match.server, 1)
        self.assertIs(match.phase, MatchPhase.GOAL)

    def test_the_recovery_countdown_is_the_shorter_one(self) -> None:
        match, _ = make_match(mode=GameMode.FOCUS, target_score=5)
        play(match)
        match.on_concede(0, 500.0, serve_side=1)
        tick(match, match.config.goal_pause + STEP)
        self.assertIs(match.phase, MatchPhase.COUNTDOWN)
        # One step of overshoot from the fixed-step tick above.
        self.assertAlmostEqual(match.timer, FOCUS_SERVE_DELAY, delta=STEP * 2)

    def test_the_last_life_is_announced(self) -> None:
        match, _ = make_match(mode=GameMode.FOCUS, target_score=2)
        play(match)
        match.on_concede(0, 500.0, serve_side=1)
        self.assertEqual(match.banner, "LAST LIFE")
        self.assertTrue(match.focus.last_life)

    def test_a_mid_run_concession_announces_life_lost(self) -> None:
        match, _ = make_match(mode=GameMode.FOCUS, target_score=5)
        play(match)
        match.on_concede(0, 500.0, serve_side=1)
        self.assertEqual(match.banner, "LIFE LOST")

    def test_the_final_concession_ends_the_run_without_a_winner(self) -> None:
        """The single most important FOCUS invariant.

        ``winner`` staying None is what stops the profile's win rate drifting
        and what tells the results screen to headline a *run* rather than a
        victory or a defeat.
        """
        match, bus = make_match(mode=GameMode.FOCUS, target_score=2)
        play(match)
        match.on_concede(0, 500.0, serve_side=1)
        tick(match, match.config.goal_pause + STEP)
        play(match)
        events = match.on_concede(1, 700.0, serve_side=0)

        self.assertTrue(match.match_over)
        self.assertIsNone(match.winner)
        self.assertIs(match.phase, MatchPhase.MATCH_OVER)
        self.assertEqual(match.focus.lives, 0)
        self.assertEqual(match.stats.lives_left, 0)

    def test_the_final_concession_reports_no_winner(self) -> None:
        match, _ = make_match(mode=GameMode.FOCUS, target_score=1)
        play(match)
        events = match.on_concede(0, 500.0, serve_side=1)
        ended = next(e for e in events if e.type is EventType.MATCH_END)
        self.assertIsNone(ended.get("winner"))
        self.assertEqual(ended.get("score"), (0, 0), "a run never scores")

    def test_the_running_banner_is_run_over(self) -> None:
        match, _ = make_match(mode=GameMode.FOCUS, target_score=1)
        play(match)
        match.on_concede(0, 500.0, serve_side=1)
        # After the short goal banner expires the strip must still say
        # something, or the final seconds before the results go blank.
        match._banner_timer = 0.0
        self.assertEqual(match.banner, "RUN OVER")

    def test_an_extra_concession_after_the_run_ends_is_ignored(self) -> None:
        """A stray call must never double-spend a life or re-fire MATCH_END."""
        match, _ = make_match(mode=GameMode.FOCUS, target_score=1)
        play(match)
        match.on_concede(0, 500.0, serve_side=1)
        self.assertTrue(match.match_over)
        self.assertEqual(match.on_concede(1, 500.0, serve_side=0), [])
        self.assertEqual(match.focus.lost, 1)
        self.assertEqual(match.stats.total_goals, 1)

    def test_a_duel_concession_is_not_accepted(self) -> None:
        match, _ = make_match(mode=GameMode.SOLO, target_score=5)
        play(match)
        self.assertEqual(match.on_concede(0, 500.0, serve_side=1), [])
        self.assertEqual(match.score, [0, 0])

    def test_an_out_of_range_side_is_rejected(self) -> None:
        match, _ = make_match(mode=GameMode.FOCUS, target_score=5)
        play(match)
        self.assertEqual(match.on_concede(7, 500.0, serve_side=0), [])
        self.assertEqual(match.focus.lives, 5)

    def test_returns_still_count_towards_the_lifetime_tally(self) -> None:
        """A run has no score, so returns are the only thing it accumulates."""
        match, _ = make_match(mode=GameMode.FOCUS, target_score=5)
        play(match)
        match.on_paddle_hit(0, 500.0)
        match.on_paddle_hit(1, 520.0)
        self.assertEqual(match.stats.total_hits, 2)
        self.assertEqual(match.rally, 2)
        match.on_concede(0, 520.0, serve_side=1)
        self.assertEqual(match.stats.total_hits, 2, "the rally is banked")


# ---------------------------------------------------------------------------
# Ball physics: the re-serve must honour the recovered speed
# ---------------------------------------------------------------------------
class FocusServeTests(unittest.TestCase):
    def test_a_focus_match_reports_its_mode(self) -> None:
        match, _ = make_match(mode=GameMode.FOCUS, target_score=5)
        self.assertIs(match.config.mode, GameMode.FOCUS)

    def test_the_recovered_speed_is_what_the_next_serve_needs(self) -> None:
        """The scene parks the recovered figure for exactly one serve.

        ``Match`` never launches the ball itself, so the contract between the
        two is that the run's recovery is what the scene will hand to
        ``Ball.set_direction`` - asserted here against a real ball.
        """
        match, _ = make_match(mode=GameMode.FOCUS, target_score=5)
        play(match)
        ball = Ball(default_court())
        ball.set_direction(800.0, 0.3)
        self.assertGreater(ball.speed, 0.0)

        recovered = match.focus.recovered_speed(ball.speed)
        self.assertAlmostEqual(recovered, 800.0 * FOCUS_SPEED_RECOVERY)

        ball.set_direction(recovered, 0.3)
        self.assertAlmostEqual(ball.speed, recovered)
        self.assertGreaterEqual(ball.speed, BASE_BALL_SPEED)


if __name__ == "__main__":
    unittest.main()
