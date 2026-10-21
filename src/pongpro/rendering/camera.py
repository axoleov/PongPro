"""Camera effects: trauma-based screen shake with Perlin-ish wobble.

Trauma (0..1) is *added* by impacts and decays exponentially, so a big goal
shakes hard then settles, while a wall tap adds only a twitch.  Offset is
derived from smoothed noise rather than raw random values, which reads as a
weighty shake instead of a vibrating one.
"""

from __future__ import annotations

import math

from ..core.rng import Rng


class Camera:
    """Produces an (ox, oy) pixel offset for the current frame."""

    __slots__ = ("_trauma", "_time", "_rng", "_max_offset", "_noise_phase",
                 "_offset", "enabled")

    def __init__(self, rng: Rng | None = None, max_offset: float = 16.0,
                 enabled: bool = True) -> None:
        self._rng = rng or Rng()
        self._max_offset = max_offset
        self.enabled = enabled
        self._trauma = 0.0
        self._time = 0.0
        self._noise_phase = self._rng.uniform(0.0, 100.0)
        self._offset = (0.0, 0.0)

    @property
    def trauma(self) -> float:
        return self._trauma

    @property
    def offset(self) -> tuple[float, float]:
        return self._offset

    def add_trauma(self, amount: float) -> None:
        """``amount`` in 0..1; clamped so a single hit cannot explode."""
        if not self.enabled:
            return
        self._trauma = max(self._trauma, min(1.0, amount))

    def kick(self, direction_y: float = 0.0) -> None:
        """Small directional jolt used on paddle hits."""
        self.add_trauma(0.22 + abs(direction_y) * 0.00018)
        if direction_y:
            self._offset = (self._offset[0], self._offset[1])

    def decay(self, dt: float) -> None:
        """Exponential falloff: shake amplitude = trauma^2."""
        self._trauma = max(0.0, self._trauma - dt * 1.7)
        self._time += dt

    def compute(self, dt: float) -> tuple[float, float]:
        """Advance time and refresh :attr:`offset`; returns the offset."""
        self.decay(dt)
        if not self.enabled or self._trauma <= 0.001:
            self._offset = (0.0, 0.0)
            return self._offset

        amp = self._trauma * self._trauma * self._max_offset
        t = self._time * 34.0 + self._noise_phase
        # Layered sines approximate smooth noise without a table.
        ox = (math.sin(t) + 0.5 * math.sin(t * 2.13 + 1.1)) * amp
        oy = (math.cos(t * 1.07 + 0.6) + 0.5 * math.sin(t * 2.7 + 2.3)) * amp
        self._offset = (ox, oy)
        return self._offset

    def reset(self) -> None:
        self._trauma = 0.0
        self._offset = (0.0, 0.0)
