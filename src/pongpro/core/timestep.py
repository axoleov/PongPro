"""Fixed-timestep clock with render interpolation.

Implements the classic "Fix Your Timestep!" accumulator loop:

* physics always advances by exactly ``fixed_dt`` (deterministic, testable),
* the leftover accumulator produces an ``alpha`` used to interpolate rendering
  between the previous and current simulation states (no micro-stutter),
* frame time is clamped and sub-steps are capped so a hitch cannot trigger the
  "spiral of death".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .constants import FIXED_DT, MAX_FRAME_TIME, MAX_SUBSTEPS


@dataclass(slots=True)
class FixedStepClock:
    """Accumulator wrapping a fixed simulation rate."""

    fixed_dt: float = FIXED_DT
    max_frame_time: float = MAX_FRAME_TIME
    max_substeps: int = MAX_SUBSTEPS

    accumulator: float = 0.0
    total_simulated: float = 0.0  # seconds of simulated world time
    ticks: int = 0  # total physics steps executed
    dropped_steps: int = 0  # steps skipped because the sub-step cap was hit
    frame_time_ema: float = 1.0 / 60.0  # smoothed measured frame duration
    _alpha: float = 0.0
    _spiral_clamped: bool = field(default=False, repr=False)

    def advance(self, frame_time: float) -> int:
        """Consume a rendered frame; return how many fixed steps to run."""
        if frame_time < 0.0:
            frame_time = 0.0
        # Exponential moving average gives a stable FPS read-out for the HUD.
        self.frame_time_ema += (frame_time - self.frame_time_ema) * 0.08
        self._spiral_clamped = frame_time > self.max_frame_time
        if self._spiral_clamped:
            frame_time = self.max_frame_time

        self.accumulator += frame_time
        steps = 0
        while self.accumulator >= self.fixed_dt and steps < self.max_substeps:
            self.accumulator -= self.fixed_dt
            self.ticks += 1
            steps += 1

        if self.accumulator >= self.fixed_dt:
            # Cap reached: drop the backlog instead of grinding forever.
            backlog = int(self.accumulator / self.fixed_dt)
            self.dropped_steps += backlog
            self.accumulator -= backlog * self.fixed_dt
            self.accumulator = min(self.accumulator, self.fixed_dt)

        self._alpha = self.accumulator / self.fixed_dt if self.fixed_dt > 0 else 0.0
        self.total_simulated += steps * self.fixed_dt
        return steps

    @property
    def alpha(self) -> float:
        """Interpolation factor in [0, 1] between previous and current state."""
        return self._alpha

    @property
    def was_clamped(self) -> bool:
        """True when the last frame exceeded ``max_frame_time``."""
        return self._spiral_clamped

    @property
    def measured_fps(self) -> float:
        """Smoothed frames-per-second estimate (0 while idle)."""
        return 1.0 / self.frame_time_ema if self.frame_time_ema > 1e-6 else 0.0
