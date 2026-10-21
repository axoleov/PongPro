"""Collision maths: walls, continuous paddle contact, deflection, prediction."""

from __future__ import annotations

import math
import unittest

from pongpro.core.constants import (
    MAX_BALL_SPEED,
    MAX_DEFLECT_DEG,
    BALL_RADIUS,
    PADDLE_H,
    PADDLE_W,
)
from pongpro.gameplay.entities import Ball, Court, Paddle, default_court
from pongpro.gameplay.physics import (
    deflect,
    liang_barsky,
    next_paddle_speed,
    predict_intercept_y,
    resolve_walls,
    swept_circle_rect,
    time_to_cross,
    try_paddle_contact,
)


def make_ball(x: float, y: float, vx: float, vy: float) -> Ball:
    ball = Ball(default_court())
    ball.x, ball.y, ball.vx, ball.vy = x, y, vx, vy
    ball.prev_x, ball.prev_y = x, y
    ball.active = True
    return ball


class LiangBarskyTests(unittest.TestCase):
    def test_segment_inside_rect(self) -> None:
        self.assertEqual(liang_barsky(1, 1, 2, 2, 0, 0, 10, 10), (0.0, 1.0))

    def test_crossing_rect(self) -> None:
        hit = liang_barsky(-5, 5, 15, 5, 0, 0, 10, 10)
        assert hit is not None
        t0, t1 = hit
        self.assertAlmostEqual(t0, 0.25)  # enters at x=0 -> 5/20
        self.assertAlmostEqual(t1, 0.75)

    def test_parallel_miss(self) -> None:
        self.assertIsNone(liang_barsky(-5, 20, 15, 20, 0, 0, 10, 10))

    def test_pointing_away(self) -> None:
        self.assertIsNone(liang_barsky(20, 5, 30, 5, 0, 0, 10, 10))


class SweptCircleTests(unittest.TestCase):
    def test_detects_crossing(self) -> None:
        rect = (100.0, 0.0, 16.0, 100.0)
        t = swept_circle_rect((140.0, 50.0), (80.0, 50.0), BALL_RADIUS, rect)
        self.assertIsNotNone(t)
        assert t is not None
        self.assertGreaterEqual(t, 0.0)
        self.assertLessEqual(t, 1.0)

    def test_miss_when_far_vertically(self) -> None:
        rect = (100.0, 0.0, 16.0, 40.0)
        self.assertIsNone(
            swept_circle_rect((140.0, 300.0), (80.0, 300.0), BALL_RADIUS, rect))

    def test_fast_ball_cannot_tunnel(self) -> None:
        """A 3000 px/s step straight through a paddle must still register."""
        court = default_court()
        paddle = Paddle(True, court)
        ball = make_ball(paddle.x + 40.0, paddle.y, -3000.0, 0.0)
        ball.begin_step()
        ball.integrate(1.0 / 60.0)  # moves ~50px, past the paddle
        contact = try_paddle_contact(ball, paddle, 500.0)
        self.assertIsNotNone(contact)
        assert contact is not None
        # Ball is rewound to the paddle surface, travelling away from it.
        self.assertGreater(ball.vx, 0.0)
        self.assertAlmostEqual(ball.x,
                               paddle.x + PADDLE_W / 2 + BALL_RADIUS + 0.5,
                               delta=60.0)


class WallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.court = default_court()

    def test_top_wall_reflects_downward(self) -> None:
        ball = make_ball(400.0, self.court.top + 2.0, 300.0, -500.0)
        self.assertTrue(resolve_walls(ball, self.court))
        self.assertGreater(ball.vy, 0.0)
        self.assertAlmostEqual(ball.y, self.court.top + BALL_RADIUS)

    def test_bottom_wall_reflects_upward(self) -> None:
        ball = make_ball(400.0, self.court.bottom - 2.0, 300.0, 500.0)
        self.assertTrue(resolve_walls(ball, self.court))
        self.assertLess(ball.vy, 0.0)

    def test_no_contact_in_open_space(self) -> None:
        ball = make_ball(400.0, (self.court.top + self.court.bottom) / 2,
                         300.0, 500.0)
        self.assertFalse(resolve_walls(ball, self.court))


class DeflectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.court = default_court()
        self.left = Paddle(True, self.court)
        self.right = Paddle(False, self.court)

    def test_centre_hit_is_straight(self) -> None:
        ball = make_ball(self.left.x + 20.0, self.left.y, -400.0, 0.0)
        angle, edge = deflect(ball, self.left, 500.0)
        self.assertLess(abs(angle), math.radians(6.0))
        self.assertFalse(edge)
        self.assertAlmostEqual(math.hypot(ball.vx, ball.vy), 500.0, delta=0.01)

    def test_top_hit_sends_ball_up(self) -> None:
        ball = make_ball(self.left.x + 20.0, self.left.y - PADDLE_H / 2,
                         -400.0, 0.0)
        angle, edge = deflect(ball, self.left, 500.0)
        self.assertLess(angle, 0.0)
        self.assertTrue(edge)
        self.assertLess(ball.vy, 0.0)

    def test_bottom_hit_sends_ball_down(self) -> None:
        ball = make_ball(self.left.x + 20.0, self.left.y + PADDLE_H / 2,
                         -400.0, 0.0)
        angle, _ = deflect(ball, self.left, 500.0)
        self.assertGreater(angle, 0.0)
        self.assertGreater(ball.vy, 0.0)

    def test_deflection_never_exceeds_max_angle(self) -> None:
        ball = make_ball(self.left.x + 20.0, self.left.y - 1000.0, -400.0, 0.0)
        angle, _ = deflect(ball, self.left, 500.0)
        self.assertLessEqual(abs(angle), math.radians(MAX_DEFLECT_DEG) + 1e-9)

    def test_ball_always_leaves_towards_opponent(self) -> None:
        for offset in (-200, -60, 0, 60, 200):
            ball = make_ball(self.left.x + 20.0, self.left.y + offset,
                             -400.0, 0.0)
            deflect(ball, self.left, 520.0)
            self.assertGreater(ball.vx, 0.0, f"offset={offset}")

        for offset in (-200, -60, 0, 60, 200):
            ball = make_ball(self.right.x - 20.0, self.right.y + offset,
                             400.0, 0.0)
            deflect(ball, self.right, 520.0)
            self.assertLess(ball.vx, 0.0, f"offset={offset}")

    def test_ball_is_pushed_clear_of_paddle(self) -> None:
        ball = make_ball(self.left.x, self.left.y, -400.0, 0.0)
        deflect(ball, self.left, 500.0)
        self.assertGreater(ball.x, self.left.x + PADDLE_W / 2)

    def test_english_adds_paddle_velocity(self) -> None:
        plain = make_ball(self.left.x + 20.0, self.left.y, -400.0, 0.0)
        deflect(plain, self.left, 500.0, english=True)

        fast_paddle = Paddle(True, self.court)
        fast_paddle.y = self.left.y
        fast_paddle.vel = 640.0
        with_spin = make_ball(fast_paddle.x + 20.0, fast_paddle.y, -400.0, 0.0)
        deflect(with_spin, fast_paddle, 500.0, english=True)

        self.assertGreater(with_spin.vy, plain.vy + 5.0)
        self.assertAlmostEqual(math.hypot(with_spin.vx, with_spin.vy), 500.0,
                               delta=0.01)


class SpeedRampTests(unittest.TestCase):
    def test_rally_increases_speed(self) -> None:
        self.assertGreater(next_paddle_speed(500.0, 3, True), 500.0)

    def test_disabled_speedup_holds_speed(self) -> None:
        self.assertEqual(next_paddle_speed(500.0, 3, False), 500.0)

    def test_hard_cap_at_max(self) -> None:
        self.assertEqual(next_paddle_speed(MAX_BALL_SPEED, 99, True),
                         MAX_BALL_SPEED)


class PredictionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.court = default_court()

    def test_straight_shot(self) -> None:
        # vx=500, target 300px away -> t=0.6s; y=200, vy=100 -> 260
        result = predict_intercept_y(100.0, 200.0, 500.0, 100.0, BALL_RADIUS,
                                     400.0, self.court)
        self.assertAlmostEqual(result or 0.0, 260.0, delta=0.01)

    def test_wall_reflection_is_predicted(self) -> None:
        # Hand-computed: travels to the bottom wall then bounces back up.
        lo = self.court.top + BALL_RADIUS
        hi = self.court.bottom - BALL_RADIUS
        span = hi - lo
        y, vy, t = 100.0, 500.0, 1.5
        crossing = y + vy * t
        rel = crossing - lo
        period = 2 * span
        rel %= period
        if rel > span:
            rel = period - rel
        expected = lo + rel

        result = predict_intercept_y(y, y, 430.0, vy, BALL_RADIUS,
                                     y + 430.0 * t, self.court)
        self.assertAlmostEqual(result or 0.0, expected, delta=0.01)

    def test_none_when_travelling_away(self) -> None:
        self.assertIsNone(predict_intercept_y(500.0, 300.0, -430.0, 0.0,
                                              BALL_RADIUS, 900.0, self.court))

    def test_none_when_vx_is_zero(self) -> None:
        self.assertIsNone(predict_intercept_y(300.0, 300.0, 0.0, 100.0,
                                              BALL_RADIUS, 600.0, self.court))

    def test_result_always_inside_walls(self) -> None:
        for y in (70.0, 200.0, 360.0, 500.0, 650.0):
            for vy in (-900.0, -300.0, 0.0, 300.0, 900.0):
                result = predict_intercept_y(y, y, 500.0, vy, BALL_RADIUS,
                                             1100.0, self.court)
                if result is None:
                    continue
                self.assertGreaterEqual(result, self.court.top + BALL_RADIUS - 0.01)
                self.assertLessEqual(result, self.court.bottom - BALL_RADIUS + 0.01)

    def test_time_to_cross(self) -> None:
        self.assertAlmostEqual(time_to_cross(100.0, 500.0, 350.0) or -1.0, 0.5)
        self.assertIsNone(time_to_cross(100.0, -500.0, 350.0))


class CourtGeometryTests(unittest.TestCase):
    def test_default_court_is_centred(self) -> None:
        court = default_court()
        self.assertAlmostEqual(court.center_x, 640.0)
        self.assertAlmostEqual(court.center_y, 360.0)
        self.assertGreater(court.width, 0)
        self.assertGreater(court.height, 0)

    def test_paddle_rect_matches_float_rect(self) -> None:
        court = default_court()
        paddle = Paddle(True, court)
        paddle.y = 123.7
        rect = paddle.rect()
        fx, fy, fw, fh = paddle.rect_f()
        self.assertEqual((rect.x, rect.w), (round(fx), int(fw)))
        self.assertEqual(fh, paddle.h)


if __name__ == "__main__":
    unittest.main()
