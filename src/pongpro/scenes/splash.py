"""Boot/splash scene: shows branding while the window comes up, then defers
heavy start-up work (audio synthesis) to the *second* frame so Windows never
marks the process as unresponsive."""

from __future__ import annotations

import math

import pygame

from .. import __version__
from ..core.constants import Color, LOGICAL_H, LOGICAL_W
from ..core.state_machine import Scene, Transition
from .common import AttractBall, draw_backdrop, draw_title


class SplashScene(Scene):
    opaque = True
    SPLASH_SECONDS = 2.2

    def __init__(self, skip: bool = False) -> None:
        super().__init__()
        self.skip = skip
        self._t = 0.0
        self._booted = False
        self._ball = AttractBall()
        self._from = Color.P1
        self._to = Color.P2

    # -- lifecycle --------------------------------------------------------
    def on_enter(self, **kwargs) -> None:
        self._t = 0.0
        self._booted = False
        self._ball = AttractBall()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            self._advance()

    def _advance(self) -> None:
        if self.stack is None:
            return
        from .menu import MenuScene
        self.stack.replace(MenuScene(), transition=Transition.FADE)

    # -- frame ------------------------------------------------------------
    def update(self, dt: float) -> None:
        self._t += dt
        self._ball.update(dt)

        if not self._booted:
            # Runs once, after the first frame has been presented.
            self._booted = True
            ctx = self.ctx  # type: ignore[attr-defined]
            if ctx is not None:
                if ctx.audio.initialise():
                    ctx.audio.start_music()
                ctx.save_settings()

        if self.skip or self._t >= self.SPLASH_SECONDS:
            self._advance()

    def draw(self, surface: pygame.Surface) -> None:
        t = self._t
        draw_backdrop(surface, t, seed=7, vignette=90)
        self._ball.draw(surface, Color.ACCENT)

        # Wordmark with a colour that cycles across the palette.
        cycle = 0.5 + 0.5 * math.sin(t * 1.7)
        color = Color.blend(self._from, self._to, cycle)
        title_rect = draw_title(surface, "PONG PRO", self.ctx.fonts,  # type: ignore[attr-defined]
                                y=246, size=104, color=color)

        subtitle = self.ctx.fonts.render(  # type: ignore[attr-defined]
            "PRODUCTION EDITION", 20, Color.TEXT_DIM, bold=True)
        surface.blit(subtitle, (title_rect.centerx - subtitle.get_width() // 2,
                                title_rect.bottom + 12))

        version = self.ctx.fonts.render(  # type: ignore[attr-defined]
            f"v{__version__}  ·  PYTHON 3.12  ·  PYGAME 2.6.1", 14, Color.TEXT_DIM)
        surface.blit(version, (LOGICAL_W // 2 - version.get_width() // 2, 60))

        # Boot progress bar: animates across the splash, completes when ready.
        progress = min(1.0, t / self.SPLASH_SECONDS)
        bar = pygame.Rect(LOGICAL_W // 2 - 180, 470, 360, 6)
        pygame.draw.rect(surface, Color.PANEL_LIGHT, bar, border_radius=3)
        fill = pygame.Rect(bar.x, bar.y, int(bar.w * progress), bar.h)
        pygame.draw.rect(surface, color, fill, border_radius=3)

        if int(t * 2.4) % 2 == 0:
            hint = self.ctx.fonts.render("press any key to skip", 14,  # type: ignore[attr-defined]
                                         Color.TEXT_DIM)
            surface.blit(hint, (LOGICAL_W // 2 - hint.get_width() // 2, 540))
