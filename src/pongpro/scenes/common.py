"""Shared scene furniture: backdrops, panels, attract-mode ball, formatting.

Heavy static surfaces (vignettes, star fields) are built once per size/seed and
memoised at module level, so menus cost one ``blit`` per frame instead of
rebuilding gradients.
"""

from __future__ import annotations

import math
import random

import pygame

from ..core.constants import Color, LOGICAL_H, LOGICAL_W
from ..core.rng import Rng
from ..economy.catalog import BackgroundLook
from ..rendering.fonts import FontManager
from ..rendering.skins import CLASSIC_BACKGROUND, paint_backdrop, paint_court

_VIGNETTE_CACHE: dict[tuple, pygame.Surface] = {}
_STAR_CACHE: dict[int, list[tuple[float, float, float, float]]] = {}


def format_duration(seconds: float) -> str:
    """12.3 -> '12s', 75 -> '1m 15s', 3725 -> '1h 02m'."""
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60:02d}s"
    return f"{total // 3600}h {(total % 3600) // 60:02d}m"


def format_percent(value: float) -> str:
    return f"{max(0.0, min(1.0, value)) * 100.0:.0f}%"


class AttractBall:
    """Slow bouncing ball with a fading trail (menu background life)."""

    def __init__(self, rng: Rng | None = None,
                 bounds: pygame.Rect | None = None) -> None:
        self._rng = rng or Rng()
        self.bounds = bounds or pygame.Rect(48, 48, LOGICAL_W - 96, LOGICAL_H - 96)
        b = self.bounds
        self.x = float(self._rng.randint(b.x, b.right))
        self.y = float(self._rng.randint(b.y, b.bottom))
        speed = 250.0
        angle = self._rng.uniform(-0.6, 0.6) + (
            0.0 if self._rng.chance(0.5) else math.pi)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.r = 9.0
        self.trail: list[list[float]] = []
        self._tick = 0

    def update(self, dt: float) -> None:
        self.x += self.vx * dt
        self.y += self.vy * dt
        left, right = self.bounds.x + self.r, self.bounds.right - self.r
        top, bottom = self.bounds.y + self.r, self.bounds.bottom - self.r
        if self.x < left:
            self.x, self.vx = left, abs(self.vx)
        elif self.x > right:
            self.x, self.vx = right, -abs(self.vx)
        if self.y < top:
            self.y, self.vy = top, abs(self.vy)
        elif self.y > bottom:
            self.y, self.vy = bottom, -abs(self.vy)

        self._tick += 1
        if self._tick % 2 == 0:
            self.trail.append([self.x, self.y, 1.0])
        alive: list[list[float]] = []
        for px, py, life in self.trail:
            life -= dt * 3.4
            if life > 0.0:
                alive.append([px, py, life])
        self.trail = alive[-16:]

    def draw(self, surface: pygame.Surface, color: tuple[int, int, int]) -> None:
        for px, py, life in self.trail:
            radius = max(1, int(self.r * life * 0.85))
            c = (int(color[0] * life * 0.7),
                 int(color[1] * life * 0.7),
                 int(color[2] * life * 0.7))
            pygame.draw.circle(surface, c, (int(px), int(py)), radius)
        pygame.draw.circle(surface, (245, 248, 255),
                           (int(self.x), int(self.y)), max(3, int(self.r - 3)))


def get_vignette(size: tuple[int, int], strength: int = 70) -> pygame.Surface:
    """Radial darkening overlay, generated once per (size, strength)."""
    key = (size, strength)
    cached = _VIGNETTE_CACHE.get(key)
    if cached is not None:
        return cached

    w, h = size
    overlay = pygame.Surface(size, pygame.SRCALPHA)
    radius = math.hypot(w, h) * 0.62
    cx, cy = w * 0.5, h * 0.5
    # Build a radial falloff with concentric translucent rings (cheap, cached).
    steps = 26
    for i in range(steps, 0, -1):
        t = i / steps
        r = radius * t
        alpha = int(strength * (t ** 1.6))
        if alpha <= 0:
            continue
        ring = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.circle(ring, (0, 0, 0, min(255, alpha)),
                           (int(cx), int(cy)), int(r))
        overlay.blit(ring, (0, 0))
    _VIGNETTE_CACHE[key] = overlay
    return overlay


def draw_vignette(surface: pygame.Surface, strength: int = 70) -> None:
    surface.blit(get_vignette(surface.get_size(), strength), (0, 0))


def get_stars(seed: int, width: int, height: int) -> list[tuple[float, float, float, float]]:
    """Deterministic star positions (x, y, phase, speed) - cached."""
    key = (seed, width, height)
    cached = _STAR_CACHE.get(key)
    if cached is not None:
        return cached
    rand = random.Random(seed)
    stars = [
        (rand.random() * width, rand.random() * height,
         rand.random() * math.tau, 0.5 + rand.random() * 1.8)
        for _ in range(80)
    ]
    _STAR_CACHE[key] = stars
    return stars


def draw_starfield(surface: pygame.Surface, t: float, seed: int = 1234) -> None:
    """Twinkling, slowly drifting dots; deterministic given ``t``."""
    w, h = surface.get_size()
    for bx, by, phase, speed in get_stars(seed, w, h):
        twinkle = 0.30 + 0.70 * (0.5 + 0.5 * math.sin(t * speed + phase))
        x = int((bx + t * 9.0 * (0.35 + speed * 0.25)) % w)
        y = int(by)
        c = (int(96 * twinkle), int(118 * twinkle), int(168 * twinkle))
        surface.set_at((x, y), c)


def draw_panel(surface: pygame.Surface, rect: pygame.Rect,
               *, accent: tuple[int, int, int] = Color.P1,
               alpha: int = 215, title: str | None = None,
               fonts: FontManager | None = None) -> None:
    """Translucent rounded panel with a glowing accent border."""
    panel = pygame.Surface((max(1, rect.w), max(1, rect.h)), pygame.SRCALPHA)
    panel.fill((*Color.PANEL, alpha))
    surface.blit(panel, rect.topleft)
    pygame.draw.rect(surface, Color.blend(Color.PANEL_LIGHT, accent, 0.35),
                     rect, width=1, border_radius=12)
    if title and fonts is not None:
        heading = fonts.render(title.upper(), 15, accent, bold=True)
        surface.blit(heading, (rect.x + 20, rect.y + 16))


def draw_title(surface: pygame.Surface, text: str, fonts: FontManager, *,
               y: int = 64, size: int = 84,
               color: tuple[int, int, int] = Color.TEXT,
               center_x: int | None = None) -> pygame.Rect:
    """Large outlined title; centred horizontally when ``center_x`` is None."""
    rendered = fonts.render(text, size, color, bold=True, outline=3,
                            outline_color=Color.BG)
    if center_x is None:
        x = (surface.get_width() - rendered.get_width()) // 2
    else:
        x = center_x - rendered.get_width() // 2
    surface.blit(rendered, (x, y))
    return pygame.Rect(x, y, rendered.get_width(), rendered.get_height())


def draw_backdrop(surface: pygame.Surface, t: float, *,
                  seed: int = 1234, vignette: int = 70,
                  look: BackgroundLook | None = None) -> None:
    """Standard animated menu background: gradient, stars, vignette.

    ``look`` lets a scene paint the equipped background skin; the arguments
    are kept for the callers that only care about seed/vignette.
    """
    if look is None:
        surface.fill(Color.BG)
        draw_starfield(surface, t, seed)
        draw_vignette(surface, vignette)
        return
    paint_backdrop(surface, t, look, seed=seed)


# --------------------------------------------------------------------------
# Court
# --------------------------------------------------------------------------
_COURT_CACHE: dict[str, pygame.Surface] = {}


def render_court(court, look: BackgroundLook | None = None) -> pygame.Surface:  # type: ignore[no-untyped-def]
    """Static arena art, built once per (geometry, background skin) and cached.

    Contains: background, playfield fill with vertical shading, walls,
    centre dashed line, centre circle, goal posts and corner brackets.
    """
    from ..gameplay.entities import Court  # local import keeps module ordering sane

    assert isinstance(court, Court)
    look = look if look is not None else CLASSIC_BACKGROUND
    key = f"{court.left}:{court.right}:{court.top}:{court.bottom}:{look.style.value}"
    cached = _COURT_CACHE.get(key)
    if cached is not None:
        return cached.copy()

    surface = pygame.Surface((LOGICAL_W, LOGICAL_H))
    paint_court(surface, court, look)

    _COURT_CACHE[key] = surface
    return surface.copy()
