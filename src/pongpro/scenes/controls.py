"""How to Play: a single reference card for every control in the game.

The menu's footer hint only ever shows the bindings for the mode currently
hovered, which is right for a returning player but useless for someone who has
never seen the game - a teacher picking it up cold, a friend borrowing the
keyboard, or you, mid-demo, forgetting which hand owns the arrows.  That
audience needs *all* of them at once, which is what this screen is for.

It is deliberately a reference and not a tutorial: nothing is interactive
beyond the one dismiss control, because a tutorial would have to interrupt a
match to teach, and the modes are each four keys.

Two columns, because one column of every binding does not fit above the
footer band (the menu already runs at zero vertical slack).  The split is by
*context* - what you press during a match on the left, what you press
everywhere else on the right - so a reader finds their answer by asking
"where am I standing?" rather than scanning a flat list.

The bindings are transcribed from the handlers in ``scenes/gameplay.py`` and
``scenes/menu.py`` rather than invented here; ``tests/test_controls.py``
re-reads those handlers and fails if this table and the code ever disagree.
"""

from __future__ import annotations

import pygame

from ..core.constants import Color, LOGICAL_H, LOGICAL_W
from ..core.events import EventType
from ..core.state_machine import Scene, Transition
from ..rendering.ui import Button, MenuList
from .common import draw_backdrop, draw_panel, draw_title

#: Panel geometry.  Wide enough for two columns of "key + what it does", and
#: tall enough that three stacked sections per column still clear the BACK
#: row pinned to the bottom.
PANEL_W = 1000
PANEL_H = 556

#: A section heading, then its (keys, description) rows.  Ordered by how
#: often a new player needs it, not by code path.
IN_MATCH: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("LEFT PADDLE", (
        ("W / S", "Player 1 in every mode"),
        ("\u2191 / \u2193", "Also the left paddle in 1P"),
    )),
    ("RIGHT PADDLE", (
        ("\u2191 / \u2193", "Player 2 in 2 Players mode"),
        ("I / K", "Focus Mode's other paddle"),
    )),
    ("DURING A MATCH", (
        ("SPACE", "Fire your held powerup (P1)"),
        ("ENTER", "Fire your held powerup (P2)"),
        ("ESC / P", "Pause, then resume or quit"),
        ("F2", "Show how the AI thinks"),
    )),
)

ELSEWHERE: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("IN THE MENUS", (
        ("\u2191 \u2193 \u2190 \u2192", "Move between rows"),
        ("ENTER", "Confirm the focused row"),
        ("MOUSE", "Click or drag anything"),
        ("ESC", "Back a screen, or quit"),
    )),
    ("JUMP STRAIGHT IN", (
        ("1 2 3 4", "Start a mode from the menu"),
    )),
    ("SHORTCUTS", (
        ("F3 / F4", "Shop  \u00b7  Settings"),
        ("H", "This screen"),
        ("R", "Watch your last match"),
    )),
)

#: Row rhythm inside a column, in pixels.
_ROW_H = 26
_SECTION_GAP = 22


class ControlsScene(Scene):
    """Reference card of every binding, dismissed back to the menu."""

    opaque = True

    def __init__(self) -> None:
        super().__init__()
        self.ctx = None  # type: ignore[assignment]
        self.menu = MenuList()
        self._t = 0.0
        self._unsubs: list = []
        #: Lowest pixel the two text columns reached, recorded while drawing.
        #: The BACK row is a real widget and the columns are just text, so no
        #: overlap test can see them collide; this lets the layout suite
        #: assert the text stops above the button instead of behind it.
        self.columns_bottom = 0

    # -- lifecycle --------------------------------------------------------
    def on_enter(self, **kwargs) -> None:
        ctx = self.ctx
        self._t = 0.0

        panel = self._panel()
        menu = MenuList(bus=ctx.bus)
        menu.add(Button("controls.back", panel.x + 40, panel.bottom - 76,
                        PANEL_W - 80, "BACK TO MENU", primary=True,
                        hotkey="ESC"))
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
                           (LOGICAL_H - PANEL_H) // 2 + 4,
                           PANEL_W, PANEL_H)

    # -- input ------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._dismiss()
                return
        action = self.menu.handle_event(event, self.ctx.bus)
        if action == "controls.back":
            self._dismiss()

    def _dismiss(self) -> None:
        from .menu import MenuScene

        self.ctx.audio.play("ui_back")
        assert self.stack is not None
        self.stack.pop_to(MenuScene, transition=Transition.FADE)

    # -- frame ------------------------------------------------------------
    def update(self, dt: float) -> None:
        self._t += dt
        mouse = pygame.mouse.get_pos()
        if self.ctx.video is not None:
            mouse = self.ctx.video.to_logical(mouse)
        self.menu.update(dt, mouse)

    # -- drawing ----------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        fonts = self.ctx.fonts
        t = min(1.0, self._t * 4.0)

        draw_backdrop(surface, self._t, seed=31, vignette=88)
        panel = self._panel()
        panel.y += int((1 - t) * 12)
        draw_panel(surface, panel, accent=Color.ACCENT, alpha=int(230 * t),
                   title=None, fonts=fonts)

        title = draw_title(surface, "CONTROLS", fonts, y=panel.y + 20,
                           size=44, color=Color.ACCENT,
                           center_x=LOGICAL_W // 2)
        subtitle = fonts.render("HOW TO PLAY  ·  EVERY KEY, EVERY MODE",
                                14, Color.TEXT_DIM, bold=True)
        surface.blit(subtitle, (LOGICAL_W // 2 - subtitle.get_width() // 2,
                                title.bottom + 6))

        top = title.bottom + 6 + subtitle.get_height() + 20
        col_w = PANEL_W // 2 - 60
        left_bottom = self._draw_column(surface, fonts, IN_MATCH,
                                        panel.x + 44, top, col_w,
                                        heading=Color.P1)
        right_bottom = self._draw_column(surface, fonts, ELSEWHERE,
                                         panel.x + PANEL_W // 2 + 16, top,
                                         col_w, heading=Color.P2)
        self.columns_bottom = max(left_bottom, right_bottom)

        self.menu.draw(surface, fonts)

    def _draw_column(self, surface: pygame.Surface, fonts,  # type: ignore[no-untyped-def]
                     sections, x: int, y: int, width: int, *,
                     heading: tuple[int, int, int]) -> int:
        """Stack sections down one column; return the lowest pixel drawn.

        The trailing ``_SECTION_GAP`` is deliberately *not* added after the
        final section - padding below the last row is wasted height, and the
        column is already tight against the BACK row.
        """
        for index, (title, rows) in enumerate(sections):
            if index:
                y += _SECTION_GAP
            label = fonts.render(title, 14, heading, bold=True)
            surface.blit(label, (x, y))
            y += label.get_height() + 7
            # A short rule under each heading keeps the sections visually
            # separate without boxing each one in.
            pygame.draw.rect(surface, Color.LINE_SOFT, (x, y - 4, width, 1))
            y += 8
            for keys, description in rows:
                y = self._draw_row(surface, fonts, keys, description,
                                   x, y, width)
        return y

    def _draw_row(self, surface: pygame.Surface, fonts,  # type: ignore[no-untyped-def]
                  keys: str, description: str, x: int, y: int,
                  width: int) -> int:
        """One 'key pill, then what it does' line.  Returns the next ``y``."""
        pill = self._draw_key_pill(surface, fonts, keys, x, y)
        # Descriptions start after a shared pill column rather than after
        # their own pill, so they line up down the column however long the
        # key label is.
        text_x = x + max(pill.width, int(width * 0.44))
        text = fonts.render(description, 14, Color.TEXT_DIM)
        surface.blit(text, (text_x, y + (pill.height - text.get_height()) // 2))
        return y + _ROW_H

    @staticmethod
    def _draw_key_pill(surface: pygame.Surface, fonts,  # type: ignore[no-untyped-def]
                       keys: str, x: int, y: int) -> pygame.Rect:
        """A key-cap chip.  Returns the rect it occupied, for row alignment."""
        pad = 9
        width = fonts.width(keys, 14, bold=True) + pad * 2
        height = 22
        rect = pygame.Rect(x, y, width, height)
        pygame.draw.rect(surface, Color.blend(Color.PANEL_LIGHT, Color.ACCENT,
                                              0.14),
                         rect, border_radius=5)
        pygame.draw.rect(surface, Color.blend(Color.LINE_SOFT, Color.ACCENT,
                                              0.45),
                         rect, width=1, border_radius=5)
        label = fonts.render(keys, 14, Color.blend(Color.TEXT, Color.ACCENT,
                                                   0.35), bold=True)
        surface.blit(label, (rect.x + pad,
                             rect.centery - label.get_height() // 2))
        return rect


__all__ = ["ControlsScene", "PANEL_H", "PANEL_W"]
