"""Collision detection and ball deflection maths.

Everything here is *pure*: it takes values, returns values, and has no pygame
display dependency - which is what makes it straightforwardly unit-testable.

The paddle test is a swept (continuous) circle-vs-rect check using a
Liang-Barsky clip, so even at 1150 px/s the ball can never tunnel through a
paddle, and the exact impact point is known for correct deflection angles.
"""

from __future__ import annotations

import math
from typing import Iterable

from ..core.constants import (
    ENGLISH_FACTOR,
    MAX_BALL_SPEED,
    MAX_DEFLECT_DEG,
    PADDLE_TOLERANCE,
    RALLY_SPEEDUP,
)
from .entities import Ball, Court, Paddle


# --------------------------------------------------------------------------
# Continuous collision
# --------------------------------------------------------------------------
def liang_barsky(
    x0: float, y0: float, x1: float, y1: float,
    xmin: float, ymin: float, xmax: float, ymax: float,
) -> tuple[float, float] | None:
    """Parametric segment/rect clip.

    Returns ``(t0, t1)`` - the entry/exit parameters in [0, 1] - or ``None``
    when the segment misses the rectangle.
    """
    dx = x1 - x0
    dy = y1 - y0
    t0, t1 = 0.0, 1.0
    p = (-dx, dx, -dy, dy)
    q = (x0 - xmin, xmax - x0, y0 - ymin, ymax - y0)
    for pi, qi in zip(p, q):
        if abs(pi) < 1e-12:
            if qi < 0.0:
                return None
            continue
        r = qi / pi
        if pi < 0.0:
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return None
            if r < t1:
                t1 = r
    return (t0, t1)


def swept_circle_rect(
    p0: tuple[float, float], p1: tuple[float, float],
    radius: float, rect: tuple[float, float, float, float],
) -> float | None:
    """Time of impact (0..1) of a circle swept from ``p0`` to ``p1``.

    Implemented as a segment vs rect-expanded-by-radius clip; returns the
    *entry* parameter so callers can rewind the ball to the contact point.
    """
    rx, ry, rw, rh = rect
    expanded = (
        rx - PADDLE_TOLERANCE,
        ry - PADDLE_TOLERANCE,
        rw + 2 * PADDLE_TOLERANCE,
        rh + 2 * PADDLE_TOLERANCE,
    )
    hit = liang_barsky(
        p0[0], p0[1], p1[0], p1[1],
        expanded[0] - radius, expanded[1] - radius,
        expanded[0] + expanded[2] + radius,
        expanded[1] + expanded[3] + radius,
    )
    if hit is None:
        return None
    t0, _t1 = hit
    if t0 < 0.0:
        t0 = 0.0
    return t0


# --------------------------------------------------------------------------
# Walls
# --------------------------------------------------------------------------
def resolve_walls(ball: Ball, court: Court) -> bool:
    """Clamp & reflect off the top/bottom walls. Returns True on contact."""
    hit = False
    if ball.y - ball.r < court.top:
        ball.y = court.top + ball.r
        if ball.vy < 0.0:
            ball.vy = -ball.vy
        hit = True
    elif ball.y + ball.r > court.bottom:
        ball.y = court.bottom - ball.r
        if ball.vy > 0.0:
            ball.vy = -ball.vy
        hit = True
    return hit


# --------------------------------------------------------------------------
# Paddles
# --------------------------------------------------------------------------
def next_paddle_speed(current_speed: float, rally: int, speedup: bool) -> float:
    """Speed after a paddle contact (rally ramp with a hard cap)."""
    if not speedup:
        return min(current_speed, MAX_BALL_SPEED)
    return min(current_speed * RALLY_SPEEDUP, MAX_BALL_SPEED)


def deflect(
    ball: Ball,
    paddle: Paddle,
    new_speed: float,
    *,
    english: bool = True,
) -> tuple[float, bool]:
    """Reflect the ball off ``paddle`` at ``new_speed``.

    The deflection angle comes from *where* on the paddle the ball struck -
    centre drives straight, edges drive steep - and the paddle's own vertical
    velocity adds "english" so a moving paddle can curve the shot.

    Returns ``(angle_radians, was_edge_shot)``.
    """
    reach = paddle.h * 0.5 + ball.r
    offset = (ball.y - paddle.center_y) / reach
    offset = -1.0 if offset < -1.0 else 1.0 if offset > 1.0 else offset
    angle = math.radians(offset * MAX_DEFLECT_DEG)
    # 0.8 of reach ~= the outer band of the paddle; a ball whose centre lands
    # exactly on the paddle edge (offset 0.84 at default sizes) must count.
    edge = abs(offset) > 0.8

    dir_x = 1.0 if paddle.is_left else -1.0
    vx = dir_x * math.cos(angle) * new_speed
    vy = math.sin(angle) * new_speed

    if english and abs(paddle.vel) > 1.0:
        vy += paddle.vel * ENGLISH_FACTOR

    magnitude = math.hypot(vx, vy) or 1.0
    scale = new_speed / magnitude
    vx *= scale
    vy *= scale

    # Never allow a return that travels *backwards* into the hitter's own court.
    if dir_x > 0.0 and vx <= 1.0:
        vx = max(vx, new_speed * math.cos(math.radians(MAX_DEFLECT_DEG)))
    elif dir_x < 0.0 and vx >= -1.0:
        vx = -max(-vx, new_speed * math.cos(math.radians(MAX_DEFLECT_DEG)))

    ball.vx, ball.vy = vx, vy
    # Push the ball clear of the paddle so it cannot re-trigger next frame.
    half_w = paddle.w * 0.5
    if paddle.is_left:
        ball.x = paddle.x + half_w + ball.r + 0.5
    else:
        ball.x = paddle.x - half_w - ball.r - 0.5
    return angle, edge


def try_paddle_contact(
    ball: Ball,
    paddle: Paddle,
    new_speed: float,
    *,
    english: bool = True,
) -> tuple[float, bool] | None:
    """Swept paddle test for this fixed step; ``None`` when no contact.

    Only triggers when the ball is travelling *towards* the paddle, and uses
    the interpolated previous position to guarantee no tunneling.
    """
    if not ball.active:
        return None
    moving_in = (paddle.is_left and ball.vx < 0.0) or (
        (not paddle.is_left) and ball.vx > 0.0
    )
    if not moving_in:
        return None

    p0 = (ball.prev_x, ball.prev_y)
    p1 = (ball.x, ball.y)
    if p0 == p1:  # stationary ball parked between points
        return None

    t = swept_circle_rect(p0, p1, ball.r, paddle.rect_f())
    if t is None:
        return None
    # Rewind to the exact contact instant before deflecting.
    ball.x = p0[0] + (p1[0] - p0[0]) * t
    ball.y = p0[1] + (p1[1] - p0[1]) * t
    return deflect(ball, paddle, new_speed, english=english)


# --------------------------------------------------------------------------
# Trajectory prediction (shared by the AI and the "aim assist" debug HUD)
# --------------------------------------------------------------------------
def predict_intercept_y(
    x: float, y: float, vx: float, vy: float, radius: float,
    target_x: float, court: Court,
) -> float | None:
    """Where will the ball cross ``target_x``?

    Simulates reflections off the top/bottom walls analytically (mirrored
    image space) - O(1) instead of stepping the simulation forward.  Returns
    ``None`` when the ball is travelling away from ``target_x``.
    """
    if vx == 0.0 or (vx > 0.0) != (target_x > x):
        return None

    t = (target_x - x) / vx
    if t < 0.0:
        return None

    lo = court.top + radius
    hi = court.bottom - radius
    span = hi - lo
    if span <= 1e-6:
        return court.center_y

    crossing = y + vy * t
    rel = crossing - lo
    period = 2.0 * span
    rel %= period
    if rel > span:
        rel = period - rel
    return lo + rel


def ball_intercept(ball: Ball, target_x: float, court: Court) -> float | None:
    """Convenience wrapper around :func:`predict_intercept_y` for a Ball."""
    if not ball.active:
        return None
    return predict_intercept_y(
        ball.x, ball.y, ball.vx, ball.vy, ball.r, target_x, court
    )


def time_to_cross(x: float, vx: float, target_x: float) -> float | None:
    """Seconds until the ball reaches ``target_x`` (``None`` if moving away)."""
    if vx == 0.0:
        return None
    t = (target_x - x) / vx
    return t if t >= 0.0 else None


def segment_points(points: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    """Utility for trail rendering: downsample a dense polyline."""
    return list(points)
