"""AI: preset ordering, bounded behaviour, prediction accuracy, determinism.

``BehaviourTests`` measures the thing a player actually feels - how often the
AI lets the ball past - by running full physics (walls, swept paddle contact,
deflection, rally speed-up) rather than asserting on the tuning table.
"""

from __future__ import annotations

import dataclasses
import math
import unittest

from pongpro.core.constants import (
    BASE_BALL_SPEED,
    Difficulty,
    PADDLE_H,
    PADDLE_SPEED,
)
from pongpro.core.rng import Rng
from pongpro.gameplay.ai import PRESETS, AIController, AIPreset
from pongpro.gameplay.entities import Ball, Paddle, default_court
from pongpro.gameplay.physics import (
    next_paddle_speed,
    predict_intercept_y,
    resolve_walls,
    try_paddle_contact,
)


def make_ball(x: float, y: float, vx: float, vy: float) -> Ball:
    court = default_court()
    ball = Ball(court)
    ball.x, ball.y, ball.vx, ball.vy = x, y, vx, vy
    ball.active = True
    return ball


class PresetTests(unittest.TestCase):
    def test_every_difficulty_has_a_preset(self) -> None:
        for difficulty in Difficulty:
            self.assertIn(difficulty, PRESETS)

    def test_harder_means_faster_and_more_accurate(self) -> None:
        order = [Difficulty.EASY, Difficulty.NORMAL, Difficulty.HARD,
                 Difficulty.ELITE]
        presets = [PRESETS[d] for d in order]
        for slower, faster in zip(presets, presets[1:]):
            self.assertLess(slower.max_speed, faster.max_speed)
            self.assertGreater(slower.reaction, faster.reaction)
            self.assertGreater(slower.aim_error, faster.aim_error)
            self.assertGreater(slower.whiff_chance, faster.whiff_chance)

    def test_elite_reaches_the_player_speed_ceiling(self) -> None:
        """ELITE must actually *use* every px/s the player has.

        ``AIController.update`` emits an axis that is clamped to +/-1 and
        ``Paddle.update`` turns that back into ``axis * PADDLE_SPEED``, so a
        preset claiming more than ``PADDLE_SPEED`` silently ran at
        ``PADDLE_SPEED``.  The old 720 px/s entry was unreachable, and the
        test that guarded it only read the table rather than the paddle.
        """
        court = default_court()
        for difficulty in Difficulty:
            self.assertLessEqual(PRESETS[difficulty].max_speed, PADDLE_SPEED)

        ai = AIController(Paddle(False, court),
                          PRESETS[Difficulty.ELITE], Rng(4))
        ai.paddle.y = court.center_y
        # Ball parked in the top corner: ~285 px of travel for the mallet.
        ball = make_ball(court.center_x, court.top + 60.0, 900.0, 0.0)
        fastest = 0.0
        for _ in range(240):
            axis = ai.update(1 / 120, ball, court)
            ai.paddle.update(axis, 1 / 120, court)
            fastest = max(fastest, abs(ai.paddle.vel))
        self.assertGreater(fastest, PADDLE_SPEED * 0.95)


class AIControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.court = default_court()

    def _controller(self, difficulty: Difficulty, seed: int = 7,
                    left: bool = False) -> AIController:
        paddle = Paddle(left, self.court)
        return AIController(paddle, PRESETS[difficulty], Rng(seed))

    def test_axis_always_bounded(self) -> None:
        for difficulty in Difficulty:
            ai = self._controller(difficulty)
            ball = make_ball(900.0, 100.0, -500.0, 400.0)
            for step in range(240):
                axis = ai.update(1 / 120, ball, self.court)
                self.assertGreaterEqual(axis, -1.0)
                self.assertLessEqual(axis, 1.0)
                ai.paddle.update(axis, 1 / 120, self.court)

    def test_target_stays_inside_the_court(self) -> None:
        for difficulty in Difficulty:
            ai = self._controller(difficulty, seed=3)
            ball = make_ball(1000.0, 60.0, -400.0, -1200.0)
            for _ in range(300):
                ai.update(1 / 120, ball, self.court)
                half = PADDLE_H / 2
                self.assertGreaterEqual(ai.target_y, self.court.top + half - 1.0)
                self.assertLessEqual(ai.target_y, self.court.bottom - half + 1.0)

    def test_elite_predicts_intercept_tightly(self) -> None:
        """Elite AI should end up near the true crossing point."""
        ai = self._controller(Difficulty.ELITE, seed=11, left=False)
        ball = make_ball(200.0, 300.0, 430.0, 120.0)
        true_intercept = predict_intercept_y(
            ball.x, ball.y, ball.vx, ball.vy, ball.r, ai._court_line(),
            self.court)
        assert true_intercept is not None

        for _ in range(120):  # one full second of observation
            ai.update(1 / 120, ball, self.court)

        # Compare the *committed target* against the true intercept.
        self.assertLess(abs(ai.target_y - true_intercept),
                        PRESETS[Difficulty.ELITE].aim_error * 3.0)
        self.assertIsNotNone(ai.last_prediction)

    def test_easy_ai_is_sloppier_than_elite(self) -> None:
        easy = self._controller(Difficulty.EASY, seed=5)
        elite = self._controller(Difficulty.ELITE, seed=5)
        ball = make_ball(200.0, 250.0, 430.0, -150.0)
        for _ in range(120):
            easy.update(1 / 120, ball, self.court)
            elite.update(1 / 120, ball, self.court)
        truth = predict_intercept_y(ball.x, ball.y, ball.vx, ball.vy, ball.r,
                                    elite._court_line(), self.court)
        assert truth is not None
        easy_error = abs(easy.target_y - truth)
        elite_error = abs(elite.target_y - truth)
        self.assertLess(elite_error, easy_error)

    def test_ai_drifts_home_when_ball_leaves(self) -> None:
        ai = self._controller(Difficulty.HARD, seed=2)
        ball = make_ball(300.0, 100.0, -430.0, 0.0)  # travelling away (right AI)
        for _ in range(300):
            ai.update(1 / 120, ball, self.court)
        self.assertAlmostEqual(ai.target_y, self.court.center_y, delta=120.0)

    def test_parked_ball_goes_home(self) -> None:
        ai = self._controller(Difficulty.NORMAL, seed=4)
        ball = make_ball(self.court.center_x, self.court.center_y, 0.0, 0.0)
        ball.active = False
        for _ in range(60):
            ai.update(1 / 120, ball, self.court)
        self.assertAlmostEqual(ai.target_y, self.court.center_y, delta=140.0)

    def test_same_seed_is_deterministic(self) -> None:
        first, second = self._controller(Difficulty.HARD, seed=99), \
            self._controller(Difficulty.HARD, seed=99)
        ball = make_ball(1000.0, 120.0, -520.0, 380.0)
        for _ in range(200):
            a = first.update(1 / 120, ball, self.court)
            b = second.update(1 / 120, ball, self.court)
            self.assertEqual(a, b)
            first.paddle.update(a, 1 / 120, self.court)
            second.paddle.update(b, 1 / 120, self.court)

    def test_different_seed_diverges(self) -> None:
        a = self._controller(Difficulty.HARD, seed=1)
        b = self._controller(Difficulty.HARD, seed=2)
        ball = make_ball(1000.0, 120.0, -520.0, 380.0)
        axes_a, axes_b = [], []
        for _ in range(200):
            axes_a.append(a.update(1 / 120, ball, self.court))
            axes_b.append(b.update(1 / 120, ball, self.court))
            a.paddle.update(axes_a[-1], 1 / 120, self.court)
            b.paddle.update(axes_b[-1], 1 / 120, self.court)
        self.assertNotEqual(axes_a, axes_b)

    def test_snapshots_round_trip(self) -> None:
        ai = self._controller(Difficulty.HARD, seed=8)
        ball = make_ball(900.0, 200.0, -500.0, 200.0)
        for _ in range(30):
            ai.update(1 / 120, ball, self.court)
        snap = ai.snapshot()
        before = ai.target_y
        ai.restore(snap)
        self.assertEqual(ai.target_y, before)

    def test_speed_cap_respected(self) -> None:
        ai = self._controller(Difficulty.EASY, seed=6)
        ai.paddle.y = self.court.top + 60
        ball = make_ball(1000.0, self.court.bottom - 60, -400.0, 0.0)
        cap = PRESETS[Difficulty.EASY].max_speed
        for _ in range(60):
            axis = ai.update(1 / 120, ball, self.court)
            ai.paddle.update(axis, 1 / 120, self.court)
            self.assertLessEqual(abs(ai.paddle.vel), cap + 1.0)


# -- measured behaviour ---------------------------------------------------
DT = 1.0 / 120.0
RALLY_CAP = 12.0  # seconds; long enough for the speed-up to reach the cap

# A partner that cannot miss, so every rally is a fresh test of the subject.
PERFECT = AIPreset(
    difficulty=Difficulty.ELITE, max_speed=4000.0, reaction=0.0,
    aim_error=0.0, whiff_chance=0.0, home_error=0.0, deadzone=0.5,
    gain=50.0, sway=0.0,
)


def return_rate(preset: AIPreset, *, seed: int = 11, rallies: int = 30) -> float:
    """Fraction of arrivals at the subject's line that the subject returned.

    Full physics - wall bounces, swept paddle contact, deflection and the
    rally speed-up - because a unit test on the tuning table cannot tell you
    whether the AI actually gets in the way of the ball.
    """
    court = default_court()
    subject = AIController(Paddle(True, court), preset, Rng(seed))
    partner = AIController(Paddle(False, court), PERFECT, Rng(seed + 1))
    ball = Ball(court)
    rally_rng = Rng(seed + 500)

    returns = misses = 0
    for _ in range(rallies):
        subject.paddle.y = partner.paddle.y = court.center_y
        subject.paddle.vel = partner.paddle.vel = 0.0
        ball.park(court, court.center_x, court.center_y)
        ball.active = True
        angle = rally_rng.uniform(0.10, 0.55)
        ball.vx = -BASE_BALL_SPEED * math.cos(angle)
        ball.vy = BASE_BALL_SPEED * math.sin(angle) * rally_rng.sign()

        rally = 0
        for _ in range(int(RALLY_CAP / DT)):
            subject.paddle.update(subject.update(DT, ball, court), DT, court)
            partner.paddle.update(partner.update(DT, ball, court), DT, court)
            ball.begin_step()
            ball.integrate(DT)
            resolve_walls(ball, court)

            speed = next_paddle_speed(ball.speed, rally, True)
            if try_paddle_contact(ball, subject.paddle, speed, english=True):
                rally += 1
                returns += 1
            elif try_paddle_contact(ball, partner.paddle, speed, english=True):
                rally += 1
            elif ball.x + ball.r < court.left:
                misses += 1
                break
            elif ball.x - ball.r > court.right:
                break  # the perfect partner erred; not the subject's problem

    total = returns + misses
    return returns / total if total else 1.0


class ReturnRateTests(unittest.TestCase):
    """Measured, per difficulty: does the AI let the ball past?"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rates = {d: return_rate(PRESETS[d]) for d in Difficulty}

    def test_harder_plays_strictly_better(self) -> None:
        order = [Difficulty.EASY, Difficulty.NORMAL, Difficulty.HARD,
                 Difficulty.ELITE]
        rates = [self.rates[d] for d in order]
        for weaker, stronger in zip(rates, rates[1:]):
            self.assertLess(weaker, stronger,
                            f"return rates not ordered: {rates}")

    def test_each_difficulty_plays_at_its_label(self) -> None:
        # Floors: no difficulty may go back to watching balls go by.
        self.assertGreaterEqual(self.rates[Difficulty.EASY], 0.62)
        self.assertGreaterEqual(self.rates[Difficulty.NORMAL], 0.82)
        self.assertGreaterEqual(self.rates[Difficulty.HARD], 0.92)
        self.assertGreaterEqual(self.rates[Difficulty.ELITE], 0.96)
        # Ceiling: EASY must stay beatable, or the ladder has collapsed.
        self.assertLessEqual(self.rates[Difficulty.EASY], 0.90)

    def test_results_are_reported_for_the_record(self) -> None:
        # Keeps the measured ladder visible in test output when it drifts.
        for difficulty in Difficulty:
            self.assertGreaterEqual(self.rates[difficulty], 0.0)
            self.assertLessEqual(self.rates[difficulty], 1.0)


class SteeringTests(unittest.TestCase):
    """The control law itself: it must *arrive*, not creep to a stop."""

    @staticmethod
    def _quiet(difficulty: Difficulty, court) -> AIController:
        """Same controller with the perceptual wobble dialled out."""
        preset = dataclasses.replace(
            PRESETS[difficulty], aim_error=0.0, whiff_chance=0.0,
            home_error=0.0, sway=0.0, reaction=0.0)
        return AIController(Paddle(False, court), preset, Rng(5))

    def test_does_not_creep_in_the_final_approach(self) -> None:
        """Regression: easing from ``deadzone * 4`` at a 0.35 floor worked out
        at ~23 px/s inside 50 px, so the mallet parked short of the ball and
        looked like it was not even trying."""
        court = default_court()
        incoming = make_ball(court.center_x, court.top + 60.0, 900.0, 0.0)
        for difficulty in Difficulty:
            ai = self._quiet(difficulty, court)
            ai.paddle.y = court.center_y
            ai.update(DT, incoming, court)

            # Park the mallet just outside the stop band and read the command.
            ai.paddle.y = ai.target_y + PRESETS[difficulty].deadzone * 1.25
            axis = ai.update(DT, incoming, court)

            preset = ai.preset
            commanded = abs(axis) * PADDLE_SPEED
            expected = min(preset.max_speed,
                           preset.deadzone * 1.25 * preset.gain)
            self.assertGreater(
                commanded, expected * 0.6,
                f"{difficulty.value} crept: {commanded:.0f} px/s commanded "
                f"of the {expected:.0f} px/s the error asks for")

    def test_first_read_of_an_incoming_ball_always_lands(self) -> None:
        """A whiff may cost one observation interval, never the whole approach.

        The stale target the bot falls back on after the ball flips onto its
        side is *home* - skipping that first read is a paddle parked at centre
        watching the ball arrive.
        """
        court = default_court()
        incoming = make_ball(court.center_x, court.top + 60.0, 900.0, 0.0)
        for difficulty in Difficulty:
            for seed in range(16):
                ai = AIController(Paddle(False, court),
                                  PRESETS[difficulty], Rng(seed))
                ai.reset(court)  # no read in hand, as after a change of ends
                ai.update(DT, incoming, court)
                self.assertIsNotNone(
                    ai.last_prediction,
                    f"{difficulty.value} ignored an incoming ball (seed "
                    f"{seed})")


if __name__ == "__main__":
    unittest.main()
