"""Simulation entities: court geometry, paddles and the ball.

Positions are stored as *floats* (sub-pixel accuracy) with a ``prev_*``
copy taken at the start of every fixed step, which lets the renderer
interpolate between simulation states for buttery motion at any refresh rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from ..core.constants import (
    LOGICAL_H,
    LOGICAL_W,
    COURT_PAD_X,
    COURT_PAD_Y,
    PADDLE_ACCEL,
    PADDLE_FRICTION,
    PADDLE_H,
    PADDLE_SPEED,
    PADDLE_W,
    BALL_RADIUS,
)


@dataclass(frozen=True, slots=True)
class Court:
    """Play area in logical pixels (world coordinates)."""

    left: float
    right: float
    top: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) * 0.5

    @property
    def center_x(self) -> float:
        return (self.left + self.right) * 0.5

    def to_rect(self) -> pygame.Rect:
        return pygame.Rect(
            int(self.left), int(self.top),
            int(self.width), int(self.height),
        )


def default_court() -> Court:
    """The fixed 16:9 arena geometry."""
    return Court(
        left=float(COURT_PAD_X),
        right=float(LOGICAL_W - COURT_PAD_X),
        top=float(COURT_PAD_Y),
        bottom=float(LOGICAL_H - COURT_PAD_Y),
    )


class Paddle:
    """A player/AI controlled paddle, positioned by its centre point.

    Powerups modify a paddle through :attr:`height_scale` and
    :attr:`speed_scale`.  ``h`` stays the *effective* height so physics, the
    AI's half-height maths and ``rect()`` all keep working unchanged; the
    unscaled height is retained in ``base_h`` so modifiers can be swapped in
    and out without drift.
    """

    __slots__ = ("x", "y", "prev_y", "vel", "w", "h", "is_left", "input_axis",
                 "base_h", "height_scale", "speed_scale")

    def __init__(self, is_left: bool, court: Court) -> None:
        self.is_left = is_left
        self.w = float(PADDLE_W)
        self.base_h = float(PADDLE_H)
        self.height_scale = 1.0
        self.speed_scale = 1.0
        self.h = self.base_h
        self.x = (
            court.left + PADDLE_W * 0.5 + 26.0
            if is_left
            else court.right - PADDLE_W * 0.5 - 26.0
        )
        self.y = court.center_y
        self.prev_y = self.y
        self.vel = 0.0
        self.input_axis = 0.0

    # -- powerup modifiers ------------------------------------------------
    def apply_modifiers(self, court: Court, *, height: float = 1.0,
                        speed: float = 1.0) -> None:
        """Recompute the effective height and re-clamp into the court.

        Called every fixed step *before* the ball is integrated, so a paddle
        that grows while parked against a wall cannot poke through it.
        """
        self.height_scale = float(height)
        self.speed_scale = float(speed)
        self.h = max(8.0, self.base_h * self.height_scale)
        half = self.h * 0.5
        top_limit = court.top + half
        bottom_limit = court.bottom - half
        if self.y < top_limit:
            self.y = top_limit
        elif self.y > bottom_limit:
            self.y = bottom_limit

    # -- geometry ---------------------------------------------------------
    @property
    def top(self) -> float:
        return self.y - self.h * 0.5

    @property
    def bottom(self) -> float:
        return self.y + self.h * 0.5

    @property
    def center_y(self) -> float:
        return self.y

    def rect(self) -> pygame.Rect:
        """Integer rect used for collision & drawing."""
        return pygame.Rect(
            int(round(self.x - self.w * 0.5)),
            int(round(self.y - self.h * 0.5)),
            int(self.w),
            int(self.h),
        )

    def rect_f(self) -> tuple[float, float, float, float]:
        """Float rect ``(x, y, w, h)`` for precise swept collision."""
        return (self.x - self.w * 0.5, self.y - self.h * 0.5, self.w, self.h)

    def lerp_y(self, alpha: float) -> float:
        """Interpolated centre for rendering between fixed steps."""
        return self.prev_y + (self.y - self.prev_y) * alpha

    # -- simulation -------------------------------------------------------
    def reset(self, court: Court, y: float | None = None) -> None:
        self.y = court.center_y if y is None else y
        self.prev_y = self.y
        self.vel = 0.0
        self.input_axis = 0.0
        # A restart must not inherit last match's powerup modifiers.
        self.height_scale = 1.0
        self.speed_scale = 1.0
        self.h = self.base_h

    def update(self, axis: float, dt: float, court: Court) -> None:
        """Advance one fixed step with a [-1, 1] movement axis."""
        self.prev_y = self.y
        axis = -1.0 if axis < -1.0 else 1.0 if axis > 1.0 else axis
        self.input_axis = axis
        target = axis * PADDLE_SPEED * self.speed_scale
        if abs(axis) < 1e-3:
            # glide to a stop with friction
            if self.vel > 0.0:
                self.vel = max(0.0, self.vel - PADDLE_FRICTION * dt)
            else:
                self.vel = min(0.0, self.vel + PADDLE_FRICTION * dt)
        else:
            delta = target - self.vel
            step = PADDLE_ACCEL * dt
            if abs(delta) > step:
                # Accelerate *towards* the target: step must carry the sign of
                # the error, otherwise an "up" input would push the paddle
                # down (and vice versa).
                self.vel += step if delta > 0.0 else -step
            else:
                # Close enough: land exactly on the target velocity.
                self.vel = target

        self.y += self.vel * dt
        half = self.h * 0.5
        top_limit = court.top + half
        bottom_limit = court.bottom - half
        if self.y < top_limit:
            self.y = top_limit
            self.vel = 0.0
        elif self.y > bottom_limit:
            self.y = bottom_limit
            self.vel = 0.0


class Ball:
    """The ball with previous-step position for render interpolation."""

    __slots__ = ("x", "y", "prev_x", "prev_y", "vx", "vy", "r", "active", "speed_cap_hint")

    def __init__(self, court: Court) -> None:
        self.r = float(BALL_RADIUS)
        self.x = court.center_x
        self.y = court.center_y
        self.prev_x = self.x
        self.prev_y = self.y
        self.vx = 0.0
        self.vy = 0.0
        self.active = False
        self.speed_cap_hint = 0.0

    # -- kinematics -------------------------------------------------------
    @property
    def speed(self) -> float:
        return (self.vx * self.vx + self.vy * self.vy) ** 0.5

    @property
    def pos(self) -> tuple[float, float]:
        return (self.x, self.y)

    def lerp_pos(self, alpha: float) -> tuple[float, float]:
        return (
            self.prev_x + (self.x - self.prev_x) * alpha,
            self.prev_y + (self.y - self.prev_y) * alpha,
        )

    def set_direction(self, speed: float, angle_rad: float) -> None:
        """Point the ball along ``angle_rad`` (0 == +x) at ``speed``."""
        self.vx = math.cos(angle_rad) * speed
        self.vy = math.sin(angle_rad) * speed

    def park(self, court: Court, x: float | None = None, y: float | None = None) -> None:
        """Freeze the ball at a position (used between points)."""
        self.x = court.center_x if x is None else x
        self.y = court.center_y if y is None else y
        self.prev_x = self.x
        self.prev_y = self.y
        self.vx = 0.0
        self.vy = 0.0
        self.active = False

    def begin_step(self) -> None:
        """Snapshot the current position at the start of a fixed step."""
        self.prev_x = self.x
        self.prev_y = self.y

    def integrate(self, dt: float) -> None:
        if not self.active:
            return
        self.x += self.vx * dt
        self.y += self.vy * dt

    # -- serialisation (replay / AI introspection) ------------------------
    def snapshot(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.vx, self.vy)

    def restore(self, snap: tuple[float, float, float, float]) -> None:
        self.x, self.y, self.vx, self.vy = snap
        self.prev_x, self.prev_y = self.x, self.y
