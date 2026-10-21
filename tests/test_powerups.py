"""Powerup runtime: cooldowns, targeting and the idempotence promise.

The design contract documented in :mod:`pongpro.gameplay.powerups` is that a
match shares **one** powerup spec and every modifier is therefore idempotent -
a giant paddle is either giant or it is not.  The tests below are that promise
written down: re-firing must produce the same scale, an opponent-targeted
effect must never touch the firer, and a ``pu.none`` loadout must make the
whole subsystem a no-op rather than a source of 1.0x multiplications.

Time is stepped in the game's own 120 Hz fixed step, and every "the effect has
expired" assertion allows a couple of steps of slack: subtracting ``1/120``
repeatedly cannot land on exactly zero in IEEE-754, so demanding an exact
``0.0`` would be testing floating point rather than the game.
"""

from __future__ import annotations

import math
import unittest

from pongpro.core.rng import Rng
from pongpro.economy.catalog import get_item
from pongpro.gameplay.entities import Ball, Paddle, default_court
from pongpro.gameplay.powerups import (
    AI_MAX_DELAY,
    AI_MIN_DELAY,
    MAGNET_DEADZONE,
    MAGNET_GAIN,
    MAGNET_MAX_VY,
    MAGNET_STRENGTH,
    PowerupSystem,
    apply_magnet,
)

#: One fixed simulation step, matching the game's 120 Hz physics rate.
DT = 1.0 / 120.0


def _spec(item_id: str):
    return get_item(item_id).data


def _advance(system: PowerupSystem, seconds: float) -> None:
    """Tick ``system`` for *at least* ``seconds``.

    The extra step makes "the window is closed" assertions deterministic:
    ``6.0 - 720 * (1/120)`` can be a denormal residue instead of zero.
    """
    for _ in range(math.ceil(seconds / DT) + 1):
        system.tick(DT)


class _World:
    """A minimal court with one paddle per side, built once for the tests."""

    def __init__(self) -> None:
        self.court = default_court()
        self.left = Paddle(True, self.court)
        self.right = Paddle(False, self.court)
        self.left.reset(self.court)
        self.right.reset(self.court)
        self.ball = Ball(self.court)


class DisabledPowerupTests(unittest.TestCase):
    """``pu.none`` must switch the subsystem off, not merely mute it."""

    def test_system_is_disabled(self) -> None:
        self.assertFalse(PowerupSystem(_spec("pu.none")).enabled)

    def test_cannot_be_fired(self) -> None:
        system = PowerupSystem(_spec("pu.none"))
        self.assertFalse(system.ready(0))
        self.assertFalse(system.trigger(0))
        self.assertFalse(system.is_active(0))
        self.assertEqual(system.active_for(0), 0.0)
        self.assertEqual(system.cooldown_left(0), 0.0)

    def test_every_modifier_is_the_identity(self) -> None:
        system = PowerupSystem(_spec("pu.none"))
        for player in (0, 1):
            with self.subTest(player=player):
                self.assertEqual(system.height_scale(player), 1.0)
                self.assertEqual(system.speed_scale(player), 1.0)
                self.assertEqual(system.return_speed_scale(player), 1.0)
                self.assertEqual(system.coins_per_hit(player), 0)
                self.assertFalse(system.controls_inverted(player))
                self.assertFalse(system.shielded(player))
                self.assertFalse(system.just_fired(player))
        self.assertFalse(system.slow_ball())
        self.assertEqual(system.ball_speed_scale(), 1.0)

    def test_a_magnet_never_reports_a_target(self) -> None:
        world = _World()
        world.ball.active = True
        world.ball.x, world.ball.y = 700.0, 200.0
        world.ball.vx = -400.0
        system = PowerupSystem(_spec("pu.none"))
        self.assertIsNone(system.magnet_target(0, world.ball, world.court,
                                               world.left))

    def test_ai_never_fires_a_disabled_powerup(self) -> None:
        system = PowerupSystem(_spec("pu.none"))
        self.assertFalse(system.ai_should_fire(0, DT, incoming=True,
                                               rng=Rng(1)))


class CooldownTests(unittest.TestCase):
    """OVERDRIVE: 6.0s at 1.55x, 14.0s cooldown, SELF."""

    def setUp(self) -> None:
        self.system = PowerupSystem(_spec("pu.overdrive"))

    def test_starts_ready_and_fires(self) -> None:
        self.assertTrue(self.system.enabled)
        self.assertTrue(self.system.ready(0))
        self.assertTrue(self.system.trigger(0))
        self.assertFalse(self.system.ready(0))
        self.assertTrue(self.system.is_active(0))
        self.assertEqual(self.system.speed_scale(0), 1.55)

    def test_a_press_on_cooldown_is_ignored(self) -> None:
        self.assertTrue(self.system.trigger(0))
        self.assertFalse(self.system.trigger(0))
        _advance(self.system, 3.0)             # still inside the 6s window
        self.assertFalse(self.system.trigger(0))
        _advance(self.system, 3.0)             # effect over, cooldown remains
        self.assertFalse(self.system.is_active(0))
        self.assertFalse(self.system.trigger(0))
        self.assertAlmostEqual(self.system.cooldown_left(0), 8.0, delta=0.05)

    def test_cooldown_outlives_the_effect(self) -> None:
        self.assertTrue(self.system.trigger(0))
        _advance(self.system, 6.0)
        self.assertFalse(self.system.is_active(0))
        self.assertFalse(self.system.ready(0), "cooldown must outlive the buff")
        _advance(self.system, 8.0)
        self.assertAlmostEqual(self.system.cooldown_left(0), 0.0)
        self.assertTrue(self.system.ready(0))

    def test_timers_never_go_negative(self) -> None:
        self.assertTrue(self.system.trigger(0))
        _advance(self.system, 60.0)
        self.assertEqual(self.system.cooldown_left(0), 0.0)
        self.assertEqual(self.system.active_for(0), 0.0)

    def test_paddles_have_independent_cooldowns(self) -> None:
        self.assertTrue(self.system.trigger(0))
        self.assertTrue(self.system.ready(1), "P2 must keep its own charge")
        self.assertTrue(self.system.trigger(1))
        _advance(self.system, 6.0)
        self.assertFalse(self.system.is_active(0))
        self.assertFalse(self.system.is_active(1))
        # Both fired on the same step, so both windows close together.
        _advance(self.system, 8.0)
        self.assertTrue(self.system.ready(0))
        self.assertTrue(self.system.ready(1))

    def test_one_paddle_can_be_on_cooldown_while_the_other_is_ready(self) -> None:
        self.assertTrue(self.system.trigger(0))          # P1's window: 14s
        _advance(self.system, 2.0)
        self.assertTrue(self.system.trigger(1))          # P2's window: 16s
        _advance(self.system, 5.0)                       # t ~= 7s
        self.assertFalse(self.system.ready(0))
        self.assertFalse(self.system.ready(1))
        _advance(self.system, 8.0)                       # t ~= 15s
        self.assertTrue(self.system.ready(0), "P1 fired 2s earlier")
        self.assertFalse(self.system.ready(1), "P2 still has ~1s to wait")
        _advance(self.system, 2.0)                       # t ~= 17s
        self.assertTrue(self.system.ready(1))

    def test_clear_drops_every_timer(self) -> None:
        self.assertTrue(self.system.trigger(0))
        self.system.clear()
        self.assertTrue(self.system.ready(0))
        self.assertEqual(self.system.active_for(0), 0.0)
        self.assertEqual(self.system.cooldown_left(0), 0.0)


class IdempotenceTests(unittest.TestCase):
    """Firing again must produce the same modifier, never a stacked one."""

    def test_height_does_not_stack(self) -> None:
        system = PowerupSystem(_spec("pu.giant"))
        for _ in range(5):
            self.assertTrue(system.trigger(0))
            self.assertEqual(system.height_scale(0), 1.55)
            _advance(system, 6.0 + 16.0)

    def test_speed_does_not_stack(self) -> None:
        system = PowerupSystem(_spec("pu.overdrive"))
        for _ in range(5):
            self.assertTrue(system.trigger(1))
            self.assertEqual(system.speed_scale(1), 1.55)
            _advance(system, 6.0 + 14.0)

    def test_modifiers_are_identity_outside_the_window(self) -> None:
        system = PowerupSystem(_spec("pu.giant"))
        self.assertEqual(system.height_scale(0), 1.0)
        self.assertTrue(system.trigger(0))
        _advance(system, 6.0)
        self.assertEqual(system.height_scale(0), 1.0)

    def test_another_spec_never_leaks_into_an_unrelated_modifier(self) -> None:
        """GIANT PADDLE must not quietly affect speed as well as height."""
        system = PowerupSystem(_spec("pu.giant"))
        self.assertTrue(system.trigger(0))
        self.assertEqual(system.speed_scale(0), 1.0)
        self.assertFalse(system.shielded(0))
        self.assertEqual(system.return_speed_scale(0), 1.0)
        self.assertEqual(system.coins_per_hit(0), 0)


class SelfVsOpponentTests(unittest.TestCase):
    """A SELF buff must never touch the other paddle, and vice versa."""

    def test_self_buff_only_affects_the_firer(self) -> None:
        system = PowerupSystem(_spec("pu.giant"))       # HEIGHT, SELF, 1.55
        self.assertTrue(system.trigger(0))
        self.assertEqual(system.height_scale(0), 1.55)
        self.assertEqual(system.height_scale(1), 1.0)

    def test_opponent_buff_hits_the_other_paddle(self) -> None:
        system = PowerupSystem(_spec("pu.shrinkray"))   # HEIGHT, OPPONENT, 0.6
        self.assertTrue(system.trigger(0))
        self.assertEqual(system.height_scale(0), 1.0, "firer must be unaffected")
        self.assertEqual(system.height_scale(1), 0.6)

    def test_opponent_buff_is_symmetric(self) -> None:
        system = PowerupSystem(_spec("pu.freezeray"))   # SPEED, OPPONENT, 0.5
        self.assertTrue(system.trigger(1))
        self.assertEqual(system.speed_scale(0), 0.5)
        self.assertEqual(system.speed_scale(1), 1.0)

    def test_inversion_follows_the_opponent_rule(self) -> None:
        system = PowerupSystem(_spec("pu.reverser"))    # INVERT, OPPONENT
        self.assertTrue(system.trigger(0))
        self.assertTrue(system.controls_inverted(1))
        self.assertFalse(system.controls_inverted(0))
        _advance(system, 5.0)
        self.assertFalse(system.controls_inverted(1))
        # P2 firing back turns P1's controls over.
        _advance(system, 26.0)
        self.assertTrue(system.trigger(1))
        self.assertTrue(system.controls_inverted(0))
        self.assertFalse(system.controls_inverted(1))

    def test_shield_seals_only_the_owner(self) -> None:
        system = PowerupSystem(_spec("pu.shield"))      # SHIELD, SELF, 4s
        self.assertTrue(system.trigger(0))
        self.assertTrue(system.shielded(0))
        self.assertFalse(system.shielded(1))
        _advance(system, 4.0)
        self.assertFalse(system.shielded(0), "the seal must expire")

    def test_gold_rush_pays_only_the_owner(self) -> None:
        system = PowerupSystem(_spec("pu.goldrush"))    # COINS, SELF, 4/hit
        self.assertEqual(system.coins_per_hit(0), 0)
        self.assertTrue(system.trigger(1))
        self.assertEqual(system.coins_per_hit(1), 4)
        self.assertEqual(system.coins_per_hit(0), 0)
        _advance(system, 8.0)
        self.assertEqual(system.coins_per_hit(1), 0)

    def test_fireball_hastens_only_the_owner_returns(self) -> None:
        system = PowerupSystem(_spec("pu.fireball"))    # RETURN_SPEED, SELF
        self.assertTrue(system.trigger(0))
        self.assertEqual(system.return_speed_scale(0), 1.45)
        self.assertEqual(system.return_speed_scale(1), 1.0)


class SlowFieldTests(unittest.TestCase):
    """SLOW FIELD is GLOBAL: either paddle's activation slows the ball."""

    def test_goes_live_with_either_paddle(self) -> None:
        system = PowerupSystem(_spec("pu.slowball"))
        self.assertFalse(system.slow_ball())
        self.assertEqual(system.ball_speed_scale(), 1.0)
        self.assertTrue(system.trigger(0))
        self.assertTrue(system.slow_ball())
        self.assertEqual(system.ball_speed_scale(), 0.65)

    def test_stays_up_while_the_other_timer_runs(self) -> None:
        system = PowerupSystem(_spec("pu.slowball"))
        self.assertTrue(system.trigger(0))
        _advance(system, 3.0)
        self.assertTrue(system.trigger(1))       # P1's window starts later
        _advance(system, 3.0)                    # P0 closes, P1 has 3s left
        self.assertTrue(system.slow_ball(), "P1's window is still open")
        _advance(system, 3.0)
        self.assertFalse(system.slow_ball())
        self.assertEqual(system.ball_speed_scale(), 1.0)


class MagnetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = _World()
        self.system = PowerupSystem(_spec("pu.magnet"))

    def _ball(self, vx: float, *, active: bool = True) -> Ball:
        ball = self.world.ball
        ball.active = active
        ball.x, ball.y = 700.0, 200.0
        ball.vx, ball.vy = vx, 0.0
        return ball

    def test_inactive_when_the_timer_is_not_running(self) -> None:
        self.assertIsNone(self.system.magnet_target(
            0, self._ball(-400.0), self.world.court, self.world.left))

    def test_only_steers_a_ball_coming_home(self) -> None:
        self.assertTrue(self.system.trigger(0))
        self.assertIsNone(self.system.magnet_target(
            0, self._ball(+400.0), self.world.court, self.world.left),
            "a ball already leaving must not be shunted")
        target = self.system.magnet_target(
            0, self._ball(-400.0), self.world.court, self.world.left)
        self.assertIsNotNone(target)
        self.assertAlmostEqual(target, self.world.left.y)

    def test_target_is_clamped_inside_the_court(self) -> None:
        self.assertTrue(self.system.trigger(0))
        ball = self._ball(-400.0)
        self.world.left.y = -500.0              # a paddle parked off-screen
        self.assertAlmostEqual(
            self.system.magnet_target(0, ball, self.world.court,
                                      self.world.left),
            self.world.court.top + self.world.left.h * 0.5)
        self.world.left.y = 5000.0
        self.assertAlmostEqual(
            self.system.magnet_target(0, ball, self.world.court,
                                      self.world.left),
            self.world.court.bottom - self.world.left.h * 0.5)

    def test_a_dead_ball_is_not_steered(self) -> None:
        self.assertTrue(self.system.trigger(0))
        self.assertIsNone(self.system.magnet_target(
            0, self._ball(-400.0, active=False), self.world.court,
            self.world.left))

    def test_steering_tolerates_a_ball_already_on_target(self) -> None:
        """Inside the deadzone the magnet must go quiet, not oscillate."""
        ball = self.world.ball
        ball.active = True
        ball.x, ball.y = 500.0, 300.0
        ball.vx, ball.vy = -100.0, 0.0
        apply_magnet(ball, ball.y + MAGNET_DEADZONE - 1.0, DT)
        self.assertEqual(ball.vy, 0.0)

    def test_steering_pushes_toward_the_target(self) -> None:
        ball = self.world.ball
        ball.active = True
        ball.x, ball.y = 500.0, 100.0
        ball.vx, ball.vy = -100.0, 0.0
        apply_magnet(ball, 400.0, DT)            # the target is below
        self.assertAlmostEqual(ball.vy, MAGNET_STRENGTH * DT)
        # One step is not enough to reverse a downward pull, two are.
        apply_magnet(ball, -400.0, DT)
        self.assertEqual(ball.vy, 0.0)
        apply_magnet(ball, -400.0, DT)
        self.assertAlmostEqual(ball.vy, -MAGNET_STRENGTH * DT)

    def test_a_dead_ball_is_untouched(self) -> None:
        ball = self.world.ball
        ball.active = False
        ball.x, ball.y = 500.0, 100.0
        ball.vx, ball.vy = -100.0, 0.0
        apply_magnet(ball, 400.0, DT)
        self.assertEqual(ball.vy, 0.0)


class MagnetSteeringTests(unittest.TestCase):
    """The magnet as it actually flies, not just one step of it.

    These exist because a single-step assertion cannot see the failure that
    shipped: ``apply_magnet`` used to add a constant force for the whole
    effect, and on a double integrator that is bang-bang control - the ball
    overshot, reversed and overshot again, each swing wider than the last.
    """

    def _fly(self, *, start: float, target: float, seconds: float,
             vy0: float = 0.0, target_vy: float = 0.0) -> list[tuple[float, float]]:
        """Step a ball under the magnet; returns the (y, vy) trace."""
        ball = Ball(default_court())
        ball.active = True
        ball.x, ball.y = 700.0, start
        ball.vx, ball.vy = -430.0, vy0
        trace: list[tuple[float, float]] = []
        for _ in range(int(round(seconds / DT))):
            apply_magnet(ball, target, DT, target_vy=target_vy)
            ball.y += ball.vy * DT
            trace.append((ball.y, ball.vy))
        return trace

    def test_the_vertical_speed_is_bounded_for_the_whole_effect(self) -> None:
        """Regression: ``vy`` used to reach the thousands and smear the puck."""
        trace = self._fly(start=100.0, target=560.0, seconds=5.0)
        peak = max(abs(vy) for _, vy in trace)
        self.assertLessEqual(peak, MAGNET_MAX_VY,
                             f"peak |vy| was {peak:.0f} px/s")
        self.assertAlmostEqual(trace[-1][0], 560.0, delta=MAGNET_DEADZONE)

    def test_it_settles_on_the_line_instead_of_bouncing_past_it(self) -> None:
        target = 560.0
        trace = self._fly(start=100.0, target=target, seconds=4.0)
        overshoot = max(y for y, _ in trace) - target
        self.assertLessEqual(overshoot, 12.0,
                             f"the ball overshot the mallet by {overshoot:.1f} px")
        self.assertAlmostEqual(trace[-1][0], target, delta=MAGNET_DEADZONE)

    def test_it_recovers_after_a_wall_bounce_away_from_the_target(self) -> None:
        """A bounce sends the ball the wrong way; the magnet must win it back."""
        trace = self._fly(start=100.0, target=300.0, seconds=3.0, vy0=-700.0)
        self.assertAlmostEqual(trace[-1][0], 300.0, delta=MAGNET_DEADZONE)

    def test_forward_speed_is_left_alone(self) -> None:
        """Only the physics module owns how fast the rally travels."""
        ball = Ball(default_court())
        ball.active = True
        ball.x, ball.y = 700.0, 100.0
        ball.vx, ball.vy = -430.0, 0.0
        apply_magnet(ball, 560.0, DT)
        self.assertEqual(ball.vx, -430.0)
        self.assertGreater(ball.vy, 0.0)

    def test_a_sliding_mallet_is_followed_not_chased(self) -> None:
        """Feed-forward removes the lag a purely reactive magnet cannot."""
        line_speed = 120.0
        seconds = 2.0

        def final_gap(target_vy: float) -> float:
            ball = Ball(default_court())
            ball.active = True
            ball.x, ball.y = 700.0, 100.0
            ball.vx, ball.vy = -430.0, 0.0
            line = 100.0
            for _ in range(int(round(seconds / DT))):
                line += line_speed * DT
                apply_magnet(ball, line, DT, target_vy=target_vy)
                ball.y += ball.vy * DT
            return abs(ball.y - line)

        reactive, tracked = final_gap(0.0), final_gap(line_speed)
        # Theory: a purely reactive magnet settles at speed / gain below the
        # line - 120 / 2.4 = 50 px of permanent lag behind a sliding mallet.
        expected_lag = line_speed / MAGNET_GAIN
        self.assertGreater(reactive, expected_lag * 0.5,
                           "the baseline lag vanished")
        self.assertLess(tracked, reactive * 0.5,
                        f"a moving paddle still lags {tracked:.1f} px "
                        f"versus {reactive:.1f} px without feed-forward")


class JustFiredTests(unittest.TestCase):
    def test_reports_true_for_exactly_one_read(self) -> None:
        system = PowerupSystem(_spec("pu.overdrive"))
        self.assertFalse(system.just_fired(0))
        self.assertTrue(system.trigger(0))
        self.assertTrue(system.just_fired(0))
        self.assertFalse(system.just_fired(0))

    def test_a_blocked_press_reports_nothing(self) -> None:
        system = PowerupSystem(_spec("pu.overdrive"))
        self.assertTrue(system.trigger(0))
        self.assertTrue(system.just_fired(0))
        self.assertFalse(system.trigger(0))
        self.assertFalse(system.just_fired(0))


class AiTriggerTests(unittest.TestCase):
    def test_delay_window_is_sane(self) -> None:
        self.assertGreater(AI_MIN_DELAY, 0.0)
        self.assertLess(AI_MIN_DELAY, AI_MAX_DELAY)

    def test_the_bot_never_answers_inside_its_reaction_window(self) -> None:
        system = PowerupSystem(_spec("pu.overdrive"))
        rng = Rng(7)
        self.assertFalse(system.ai_should_fire(0, DT, incoming=False,
                                               rng=rng))
        self.assertFalse(system.ai_should_fire(0, AI_MIN_DELAY,
                                               incoming=False, rng=rng))

    def test_bot_commits_once_the_window_elapses(self) -> None:
        system = PowerupSystem(_spec("pu.overdrive"))
        rng = Rng(7)
        system.ai_should_fire(0, DT, incoming=False, rng=rng)  # arms the delay
        fired = False
        for _ in range(int(AI_MAX_DELAY / DT) + 10):
            if system.ai_should_fire(0, DT, incoming=True, rng=rng):
                fired = True
                break
        self.assertTrue(fired, "the bot never re-armed")
        self.assertFalse(system.ai_should_fire(0, DT, incoming=True, rng=rng),
                         "one press, one activation")

    def test_bot_waits_out_a_live_cooldown(self) -> None:
        system = PowerupSystem(_spec("pu.overdrive"))
        rng = Rng(7)
        self.assertTrue(system.trigger(0))
        for _ in range(50):
            self.assertFalse(system.ai_should_fire(0, DT, incoming=True,
                                                   rng=rng))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
