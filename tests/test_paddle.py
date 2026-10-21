"""Paddle control regressions.

These cover the "any key drives both paddles into the floor" bug: the sign of
the acceleration step must follow the sign of the input error, so that

* ``axis < 0`` always accelerates *upwards*,
* ``axis > 0`` always accelerates *downwards*,
* ``axis == 0`` never lets the paddle drift, and

the key -> axis mapping must be symmetric in both solo and 2-player modes.
"""

from __future__ import annotations

import unittest
from collections import defaultdict
from unittest.mock import patch

import pygame

from pongpro.core.constants import (
    PADDLE_ACCEL,
    PADDLE_SPEED,
    GameMode,
)
from pongpro.gameplay.entities import Paddle, default_court
from pongpro.scenes.gameplay import GameplayScene

DT = 1.0 / 120.0


class PaddleMovementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.court = default_court()
        self.top = self.court.top + Paddle(True, self.court).h * 0.5
        self.bottom = self.court.bottom - Paddle(True, self.court).h * 0.5

    def _centre(self) -> Paddle:
        paddle = Paddle(True, self.court)
        paddle.reset(self.court)
        return paddle

    def test_negative_axis_moves_up(self) -> None:
        paddle = self._centre()
        start = paddle.y
        for _ in range(30):
            paddle.update(-1.0, DT, self.court)
        self.assertLess(paddle.y, start, "-1 axis must move the paddle up")
        self.assertLess(paddle.vel, 0.0)

    def test_positive_axis_moves_down(self) -> None:
        paddle = self._centre()
        start = paddle.y
        for _ in range(30):
            paddle.update(1.0, DT, self.court)
        self.assertGreater(paddle.y, start, "+1 axis must move the paddle down")
        self.assertGreater(paddle.vel, 0.0)

    def test_zero_axis_never_drifts(self) -> None:
        paddle = self._centre()
        start = paddle.y
        for _ in range(1200):  # 10 simulated seconds
            paddle.update(0.0, DT, self.court)
        self.assertEqual(paddle.y, start, "idle paddle must not creep")
        self.assertEqual(paddle.vel, 0.0)

    def test_up_from_the_floor_reaches_the_ceiling(self) -> None:
        """Regression: an "up" input used to be integrated downwards."""
        paddle = self._centre()
        paddle.y = self.bottom
        paddle.update(1.0, DT, self.court)
        self.assertAlmostEqual(paddle.y, self.bottom)
        for _ in range(600):
            paddle.update(-1.0, DT, self.court)
        self.assertAlmostEqual(paddle.y, self.top, places=4)
        self.assertGreaterEqual(paddle.y, self.top - 1e-6)

    def test_down_from_the_ceiling_reaches_the_floor(self) -> None:
        paddle = self._centre()
        paddle.y = self.top
        for _ in range(600):
            paddle.update(1.0, DT, self.court)
        self.assertAlmostEqual(paddle.y, self.bottom, places=4)

    def test_acceleration_is_symmetric_about_the_centre(self) -> None:
        up = self._centre()
        down = self._centre()
        centre = self.court.center_y
        for _ in range(90):
            up.update(-1.0, DT, self.court)
            down.update(1.0, DT, self.court)
        self.assertAlmostEqual(up.y + down.y, 2.0 * centre, places=6)
        self.assertAlmostEqual(up.vel, -down.vel, places=6)

    def test_axis_is_clamped(self) -> None:
        paddle = self._centre()
        paddle.update(-99.0, DT, self.court)
        self.assertEqual(paddle.input_axis, -1.0)
        paddle.update(+99.0, DT, self.court)
        self.assertEqual(paddle.input_axis, +1.0)

    def test_reaches_terminal_speed(self) -> None:
        paddle = self._centre()
        for _ in range(600):
            paddle.update(1.0, DT, self.court)
            if abs(paddle.vel) >= PADDLE_SPEED - 1e-9:
                break
        self.assertAlmostEqual(abs(paddle.vel), PADDLE_SPEED, places=6)
        # PADDLE_ACCEL * time to reach terminal speed, up to a full step of dt.
        seconds = PADDLE_SPEED / PADDLE_ACCEL
        self.assertLessEqual(seconds, 0.2, "acceleration should feel responsive")

    def test_paddle_never_leaves_the_court(self) -> None:
        paddle = self._centre()
        sequence = [1.0] * 240 + [-1.0] * 240 + [0.0] * 240
        for axis in sequence:
            paddle.update(axis, DT, self.court)
            self.assertGreaterEqual(paddle.y, self.top - 1e-6)
            self.assertLessEqual(paddle.y, self.bottom + 1e-6)


class _FakeScene:
    """Minimal stand-in: ``_read_axes`` only reads ``self.mode``."""

    def __init__(self, mode: GameMode) -> None:
        self.mode = mode


class InputAxisTests(unittest.TestCase):
    def _axes(self, mode: GameMode, *held: int) -> tuple[float, float]:
        # defaultdict(bool) mirrors ScancodeWrapper: an untouched key reads False.
        pressed: defaultdict[int, bool] = defaultdict(bool)
        for key in held:
            pressed[key] = True
        with patch.object(pygame.key, "get_pressed", lambda: pressed):
            return GameplayScene._read_axes(_FakeScene(mode))  # type: ignore[arg-type]

    def test_nothing_held_is_neutral(self) -> None:
        for mode in GameMode:
            self.assertEqual(self._axes(mode), (0.0, 0.0), mode)

    def test_solo_wasd_and_arrows_agree(self) -> None:
        self.assertEqual(self._axes(GameMode.SOLO, pygame.K_w), (-1.0, 0.0))
        self.assertEqual(self._axes(GameMode.SOLO, pygame.K_s), (+1.0, 0.0))
        self.assertEqual(self._axes(GameMode.SOLO, pygame.K_UP), (-1.0, 0.0))
        self.assertEqual(self._axes(GameMode.SOLO, pygame.K_DOWN), (+1.0, 0.0))
        # Opposite keys cancel rather than falling through to a default.
        self.assertEqual(self._axes(GameMode.SOLO, pygame.K_w, pygame.K_s),
                         (0.0, 0.0))
        self.assertEqual(self._axes(GameMode.SOLO, pygame.K_w, pygame.K_UP),
                         (-1.0, 0.0))
        self.assertEqual(self._axes(GameMode.SOLO, pygame.K_s, pygame.K_DOWN),
                         (+1.0, 0.0))

    def test_two_player_keeps_the_paddles_independent(self) -> None:
        self.assertEqual(self._axes(GameMode.TWO_PLAYER, pygame.K_w),
                         (-1.0, 0.0))
        # P1 must not be dragged by the arrows in 2P mode.
        self.assertEqual(self._axes(GameMode.TWO_PLAYER, pygame.K_DOWN),
                         (0.0, +1.0))
        self.assertEqual(self._axes(GameMode.TWO_PLAYER, pygame.K_UP),
                         (0.0, -1.0))

    def test_focus_right_paddle_moves_up_as_well_as_down(self) -> None:
        # Regression: the two right-paddle binding groups were merged with
        # max().  A group with no key held contributes 0.0, and
        # max(-1.0, 0.0) == 0.0, so every "up" input was silently discarded
        # and the paddle could only ever travel downwards.
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_i), (0.0, -1.0))
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_UP), (0.0, -1.0))
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_k), (0.0, +1.0))
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_DOWN), (0.0, +1.0))

    def test_focus_left_paddle_stays_on_wasd(self) -> None:
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_w), (-1.0, 0.0))
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_s), (+1.0, 0.0))
        # The arrows belong to the right hand in this mode, never the left.
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_UP), (0.0, -1.0))
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_DOWN), (0.0, +1.0))

    def test_focus_reinforcing_groups_clamp_instead_of_cancelling(self) -> None:
        # Holding IJKL *and* arrows together must still read as full travel -
        # the reason the groups are summed rather than averaged - and
        # opposing keys within one hand still cancel to neutral.
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_i, pygame.K_UP),
                         (0.0, -1.0))
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_k, pygame.K_DOWN),
                         (0.0, +1.0))
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_i, pygame.K_k),
                         (0.0, 0.0))
        self.assertEqual(self._axes(GameMode.FOCUS, pygame.K_i, pygame.K_DOWN),
                         (0.0, 0.0))

    def test_ai_vs_ai_ignores_the_keyboard(self) -> None:
        self.assertEqual(
            self._axes(GameMode.AI_VS_AI,
                       pygame.K_w, pygame.K_s, pygame.K_UP, pygame.K_DOWN),
            (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
