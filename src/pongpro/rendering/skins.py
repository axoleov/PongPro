"""Turning catalog *looks* into pixels: balls, paddles, trails and impacts.

This is the only module allowed to interpret
:class:`~pongpro.economy.catalog` look dataclasses.  Keeping the dispatch in
one place means adding a cosmetic is a catalog entry plus one ``if`` branch
here - the gameplay scene never learns that skins exist.

Every drawer is a pure function of (surface, geometry, look) so the shop can
render a live preview with exactly the code that will draw it in a match.
"""

from __future__ import annotations

import math

import pygame

from ..core.constants import Color
from ..economy.catalog import (
    BackdropStyle,
    BallLook,
    BallPattern,
    BackgroundLook,
    ImpactLook,
    ImpactStyle,
    PaddleLook,
    PaddlePattern,
    TrailLook,
    TrailStyle,
)

#: The stock background, used whenever nothing has been equipped yet.
CLASSIC_BACKGROUND = BackgroundLook()


# --------------------------------------------------------------------------
# Shared sprites
# --------------------------------------------------------------------------
def make_glow(color: tuple[int, int, int], radius: int) -> pygame.Surface:
    """Radial glow sprite.  Built once per colour and cached by the caller."""
    size = radius * 2
    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    cx = cy = radius
    steps = 22
    for i in range(steps, 0, -1):
        t = i / steps
        r = radius * t
        alpha = int(150 * (1.0 - t) ** 1.7)
        if alpha <= 0:
            continue
        pygame.draw.circle(surface, (*color, alpha), (cx, cy), int(r))
    return surface


_GLOW_CACHE: dict[tuple[tuple[int, int, int], int], pygame.Surface] = {}


def glow_sprite(color: tuple[int, int, int], radius: int) -> pygame.Surface:
    """Memoised :func:`make_glow` (a match builds the same three sprites)."""
    key = (tuple(color), int(radius))
    cached = _GLOW_CACHE.get(key)
    if cached is None:
        cached = make_glow(color, int(radius))
        _GLOW_CACHE[key] = cached
    return cached


def clear_glow_cache() -> None:
    _GLOW_CACHE.clear()


# --------------------------------------------------------------------------
# Ball
# --------------------------------------------------------------------------
def draw_ball(surface: pygame.Surface, x: float, y: float, radius: int,
              look: BallLook, *, glow: pygame.Surface | None = None,
              glow_boost: float = 1.0) -> None:
    """Draw one ball at ``(x, y)`` using ``look``'s pattern.

    ``glow`` is an optional pre-rendered halo sprite; ``glow_boost`` scales it
    with ball speed so a fast ball reads as more dangerous.
    """
    r = max(2, int(radius))
    px, py = int(x), int(y)

    if glow is not None and look.glow > 0.0:
        size = int(glow.get_width() * glow_boost * look.glow)
        if size > 2:
            sprite = (pygame.transform.smoothscale(glow, (size, size))
                      if size != glow.get_width() else glow)
            surface.blit(sprite, (px - sprite.get_width() // 2,
                                  py - sprite.get_height() // 2))

    pattern = look.pattern
    pygame.draw.circle(surface, look.fill, (px, py), r)

    if pattern is BallPattern.SOLID:
        pygame.draw.circle(surface, look.core, (px, py), max(2, r - 4))
        pygame.draw.circle(surface, look.accent,
                           (int(x - r * 0.35), int(y - r * 0.35)), 2)
    elif pattern is BallPattern.DOT:
        pygame.draw.circle(surface, look.core, (px, py), max(2, int(r * 0.45)))
        pygame.draw.circle(surface, look.accent, (px, py), max(1, r // 4))
    elif pattern is BallPattern.RING:
        pygame.draw.circle(surface, look.core, (px, py), max(2, r - 4))
        pygame.draw.circle(surface, look.accent, (px, py), max(2, r - 1),
                           max(2, r // 3))
    elif pattern is BallPattern.STRIPES:
        # Two half-discs that read as rotation.
        #
        # Both halves have to be *clipped to the disc*.  The old code painted
        # the lower half with a plain rect the width of the bounding box, so
        # it spilled past the circle on both sides and left the ball with a
        # flat, square-cornered base - EMBER shipped looking like a dome
        # rather than a ball.  Drawing the upper half into a surface only
        # half-disc tall does the clipping for free, and the rim sits one
        # radius inward so the silhouette is exactly the circle.
        size = r * 2 + 4
        clip = pygame.Surface((size, size), pygame.SRCALPHA)
        centre = size // 2                      # = r + 2: two clear pixels
        pygame.draw.circle(clip, look.accent, (centre, centre), r)

        top = pygame.Surface((size, centre + 1), pygame.SRCALPHA)
        pygame.draw.circle(top, look.core, (centre, centre), r)
        clip.blit(top, (0, 0))

        pygame.draw.circle(clip, look.fill, (centre, centre),
                           max(2, r - 1), 2)
        surface.blit(clip, (px - centre, py - centre))
        pygame.draw.circle(surface, look.accent,
                           (int(x - r * 0.35), int(y - r * 0.35)), 2)
    elif pattern is BallPattern.ORB:
        pygame.draw.circle(surface, look.core, (px, py), max(2, int(r * 0.62)))
        pygame.draw.circle(surface, look.accent, (px, py), max(2, r - 1), 2)
        pygame.draw.circle(surface, Color.blend(look.accent, (255, 255, 255), 0.6),
                           (int(x - r * 0.3), int(y - r * 0.3)), 2)
    elif pattern is BallPattern.NOVA:
        # Radiating spokes plus a bright core: reads as a small star.
        for i in range(6):
            angle = i * math.tau / 6.0
            ex = x + math.cos(angle) * (r - 1)
            ey = y + math.sin(angle) * (r - 1)
            pygame.draw.line(surface, look.accent, (px, py),
                             (int(ex), int(ey)), 2)
        pygame.draw.circle(surface, look.core, (px, py), max(2, int(r * 0.5)))
        pygame.draw.circle(surface, look.fill, (px, py), max(1, r // 3))


# --------------------------------------------------------------------------
# Paddle
# --------------------------------------------------------------------------
def draw_paddle(surface: pygame.Surface, rect: pygame.Rect,
                team: tuple[int, int, int], look: PaddleLook,
                *, glow: pygame.Surface | None = None) -> None:
    """Draw one paddle.

    ``team`` keeps the side identity (cyan left, pink right).  ``look.tint``
    blends it toward the skin's body colour, and the outline always mixes body
    and team so the two paddles never become indistinguishable - even with the
    legendary full-tint skins.
    """
    body = Color.blend(team, look.body, look.tint)
    accent = Color.blend(body, look.accent, max(0.15, look.tint))
    outline = Color.blend(body, team, 0.55)

    if glow is not None and look.glow > 0.0:
        size = int(glow.get_width() * look.glow)
        if size > 2:
            sprite = (pygame.transform.smoothscale(glow, (size, size))
                      if size != glow.get_width() else glow)
            surface.blit(sprite, (rect.centerx - sprite.get_width() // 2,
                                  rect.centery - sprite.get_height() // 2))

    pattern = look.pattern
    pygame.draw.rect(surface, body, rect, border_radius=7)

    inner = rect.inflate(-6, -14)
    if pattern is PaddlePattern.SOLID:
        if inner.w > 0 and inner.h > 0:
            pygame.draw.rect(surface, Color.blend(body, (255, 255, 255), 0.55),
                             inner, border_radius=4)
    elif pattern is PaddlePattern.STRIPES:
        band = max(4, rect.h // 6)
        for y in range(rect.y + 4, rect.bottom - 4, band * 2):
            pygame.draw.rect(surface, accent,
                             (rect.x + 3, y, rect.w - 6, band),
                             border_radius=2)
    elif pattern is PaddlePattern.NEON:
        rail = max(2, rect.w // 5)
        pygame.draw.rect(surface, accent,
                         (rect.x + 2, rect.y + 3, rail, rect.h - 6),
                         border_radius=2)
        pygame.draw.rect(surface, accent,
                         (rect.right - 2 - rail, rect.y + 3, rail, rect.h - 6),
                         border_radius=2)
    elif pattern is PaddlePattern.SPLIT:
        if inner.w > 0 and inner.h > 0:
            top = inner.copy()
            bottom = inner.copy()
            top.height = max(1, inner.h // 2)
            bottom.y = top.bottom
            bottom.height = max(1, inner.bottom - top.bottom)
            pygame.draw.rect(surface, Color.blend(body, (255, 255, 255), 0.45),
                             top, border_radius=4)
            pygame.draw.rect(surface, accent, bottom, border_radius=4)
    elif pattern is PaddlePattern.TECH:
        seg = max(6, rect.h // 7)
        for y in range(rect.y + 5, rect.bottom - 5, seg):
            height = max(2, seg - 4)
            if y + height > rect.bottom - 4:
                height = rect.bottom - 4 - y
            if height <= 0:
                continue
            pygame.draw.rect(surface, accent,
                             (rect.x + 3, y, rect.w - 6, height),
                             border_radius=2)

    pygame.draw.rect(surface, outline, rect, width=1, border_radius=7)


# --------------------------------------------------------------------------
# Trail
# --------------------------------------------------------------------------
def draw_trail(surface: pygame.Surface, points: list[list[float]],
               look: TrailLook, ball_radius: float) -> None:
    """Draw the fading record of the ball's recent positions.

    ``points`` is the scene's ``[x, y, life]`` history (life runs 1.0 -> 0.0).
    """
    if not points:
        return
    style = look.style
    base = max(2, int(ball_radius * 0.9 * look.width_scale))

    if style is TrailStyle.RIBBON:
        _draw_ribbon(surface, points, look, base)
        return

    for index, (px, py, life) in enumerate(points):
        if life <= 0.0:
            continue
        t = life
        radius = max(2, int(base * t))
        if style is TrailStyle.COMET:
            # Tail is `look.color`, head is `look.color2`.
            head = (index + 1) / len(points)
            color = Color.blend(look.color, look.color2, head)
        elif style is TrailStyle.NEON:
            color = Color.blend(look.color, (255, 255, 255), t * 0.4)
        else:
            color = look.color
        shaded = (int(color[0] * t * 0.7), int(color[1] * t * 0.7),
                  int(color[2] * t * 0.7))
        if style is TrailStyle.SPARK and index % 2:
            # Hollow, jittered rings read as stray static.
            pygame.draw.circle(surface, shaded, (int(px), int(py)), radius, 1)
        else:
            pygame.draw.circle(surface, shaded, (int(px), int(py)), radius)
        if style is TrailStyle.NEON and look.glow > 1.0:
            halo = (int(shaded[0] * 0.3), int(shaded[1] * 0.3),
                    int(shaded[2] * 0.3))
            pygame.draw.circle(surface, halo, (int(px), int(py)),
                               max(2, int(radius * 1.9)))


def _draw_ribbon(surface: pygame.Surface, points: list[list[float]],
                 look: TrailLook, base: int) -> None:
    """Continuous tapering strip through the sample points."""
    alive = [(px, py, life) for px, py, life in points if life > 0.0]
    if len(alive) < 2:
        return
    for i in range(len(alive) - 1):
        x0, y0, l0 = alive[i]
        x1, y1, l1 = alive[i + 1]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        nx, ny = -dy / length, dx / length
        w0 = max(1.0, base * l0 * 0.6)
        w1 = max(1.0, base * l1 * 0.6)
        head = (i + 1) / (len(alive) - 1)
        color = Color.blend(look.color, look.color2, head)
        shaded = (int(color[0] * l0 * 0.85), int(color[1] * l0 * 0.85),
                  int(color[2] * l0 * 0.85))
        quad = [
            (x0 + nx * w0, y0 + ny * w0),
            (x1 + nx * w1, y1 + ny * w1),
            (x1 - nx * w1, y1 - ny * w1),
            (x0 - nx * w0, y0 - ny * w0),
        ]
        pygame.draw.polygon(surface, shaded, [(int(a), int(b)) for a, b in quad])


# --------------------------------------------------------------------------
# Impacts
# --------------------------------------------------------------------------
def emit_impact(particles, look: ImpactLook, x: float, y: float,  # type: ignore[no-untyped-def]
                color: tuple[int, int, int], *,
                outgoing: float | None = None,
                normal: float | None = None,
                scale: float = 1.0) -> None:
    """Emit ``look``'s contact effect at ``(x, y)``.

    ``outgoing`` (a paddle return) or ``normal`` (a wall bounce) select the
    cone; without either the burst is omnidirectional.
    """
    if look.colors:
        primary = look.colors[0]
    else:
        primary = color
    count = look.count_scale * scale
    speed = 440.0 * look.speed_scale

    if outgoing is not None:
        direction = 0.0 if outgoing > 0 else math.pi
        spread = 2.3
    elif normal is not None:
        direction = math.pi / 2 if normal > 0 else -math.pi / 2
        spread = 2.1
    else:
        direction = 0.0
        spread = math.tau

    style = look.style
    if style is ImpactStyle.RING:
        for radius_life in (0.20, 0.42):
            particles.burst(x, y, primary, count=int(10 * count), speed=speed * 0.5,
                            life=radius_life + 0.2, size=2.4,
                            spread=spread, direction=direction,
                            drag=4.0, glow=look.glow, ring=True)
    elif style is ImpactStyle.SHARDS:
        particles.burst(x, y, primary, count=int(20 * count), speed=speed * 1.1,
                        life=0.42, size=4.2, spread=spread, direction=direction,
                        drag=3.4, gravity=90.0, glow=look.glow * 0.5)
    elif style is ImpactStyle.PULSE:
        particles.burst(x, y, primary, count=int(16 * count), speed=speed * 0.35,
                        life=0.55, size=5.0, spread=spread, direction=direction,
                        drag=2.0, glow=look.glow * 1.4)
    elif style is ImpactStyle.STARS:
        particles.burst(x, y, primary, count=int(14 * count), speed=speed * 0.6,
                        life=0.65, size=3.4, spread=spread, direction=direction,
                        drag=1.8, glow=look.glow, ring=True)
    elif style is ImpactStyle.RAINBOW:
        palette = look.colors or (Color.BALL,)
        for i, palette_color in enumerate(palette):
            particles.burst(x, y, palette_color, count=max(2, int(6 * count)),
                            speed=speed * (0.7 + 0.08 * i), life=0.5,
                            size=3.2, spread=spread, direction=direction,
                            drag=2.2, gravity=40.0 if i % 2 else 0.0,
                            glow=look.glow)
    else:  # SPARK and anything unrecognised -> the classic burst
        particles.burst(x, y, primary, count=int(24 * count), speed=speed,
                        life=0.36, size=3.0, spread=spread, direction=direction,
                        drag=2.6, glow=1.2 * look.glow)

    # A secondary tint keeps the player's team colour visible in every skin.
    if look.colors and color not in look.colors:
        particles.burst(x, y, color, count=int(8 * count), speed=speed * 0.6,
                        life=0.3, size=2.6, spread=spread, direction=direction,
                        drag=3.0, glow=0.6 * look.glow)


# --------------------------------------------------------------------------
# Backdrops & courts
# --------------------------------------------------------------------------
def paint_backdrop(surface: pygame.Surface, t: float, look: BackgroundLook,
                   *, seed: int = 1234) -> None:
    """Fill ``surface`` with the themed menu background."""
    # Deferred: `scenes.common` imports this module at import time.
    from ..scenes.common import draw_starfield, draw_vignette

    surface.fill(look.bg)
    _paint_backdrop_decoration(surface, look, t)
    if look.starfield:
        draw_starfield(surface, t, seed)
    draw_vignette(surface, look.vignette)


def _paint_backdrop_decoration(surface: pygame.Surface, look: BackgroundLook,
                               t: float) -> None:
    """Style-specific background motion, drawn under the star field."""
    w, h = surface.get_size()
    style = look.style

    if style is BackdropStyle.GRID or look.grid:
        spacing = 64
        offset = int(t * 18) % spacing
        for x in range(-spacing, w + spacing, spacing):
            pygame.draw.line(surface, look.line_soft, (x + offset, 0),
                             (x + offset, h), 1)
        for y in range(-spacing, h + spacing, spacing):
            pygame.draw.line(surface, look.line_soft, (0, y + offset),
                             (w, y + offset), 1)
    elif style is BackdropStyle.AURORA:
        for band, (colour, phase) in enumerate(
                ((look.line, 0.0), (look.accent, 1.7), (look.line_soft, 3.1))):
            points = []
            for x in range(0, w + 32, 32):
                y = (h * 0.30) + band * 46 + math.sin(x * 0.006 + t * 0.7 + phase) * 42
                points.append((x, int(y)))
            for i in range(len(points) - 1):
                pygame.draw.line(surface, Color.blend(colour, look.bg, 0.45),
                                 points[i], points[i + 1], 3)
    elif style is BackdropStyle.SUNSET:
        bands = 5
        for i in range(bands):
            frac = i / max(1, bands - 1)
            colour = Color.blend(look.bg, look.line, frac * 0.5)
            y = int(h * (0.42 + frac * 0.30))
            pygame.draw.rect(surface, colour, (0, y, w, int(h * 0.30 / bands) + 2))
        pygame.draw.circle(surface, look.accent, (w // 2, int(h * 0.62)),
                           int(90 + math.sin(t * 0.5) * 4))
    elif style is BackdropStyle.ARCADE:
        for y in range(0, h, 4):
            if (y // 4) % 2 == 0:
                pygame.draw.rect(surface, (0, 0, 0), (0, y, w, 2))
    elif style is BackdropStyle.VOID:
        for i in range(3):
            radius = 120 + i * 70 + int(math.sin(t * 0.6 + i) * 12)
            pygame.draw.circle(surface, Color.blend(look.line, look.bg, 0.75),
                               (w // 2, h // 2), radius, 1)
    elif style is BackdropStyle.CANDY:
        for i in range(6):
            cx = int((w * (i + 0.5) / 6) + math.sin(t * 0.8 + i) * 40)
            cy = int(h * 0.5 + math.cos(t * 0.6 + i * 1.3) * 120)
            pygame.draw.circle(surface, Color.blend(look.accent, look.bg, 0.72),
                               (cx, cy), 46, 3)
    elif style is BackdropStyle.NOIR:
        pygame.draw.rect(surface, (0, 0, 0), (0, int(h * 0.78), w, h))


def paint_court(surface: pygame.Surface, court, look: BackgroundLook) -> None:  # type: ignore[no-untyped-def]
    """Draw the arena art for ``court`` onto ``surface`` using ``look``."""
    rect = court.to_rect()
    surface.fill(look.bg)
    pygame.draw.rect(surface, look.court, rect)

    # Vertical shading: darker near the walls, brighter through the middle.
    shade = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    half_h = max(1, rect.h * 0.5)
    band = 6
    for y in range(0, rect.h, band):
        t = abs((y + band * 0.5) - half_h) / half_h
        alpha = int(58 * (t ** 1.5))
        if alpha <= 0:
            continue
        shade.fill((0, 0, 0, alpha))
        surface.blit(shade, (rect.x, rect.y + y),
                     (0, 0, rect.w, min(band, rect.h - y)))

    _paint_court_decoration(surface, rect, look)

    # Playfield boundary.
    pygame.draw.rect(surface, look.line_soft, rect, width=2)
    pygame.draw.line(surface, look.line, (rect.left, rect.top),
                     (rect.right, rect.top), 3)
    pygame.draw.line(surface, look.line, (rect.left, rect.bottom),
                     (rect.right, rect.bottom), 3)

    # Centre dashed divider.
    dash, gap = 20, 16
    x = rect.centerx - 2
    y = rect.y + 6
    while y < rect.bottom - 6:
        length = min(dash, rect.bottom - 6 - y)
        pygame.draw.rect(surface, look.line_soft, (x, y, 4, int(length)),
                         border_radius=2)
        y += dash + gap

    # Centre circle + serve spot.
    pygame.draw.circle(surface, look.line_soft, rect.center, 74, 2)
    pygame.draw.circle(surface, look.line, rect.center, 5)

    # Goal posts, colour-coded to the player they defend.
    pygame.draw.line(surface, Color.blend(look.court, Color.P1, 0.55),
                     (rect.left + 3, rect.y), (rect.left + 3, rect.bottom), 4)
    pygame.draw.line(surface, Color.blend(look.court, Color.P2, 0.55),
                     (rect.right - 3, rect.y), (rect.right - 3, rect.bottom), 4)

    # Corner brackets.
    bracket = 30
    for cx, cy, dx, dy in (
        (rect.left + 8, rect.top + 8, 1, 1),
        (rect.right - 8, rect.top + 8, -1, 1),
        (rect.left + 8, rect.bottom - 8, 1, -1),
        (rect.right - 8, rect.bottom - 8, -1, -1),
    ):
        pygame.draw.line(surface, look.accent, (cx, cy), (cx + dx * bracket, cy), 2)
        pygame.draw.line(surface, look.accent, (cx, cy), (cx, cy + dy * bracket), 2)


def _paint_court_decoration(surface: pygame.Surface, rect: pygame.Rect,
                            look: BackgroundLook) -> None:
    """In-court flourish for themed backgrounds (drawn under the lines)."""
    style = look.style
    if style is BackdropStyle.GRID or look.grid:
        spacing = 48
        for x in range(rect.left + spacing, rect.right, spacing):
            pygame.draw.line(surface, Color.blend(look.line_soft, look.court, 0.5),
                             (x, rect.top), (x, rect.bottom), 1)
        for y in range(rect.top + spacing, rect.bottom, spacing):
            pygame.draw.line(surface, Color.blend(look.line_soft, look.court, 0.5),
                             (rect.left, y), (rect.right, y), 1)
    elif style is BackdropStyle.ARCADE:
        for y in range(rect.top, rect.bottom, 4):
            if ((y - rect.top) // 4) % 2 == 0:
                pygame.draw.rect(surface, (0, 0, 0), (rect.left, y, rect.w, 2))
    elif style is BackdropStyle.SUNSET:
        horizon = rect.centery
        pygame.draw.rect(surface, Color.blend(look.court, look.line, 0.30),
                         (rect.left, horizon, rect.w, rect.bottom - horizon))


__all__ = [
    "CLASSIC_BACKGROUND",
    "clear_glow_cache",
    "draw_ball",
    "draw_paddle",
    "draw_trail",
    "emit_impact",
    "glow_sprite",
    "make_glow",
    "paint_backdrop",
    "paint_court",
]
