"""Pooled particle system for impacts, trails and celebrations.

Design points:

* **No per-frame allocation** - particles are pre-allocated and recycled, so
  the GC never causes frame hitches during a goal explosion.
* **Quality tiers** - the settings screen can dial effects down (or off)
  without touching gameplay code.
* **Cheap drawing** - two ``pygame.draw.circle`` calls per particle instead of
  per-particle alpha surfaces (which would allocate and blit a surface each).
"""

from __future__ import annotations

import math

import pygame

from ..core.constants import Color, ParticleQuality
from ..core.rng import Rng

_QUALITY_SCALE: dict[ParticleQuality, float] = {
    ParticleQuality.OFF: 0.0,
    ParticleQuality.LOW: 0.30,
    ParticleQuality.MEDIUM: 0.60,
    ParticleQuality.HIGH: 1.0,
}
_MAX_BY_QUALITY: dict[ParticleQuality, int] = {
    ParticleQuality.OFF: 0,
    ParticleQuality.LOW: 180,
    ParticleQuality.MEDIUM: 420,
    ParticleQuality.HIGH: 900,
}


class _Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "size", "color",
                 "drag", "gravity", "glow", "active", "ring")

    def __init__(self) -> None:
        self.active = False
        self.x = self.y = self.vx = self.vy = 0.0
        self.life = self.max_life = 0.0
        self.size = 1.0
        self.color = (255, 255, 255)
        self.drag = 0.0
        self.gravity = 0.0
        self.glow = 0.0
        self.ring = False


class ParticleSystem:
    """Fixed-capacity particle pool with helper emitters."""

    def __init__(self, rng: Rng | None = None,
                 quality: ParticleQuality = ParticleQuality.HIGH) -> None:
        self._rng = rng or Rng()
        self.quality = quality
        self._pool: list[_Particle] = []
        self._max = 0
        self._cursor = 0
        self._active_count = 0
        self.set_quality(quality)

    # -- configuration ----------------------------------------------------
    def set_quality(self, quality: ParticleQuality) -> None:
        self.quality = quality
        wanted = _MAX_BY_QUALITY.get(quality, 900)
        if wanted > self._max:
            self._pool.extend(_Particle() for _ in range(wanted - self._max))
        self._max = wanted
        if len(self._pool) > wanted:
            # Trim from the tail, deactivating anything we drop.
            for particle in self._pool[wanted:]:
                particle.active = False
            del self._pool[wanted:]
        if self._cursor >= self._max:
            self._cursor = 0

    @property
    def active_count(self) -> int:
        return self._active_count

    @property
    def capacity(self) -> int:
        return self._max

    # -- emission ---------------------------------------------------------
    def _alloc(self) -> _Particle | None:
        if self._max <= 0:
            return None
        for _ in range(self._max):
            particle = self._pool[self._cursor]
            self._cursor = (self._cursor + 1) % self._max
            if not particle.active:
                return particle
        return None  # pool saturated: drop the effect rather than grow memory

    def spawn(
        self, x: float, y: float, vx: float, vy: float,
        life: float, size: float, color: tuple[int, int, int],
        *, drag: float = 0.0, gravity: float = 0.0, glow: float = 0.0,
        ring: bool = False,
    ) -> None:
        particle = self._alloc()
        if particle is None:
            return
        particle.x, particle.y = x, y
        particle.vx, particle.vy = vx, vy
        particle.life = particle.max_life = life
        particle.size = size
        particle.color = color
        particle.drag = drag
        particle.gravity = gravity
        particle.glow = glow
        particle.ring = ring
        particle.active = True
        self._active_count += 1

    def burst(
        self, x: float, y: float, color: tuple[int, int, int],
        *, count: int, speed: float, life: float = 0.45,
        size: float = 3.0, spread: float = math.tau, direction: float = 0.0,
        drag: float = 2.2, gravity: float = 0.0, glow: float = 0.0,
        scale: float = 1.0, ring: bool = False,
    ) -> None:
        """Omnidirectional (or cone) burst of ``count * quality`` particles.

        ``ring`` spaces the particles evenly around the cone and evens out
        their speeds, so the cloud expands as a visible *ring* rather than a
        fuzzy blob.  That is the entire visual identity of the RING and STARS
        impact skins, so the jitter is turned down instead of merely dropped.
        """
        actual = int(count * _QUALITY_SCALE.get(self.quality, 1.0) * scale)
        if actual <= 0:
            return
        step = spread / actual
        for index in range(actual):
            if ring:
                angle = (direction - spread * 0.5
                         + step * (index + 0.5)
                         + self._rng.uniform(-0.05, 0.05))
                magnitude = speed * self._rng.uniform(0.94, 1.06)
            else:
                angle = direction + self._rng.uniform(-spread * 0.5,
                                                     spread * 0.5)
                magnitude = speed * self._rng.uniform(0.35, 1.15)
            self.spawn(
                x, y,
                math.cos(angle) * magnitude, math.sin(angle) * magnitude,
                life * (self._rng.uniform(0.9, 1.1) if ring
                        else self._rng.uniform(0.6, 1.25)),
                size * (self._rng.uniform(0.9, 1.1) if ring
                        else self._rng.uniform(0.6, 1.3)),
                color, drag=drag, gravity=gravity, glow=glow,
            )

    # -- named effects ----------------------------------------------------
    def goal_burst(self, x: float, y: float, color: tuple[int, int, int]) -> None:
        self.burst(x, y, color, count=70, speed=620, life=0.75, size=4.2,
                   drag=1.7, glow=1.6)
        self.burst(x, y, Color.BALL, count=30, speed=420, life=0.6, size=3.0,
                   drag=1.9, glow=1.2, scale=0.6)

    def trail_dot(self, x: float, y: float, color: tuple[int, int, int],
                  speed: float) -> None:
        """Soft glowing dot left behind a fast-moving ball."""
        self.spawn(x, y, 0.0, 0.0, 0.26, 4.6 + min(3.0, speed * 0.003),
                   color, drag=0.0, glow=1.0)

    def confetti(self, x: float, y: float) -> None:
        palette = (Color.P1, Color.P2, Color.BALL, Color.ACCENT, Color.GOLD)
        for i in range(4):
            color = palette[i % len(palette)]
            self.burst(x, y, color, count=32, speed=520, life=1.0, size=3.4,
                       drag=1.4, gravity=260.0, glow=0.7)

    # -- frame ------------------------------------------------------------
    def update(self, dt: float) -> None:
        if self._active_count == 0:
            return
        active = 0
        for particle in self._pool:
            if not particle.active:
                continue
            particle.life -= dt
            if particle.life <= 0.0:
                particle.active = False
                continue
            if particle.drag:
                damping = math.exp(-particle.drag * dt)
                particle.vx *= damping
                particle.vy *= damping
            particle.vy += particle.gravity * dt
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            active += 1
        self._active_count = active

    def draw(self, surface: pygame.Surface, offset: tuple[float, float] = (0.0, 0.0)) -> None:
        ox, oy = offset
        if self._active_count == 0:
            return
        draw_circle = pygame.draw.circle
        for particle in self._pool:
            if not particle.active:
                continue
            t = particle.life / particle.max_life if particle.max_life > 0 else 0.0
            # Ease-out fade: bright at birth, quickly settling.
            brightness = t * t * (3.0 - 2.0 * t)
            r, g, b = particle.color
            color = (
                max(0, min(255, int(r * brightness))),
                max(0, min(255, int(g * brightness))),
                max(0, min(255, int(b * brightness))),
            )
            px = particle.x + ox
            py = particle.y + oy
            radius = max(1, int(particle.size * (0.45 + 0.55 * t)))
            if particle.glow > 0.0 and brightness > 0.15:
                # soft halo: dim, larger circle underneath
                halo = int(radius * 2.4)
                dim = (color[0] // 4, color[1] // 4, color[2] // 4)
                draw_circle(surface, dim, (int(px), int(py)), halo)
            if particle.ring:
                pygame.draw.circle(surface, color, (int(px), int(py)), radius, 1)
            else:
                draw_circle(surface, color, (int(px), int(py)), radius)

    def clear(self) -> None:
        for particle in self._pool:
            particle.active = False
        self._active_count = 0
