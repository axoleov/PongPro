"""Opponent AI with tunable, *human-feeling* imperfections.

Design notes (why it is not simply "chase the ball y"):

1. **Predictive intercept** - the AI asks the physics layer exactly where the
   ball will cross its own paddle line (wall reflections included), instead of
   chasing the ball's current position.  This is what separates a rally
   partner from a wall.
2. **Reaction delay** - it only re-observes the world every ``reaction``
   seconds.  Between observations it commits to a stale target, so fast
   rallies beat it.
3. **Aim error** - the chosen intercept is perturbed by gaussian noise whose
   sigma grows as difficulty drops, so the ball genuinely escapes it.  The
   paddle still *travels* to where it believes the ball will be: it filters
   one noisy re-read per observation, so a miss reads as "it reached for the
   wrong place" rather than "it never moved at all".
4. **Whiffs** - a per-observation probability of ignoring the shot, *only when
   a read is already in hand*.  A bot that has nothing in hand must look at
   the ball; skipping that read is not a lapse, it is a paddle parked at home
   while the ball sails past it.
5. **Resting behaviour** - when the ball is travelling away, it drifts to a
   home position (with its own error) instead of cheating to centre, giving a
   believable idle sway.

Everything is driven by an injected :class:`~pongpro.core.rng.Rng`, so an AI
match is fully reproducible from its seed (which is what replay playback uses).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.constants import Difficulty, PADDLE_SPEED
from ..core.rng import Rng
from .entities import Ball, Court, Paddle
from .physics import predict_intercept_y


@dataclass(frozen=True, slots=True)
class AIPreset:
    """Tuning knobs for one difficulty level."""

    difficulty: Difficulty
    max_speed: float  # px/s ceiling for this paddle
    reaction: float  # seconds between re-observations
    aim_error: float  # gaussian sigma (px) on the predicted intercept
    whiff_chance: float  # probability of missing a re-observation entirely
    home_error: float  # gaussian sigma (px) for the resting position
    deadzone: float  # px band around the target where it stops moving
    gain: float  # proportional gain converting error to speed
    sway: float  # idle drift amplitude (px) and speed

    @property
    def label(self) -> str:
        return self.difficulty.value.upper()


PRESETS: dict[Difficulty, AIPreset] = {
    Difficulty.EASY: AIPreset(
        difficulty=Difficulty.EASY,
        max_speed=340.0, reaction=0.26, aim_error=110.0,
        whiff_chance=0.16, home_error=60.0, deadzone=32.0,
        gain=2.6, sway=40.0,
    ),
    Difficulty.NORMAL: AIPreset(
        difficulty=Difficulty.NORMAL,
        max_speed=470.0, reaction=0.15, aim_error=78.0,
        whiff_chance=0.07, home_error=38.0, deadzone=24.0,
        gain=3.6, sway=28.0,
    ),
    Difficulty.HARD: AIPreset(
        difficulty=Difficulty.HARD,
        max_speed=610.0, reaction=0.075, aim_error=72.0,
        whiff_chance=0.02, home_error=18.0, deadzone=16.0,
        gain=5.0, sway=15.0,
    ),
    Difficulty.ELITE: AIPreset(
        difficulty=Difficulty.ELITE,
        # PADDLE_SPEED is the *player's* ceiling too: the AI is allowed to use
        # all of it, but not to cheat past it.  The axis each controller emits
        # is clamped to +/-1, so any preset above 640 px/s silently ran at 640 -
        # the old 720 was a lie the preset table told.  ELITE wins on reaction,
        # aim and nerve instead, which is what a player actually feels.
        max_speed=PADDLE_SPEED, reaction=0.035, aim_error=55.0,
        whiff_chance=0.004, home_error=6.0, deadzone=10.0,
        gain=7.0, sway=7.0,
    ),
}


class AIController:
    """Drives one paddle. Call :meth:`update` once per fixed step."""

    __slots__ = (
        "paddle", "preset", "rng", "is_left", "_target", "_observe_in",
        "_sway_phase", "_committed_target", "_last_prediction", "_idle_ticks",
    )

    def __init__(self, paddle: Paddle, preset: AIPreset, rng: Rng) -> None:
        self.paddle = paddle
        self.preset = preset
        self.rng = rng
        self.is_left = paddle.is_left
        self._target = paddle.y
        self._committed_target = paddle.y
        self._observe_in = 0.0
        self._sway_phase = rng.uniform(0.0, math.tau)
        self._last_prediction: float | None = None
        self._idle_ticks = 0

    # -- helpers ----------------------------------------------------------
    @property
    def target_y(self) -> float:
        """Where the AI is currently steering (useful for debug overlays)."""
        return self._committed_target

    @property
    def last_prediction(self) -> float | None:
        return self._last_prediction

    def _court_line(self) -> float:
        """X coordinate of this AI's own paddle line."""
        return self.paddle.x + (18.0 if self.is_left else -18.0)

    def _home(self, court: Court) -> float:
        """Resting position: near centre, nudged by a persistent bias."""
        base = court.center_y + math.sin(self._sway_phase) * self.preset.sway
        bias = self.rng.gauss(0.0, self.preset.home_error * 0.35)
        return base + bias

    # -- main -------------------------------------------------------------
    def reset(self, court: Court) -> None:
        self._target = court.center_y
        self._committed_target = court.center_y
        self._observe_in = 0.0
        self._last_prediction = None

    def update(self, dt: float, ball: Ball, court: Court) -> float:
        """Advance the AI and return the movement axis in [-1, 1]."""
        preset = self.preset
        self._sway_phase += dt * (0.9 + preset.sway * 0.01)

        self._observe_in -= dt
        if self._observe_in <= 0.0:
            self._observe_in = preset.reaction * self.rng.uniform(0.8, 1.25)
            self._reobserve(ball, court)

        # Smooth steering: proportional control with a per-preset speed cap.
        error = self._committed_target - self.paddle.y
        if abs(error) <= preset.deadzone:
            desired = 0.0
        else:
            desired = max(-preset.max_speed, min(preset.max_speed,
                                                  error * preset.gain))
            # Ease off *only* in the last sliver, so the paddle settles on the
            # target instead of buzzing across the deadzone.
            #
            # The previous rule eased from ``deadzone * 4`` with a 0.35 floor,
            # which - combined with an already-proportional command - made the
            # mallet crawl through the whole approach band (EASY worked out at
            # ~23 px/s inside 50 px) and stop dead well short of the ball.  The
            # paddle then *looked* idle while a ball flew past it, which is the
            # "it is not even trying" reading.  Braking here only matters for
            # the ~8 ms of sampling either side of the band: at the worst case
            # (ELITE, 640 px/s) the paddle coasts 33 px on friction, and the
            # deadzone plus the 71 px capture reach absorb that comfortably.
            ease = preset.deadzone * 2.0
            if abs(error) < ease:
                desired *= max(0.75, abs(error) / ease)
        axis = desired / PADDLE_SPEED
        return max(-1.0, min(1.0, axis))

    def _reobserve(self, ball: Ball, court: Court) -> None:
        """Pick a new target: intercept the ball, or drift home."""
        if not ball.active:
            self._committed_target = self._home(court)
            self._last_prediction = None
            return

        incoming = (self.is_left and ball.vx < 0.0) or (
            (not self.is_left) and ball.vx > 0.0
        )
        if not incoming:
            # Ball is heading to the other side: hold a home position rather
            # than cheating towards centre, which reads as "watching the rally".
            self._committed_target = self._home(court)
            self._last_prediction = None
            return

        # A lapse may only skip *re-aiming* when the bot already holds a live
        # read to fall back on.  Whiffing a shot it has not aimed at yet is not
        # a lapse - that is standing still while the ball arrives.  Worse, the
        # stale target at that instant is almost always ``home`` (the ball has
        # just flipped from outgoing to incoming), so an unguarded whiff let the
        # bot watch the rally go by instead of moving at all.
        #
        # Clearing the prediction also guarantees a fresh read on the very next
        # observation: a whiff can cost one reaction interval, never two.
        if self._last_prediction is not None and self.rng.chance(
                self.preset.whiff_chance):
            self._last_prediction = None
            return

        predicted = predict_intercept_y(
            ball.x, ball.y, ball.vx, ball.vy, ball.r,
            self._court_line(), court,
        )
        if predicted is None:
            self._committed_target = self._home(court)
            self._last_prediction = None
            return

        # Imperfect perception: gaussian error + a rare hard whiff.
        error = self.rng.gauss(0.0, self.preset.aim_error)
        if self.rng.chance(self.preset.whiff_chance * 0.6):
            error += self.rng.choice((-1.0, 1.0)) * self.preset.aim_error * 3.0

        target = predicted + error
        half = self.paddle.h * 0.5
        target = max(court.top + half, min(court.bottom - half, target))
        self._committed_target = target
        self._last_prediction = predicted

    # -- serialisation ----------------------------------------------------
    def snapshot(self) -> tuple[float, float, float]:
        return (self._committed_target, self._observe_in, self._sway_phase)

    def restore(self, snap: tuple[float, float, float]) -> None:
        self._committed_target, self._observe_in, self._sway_phase = snap
