"""Boot credits scene: names the game's creator before the brand splash.

Every launch opens credits -> PONG PRO splash -> menu, by the creator's
explicit choice (no "seen" flag, no settings toggle).  A click or keypress
skips *only this screen*, so the splash after it still gets its turn.

The screen carries exactly two lines of text - ``GAME CREATOR`` and the
name - and nothing else readable.  Everything else (rule lines, light
sweeps, the drift-up exit) is ornament, which is how a single credit still
reads as a deliberate opening rather than a placeholder.  The last ~1.6 s
hold *perfectly still* so the line can actually be read; this is a school
project that gets shown to a teacher, and animation that never stops moving
is hard to read.

Hand-off mirrors ``SplashScene._advance``: a ``replace`` with a FADE, so
the splash's own second-frame audio-deferral trick runs on a fresh scene
exactly as it does when booted directly.
"""

from __future__ import annotations

import math

import pygame

from ..core.constants import Color, LOGICAL_W
from ..core.state_machine import Scene, Transition
from .common import draw_backdrop

CREDITS_SECONDS = 5.6
LABEL = "GAME CREATOR"
NAME = "ASHIRYA WILSON D'SOUZA"

#: Beat schedule (seconds).
LABEL_START, NAME_START, RULE2_START = 0.2, 1.6, 4.0
#: Each letter resolves on its own clock, staggered along the word.
LETTER_STAGGER, LETTER_DURATION = 0.07, 0.35
#: The light sweep crosses the name once, just before the hold.
SWEEP_AT = 3.6
#: Beat 3's rule is quick so the still hold it opens actually exists.
RULE2_SECONDS = 0.4
#: Content drifts up and dims into the state machine's fade.  The still
#: hold therefore runs ~4.45 -> 5.2; the drift is the hand-off, not part
#: of the hold.
EXIT_AT = 5.2
RULE_W, RULE_H = 340, 2
NAME_SIZE, LABEL_SIZE = 64, 22
#: Letterspacing between rendered glyphs, px.
TRACKING = 2


def _clamp01(p: float) -> float:
    return 0.0 if p < 0.0 else 1.0 if p > 1.0 else p


def _ease_out_cubic(p: float) -> float:
    p = _clamp01(p)
    return 1.0 - (1.0 - p) ** 3


class CreditsScene(Scene):
    opaque = True

    def __init__(self) -> None:
        super().__init__()
        self._t = 0.0
        self._glow: pygame.Surface | None = None

    # -- lifecycle --------------------------------------------------------
    def on_enter(self, **kwargs) -> None:
        self._t = 0.0

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            self._skip()

    def _skip(self) -> None:
        # SceneStack.handle_event swallows KEYDOWN during a fade but *not*
        # mouse clicks, so without this guard a click landing mid-fade
        # would double-fire the hand-off.
        if self.stack is None or self.stack.transitioning:
            return
        from .splash import SplashScene
        self.stack.replace(SplashScene(), transition=Transition.FADE)

    # -- frame ------------------------------------------------------------
    def update(self, dt: float) -> None:
        self._t += dt
        if self._t >= CREDITS_SECONDS:
            self._skip()

    # -- draw -------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        t = self._t
        fonts = self.ctx.fonts  # type: ignore[attr-defined]
        cx = LOGICAL_W // 2

        draw_backdrop(surface, t, seed=21, vignette=90)

        accent = Color.blend(Color.P1, Color.P2, 0.5 + 0.5 * math.sin(t * 1.7))
        rule_color = Color.blend(Color.LINE, accent, 0.5)

        # Everything credits-side shares one exit drift (fade + rise).
        exit_p = _ease_out_cubic((t - EXIT_AT) / (CREDITS_SECONDS - EXIT_AT))
        drift = int(exit_p * 40)
        exit_alpha = int(255 * (1.0 - exit_p))

        # -- beat 1: the top rule draws outward from the centre ------------
        rule_w = int(RULE_W * _ease_out_cubic(t / 1.2))
        rule_y = 258 - drift
        if rule_w > 0:
            rule = pygame.Rect(cx - rule_w // 2, rule_y, rule_w, RULE_H)
            pygame.draw.rect(surface, rule_color, rule, border_radius=1)

        # -- beat 1: the label fades up beneath it -------------------------
        label_p = _ease_out_cubic((t - LABEL_START) / 0.8)
        if label_p > 0.0:
            label = fonts.render(LABEL, LABEL_SIZE, Color.TEXT_DIM, bold=True)
            label = label.copy()
            label.set_alpha(int(_label_alpha(label_p, exit_alpha)))
            surface.blit(label, (cx - label.get_width() // 2, rule_y + 22))

        # -- beat 2: the name resolves letter by letter --------------------
        name_y = 330 - drift
        name_rect = _name_rect(fonts, cx, name_y)

        # The bloom sits *behind* the letters, so they stay readable.  The
        # cached glow is ours, not the font cache's, so it is safe to set
        # its alpha in place - no copy needed.
        bloom = _bloom_strength(t)
        if bloom > 0.0:
            if self._glow is None:
                self._glow = _make_glow(name_rect)
            self._glow.set_alpha(int(70 * bloom * (exit_alpha / 255)))
            surface.blit(self._glow,
                         (cx - self._glow.get_width() // 2,
                          name_rect.centery - self._glow.get_height() // 2))

        _draw_name(surface, fonts, t, name_y, accent, exit_alpha,
                   name_rect)

        # -- beat 2: one light sweep across the word -----------------------
        sweep_p = (t - SWEEP_AT) / 0.7
        if 0.0 < sweep_p < 1.0:
            _draw_sweep(surface, name_rect, sweep_p, exit_alpha)

        # -- beat 3: the bottom rule, then the still hold ------------------
        rule2_w = int(RULE_W * _ease_out_cubic(
            (t - RULE2_START) / RULE2_SECONDS))
        if rule2_w > 0:
            rule2 = pygame.Rect(cx - rule2_w // 2, 402 - drift,
                                rule2_w, RULE_H)
            pygame.draw.rect(surface, rule_color, rule2, border_radius=1)

        # -- persistent furniture ------------------------------------------
        progress = min(1.0, t / CREDITS_SECONDS)
        bar = pygame.Rect(cx - 180, 660, 360, 6)
        pygame.draw.rect(surface, Color.PANEL_LIGHT, bar, border_radius=3)
        fill = pygame.Rect(bar.x, bar.y, int(bar.w * progress), bar.h)
        pygame.draw.rect(surface, accent, fill, border_radius=3)

        if int(t * 2.4) % 2 == 0:
            hint = fonts.render("click anywhere to skip", 14, Color.TEXT_DIM)
            surface.blit(hint, (cx - hint.get_width() // 2, 684))


def _label_alpha(p: float, exit_alpha: int) -> float:
    return 255.0 * _clamp01(p) * (exit_alpha / 255)


def _name_rect(fonts, cx: int, y: int):  # type: ignore[no-untyped-def]
    """The name's bounding rect, independent of the animation state."""
    offsets = _letter_offsets(fonts)
    last_i = max(offsets)
    last_w = fonts.render(NAME[last_i], NAME_SIZE, Color.TEXT,
                          bold=True).get_width()
    width = offsets[last_i] + last_w
    height = fonts.render("A", NAME_SIZE, Color.TEXT, bold=True).get_height()
    return pygame.Rect(cx - width // 2, y, width, height)


def _letter_offsets(fonts):  # type: ignore[no-untyped-def]
    """x offset of every non-space glyph, keyed by index into NAME."""
    offsets: dict[int, int] = {}
    x = 0
    for i, ch in enumerate(NAME):
        if ch == " ":
            x += NAME_SIZE // 3
            continue
        offsets[i] = x
        x += fonts.render(ch, NAME_SIZE, Color.TEXT, bold=True).get_width()
        x += TRACKING
    return offsets


def _bloom_strength(t: float) -> float:
    """Rises as the sweep passes, then settles at once.

    The settle is deliberately quick (0.15 s): the beat after the sweep is
    the *still* hold, where the name can be read, and a glow that keeps
    pulsing through it defeats the point of the hold.
    """
    if t < SWEEP_AT:
        return 0.0
    rise = _clamp01((t - SWEEP_AT) / 0.7)
    settle = _clamp01((t - SWEEP_AT - 0.7) / 0.15)
    return rise * (1.0 - 0.45 * settle)


def _draw_name(surface: pygame.Surface, fonts, t: float, y: int,  # type: ignore[no-untyped-def]
               accent: tuple[int, int, int], exit_alpha: int,
               rect: pygame.Rect) -> None:
    """Render the name letter by letter, each rising into place."""
    offsets = _letter_offsets(fonts)
    origin_x = rect.x
    color = Color.blend(Color.TEXT, accent, 0.25 + 0.25 * math.sin(t * 1.7))
    for i, ch in enumerate(NAME):
        if ch == " ":
            continue
        p = _ease_out_cubic((t - NAME_START - i * LETTER_STAGGER)
                            / LETTER_DURATION)
        if p <= 0.0:
            continue
        glyph = fonts.render(ch, NAME_SIZE, color, bold=True).copy()
        glyph.set_alpha(int(255 * p * (exit_alpha / 255)))
        surface.blit(glyph, (origin_x + offsets[i], y + int((1.0 - p) * 18)))


def _draw_sweep(surface: pygame.Surface, rect: pygame.Rect, p: float,
                exit_alpha: int) -> None:
    """A soft vertical band travels left -> right across the name.

    ``BLEND_RGB_ADD`` ignores per-pixel *alpha*, so the falloff has to live
    in the RGB values themselves: every column holds an opaque grey whose
    brightness is the falloff, and the add- blend turns that into light.
    Baking it into alpha instead made the whole band solid white.
    """
    band_w = max(24, rect.w // 6)
    band = pygame.Surface((band_w, rect.h + 8))
    for bx in range(band_w):
        falloff = 1.0 - abs(bx - band_w / 2) / (band_w / 2)
        shade = int(90 * falloff * falloff * (exit_alpha / 255))
        band.fill((shade, shade, shade), (bx, 0, 1, band.get_height()))
    x = rect.x - band_w + int((rect.w + band_w) * p)
    surface.blit(band, (x, rect.y - 4), special_flags=pygame.BLEND_RGB_ADD)


def _make_glow(rect: pygame.Rect) -> pygame.Surface:
    """A soft halo behind the name, built once and cached.

    Built small and smooth-scaled up: per-step alpha at a handful of
    concentric rings, blurred into a gradient by the scale.  Stacking
    full-alpha ellipses instead produced a solid white blob that ate the
    letters it was meant to frame.
    """
    pad = 48
    small_w, small_h = 96, 24
    glow = pygame.Surface((small_w, small_h), pygame.SRCALPHA)
    for i in range(6, 0, -1):
        f = i / 6.0
        alpha = int(26 * (1.0 - f * 0.8))
        box = pygame.Rect(int(small_w * (1 - f) / 2),
                          int(small_h * (1 - f) / 2),
                          max(1, int(small_w * f)),
                          max(1, int(small_h * f)))
        pygame.draw.ellipse(glow, (150, 210, 255, alpha), box)
    return pygame.transform.smoothscale(
        glow, (rect.w + pad * 2, rect.h + pad * 2))
