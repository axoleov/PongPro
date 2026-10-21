"""FOCUS mode explainer: shown once before the player's first run.

FOCUS inverts rules the other three modes share - there is no opponent, no
score, and the shop's powerups are switched off - so a player arriving from
the menu would otherwise have to discover all of that by losing.  This scene
states it up front, once, and gets out of the way.

It is deliberately *not* a tutorial: the ball never appears, nothing is
interactive beyond the two controls that matter, and dismissing it is a
single keypress.  A player who has seen it never sees it again unless they
ask, via the settings screen.
"""

from __future__ import annotations

import pygame

from ..core.constants import Color, LOGICAL_H, LOGICAL_W, GameMode
from ..core.events import EventType
from ..core.state_machine import Scene, Transition
from ..rendering.ui import Button, MenuList, Toggle
from .common import draw_backdrop, draw_panel, draw_title

#: Panel geometry.  Wider than the pause panel because the rule lines are
#: full sentences and wrapping them would bury the lede.
PANEL_W = 760
PANEL_H = 520

#: The player-facing rules, in the order they matter.  Each entry is a heading
#: plus one line of detail - the heading alone is enough for a returning
#: player, the detail is enough for a first one.
RULES: tuple[tuple[str, str], ...] = (
    ("ONE PLAYER, TWO PADDLES",
     "Drive the left paddle with W / S and the right one with I / K or ↑ / ↓."),
    ("NO OPPONENT, NO SCORE",
     "Keep the ball off both goal lines. There is nobody to beat but yourself."),
    ("LIVES REPLACE POINTS",
     "First to N sets your starting lives instead of a points target."),
    ("POWERUPS ARE OFF",
     "Timed powerups do nothing here, so they never appear in a pickup."),
    ("ONE PICKUP: LIFE ORB",
     "A gold orb grants +1 life. At full health it pays bonus coins instead."),
    ("SPEED STILL CLIMBS",
     "Every return makes the ball faster. Losing a life resets it partway."),
)


class FocusIntroScene(Scene):
    """Modal explainer that hands off to a FOCUS run once dismissed."""

    opaque = True

    def __init__(self) -> None:
        super().__init__()
        self.ctx = None  # type: ignore[assignment]
        self.menu = MenuList()
        self._t = 0.0
        self._unsubs: list = []

    # -- lifecycle --------------------------------------------------------
    def on_enter(self, **kwargs) -> None:
        ctx = self.ctx
        self._t = 0.0

        panel = self._panel()
        menu = MenuList(bus=ctx.bus)
        row_y = panel.bottom - 120
        menu.add(Toggle("focus.intro_dont_show", panel.x + 40, row_y,
                        PANEL_W - 80, "DON'T SHOW AGAIN", False))
        menu.add(Button("focus.start", panel.x + 40, row_y + 60,
                        PANEL_W - 80, "START RUN", primary=True,
                        hotkey="ENTER"))
        self.menu = menu

        if not self._unsubs:
            self._unsubs = [
                ctx.bus.subscribe(EventType.UI_MOVE,
                                  lambda e: ctx.audio.play("ui_move",
                                                           volume=0.6)),
                ctx.bus.subscribe(EventType.UI_SELECT,
                                  lambda e: ctx.audio.play("ui_select")),
            ]
        ctx.audio.play("ui_back")

    def on_exit(self) -> None:
        for unsubscribe in self._unsubs:
            unsubscribe()
        self._unsubs.clear()

    def _panel(self) -> pygame.Rect:
        return pygame.Rect((LOGICAL_W - PANEL_W) // 2,
                           (LOGICAL_H - PANEL_H) // 2 + 8,
                           PANEL_W, PANEL_H)

    # -- input ------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._dismiss(start=False)
                return
            if event.key == pygame.K_RETURN:
                self._dismiss(start=True)
                return
            # SPACE is the activation key MenuList already handles, but the
            # row has to be focused first; ENTER is offered as the shortcut
            # from anywhere.
        action = self.menu.handle_event(event, self.ctx.bus)
        if action == "focus.start":
            self._dismiss(start=True)
        elif action == "focus.intro_dont_show":
            self.ctx.audio.play("ui_move", volume=0.6)

    def _dismiss(self, *, start: bool) -> None:
        """Leave this scene, remembering the toggle, then start the run."""
        from .menu import MenuScene

        ctx = self.ctx
        stack = self.stack
        assert stack is not None

        toggle = self.menu.typed("focus.intro_dont_show", Toggle)
        if toggle is not None and toggle.value:
            ctx.settings.gameplay.focus_intro_seen = True
            ctx.save_settings()

        ctx.audio.play("ui_back" if not start else "ui_select")
        if start:
            # Replace this modal with the run itself, so backing out of the
            # match returns straight to the menu rather than to an explainer
            # the player has already dismissed.
            stack.replace_top(1, self._build_run(), transition=Transition.FADE)
            return
        stack.pop_to(MenuScene, transition=Transition.FADE)

    def _build_run(self):  # type: ignore[no-untyped-def]
        from .menu import MenuScene

        assert self.stack is not None
        menu = self.stack.find(MenuScene)
        assert menu is not None
        return menu.build_match(GameMode.FOCUS)

    # -- frame ------------------------------------------------------------
    def update(self, dt: float) -> None:
        self._t += dt
        mouse = pygame.mouse.get_pos()
        if self.ctx.video is not None:
            mouse = self.ctx.video.to_logical(mouse)
        self.menu.update(dt, mouse)

    def draw(self, surface: pygame.Surface) -> None:
        ctx = self.ctx
        fonts = ctx.fonts
        t = min(1.0, self._t * 4.0)

        draw_backdrop(surface, self._t, seed=7, vignette=84)

        panel = self._panel()
        panel.y += int((1 - t) * 12)
        draw_panel(surface, panel, accent=Color.GOLD, alpha=int(228 * t),
                   title=None, fonts=fonts)

        title = draw_title(surface, "FOCUS", fonts, y=panel.y + 22, size=54,
                           color=Color.GOLD, center_x=LOGICAL_W // 2)
        subtitle = fonts.render(
            "BRAIN EXERCISE  ·  ONE PLAYER, TWO PADDLES", 14, Color.TEXT_DIM,
            bold=True)
        subtitle_y = title.bottom + 8
        surface.blit(subtitle, (LOGICAL_W // 2 - subtitle.get_width() // 2,
                                subtitle_y))

        # -- rules ---------------------------------------------------------
        # Two lines each (heading, then the detail indented under it) so the
        # headings scan without reading the prose.  Laid out from the top; the
        # controls below are anchored to the panel's bottom edge, and the
        # panel is sized so the two blocks meet with room to spare.
        y = subtitle_y + subtitle.get_height() + 20
        indent = panel.x + 40 + 26
        for heading, detail in RULES:
            bullet = fonts.render("▸", 16, Color.ACCENT, bold=True)
            head = fonts.render(heading, 16, Color.TEXT, bold=True)
            surface.blit(bullet, (panel.x + 40, y))
            surface.blit(head, (indent, y))
            body = fonts.render(detail, 15, Color.TEXT_DIM)
            surface.blit(body, (indent, y + head.get_height() + 3))
            y += head.get_height() + body.get_height() + 13

        self.menu.draw(surface, fonts)

        hint = fonts.render("ENTER START   ·   ESC BACK", 13, Color.TEXT_DIM)
        surface.blit(hint, (LOGICAL_W // 2 - hint.get_width() // 2,
                            panel.bottom - 24))


__all__ = ["FocusIntroScene"]
