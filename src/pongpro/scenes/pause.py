"""Pause overlay: rendered above the frozen match (non-opaque scene)."""

from __future__ import annotations

import pygame

from ..core.constants import Color, LOGICAL_H, LOGICAL_W
from ..core.events import EventType
from ..core.state_machine import Scene, Transition
from ..rendering.ui import Button, MenuList, StaticText
from .common import draw_panel, draw_title


class PauseScene(Scene):
    """Stops the match underneath while offering control options."""

    opaque = False  # gameplay stays visible behind the dimmed overlay

    def __init__(self, params: dict | None = None) -> None:
        super().__init__()
        self.params = dict(params or {})
        self.menu = MenuList()
        self._t = 0.0
        self._unsubs: list = []

    # -- lifecycle --------------------------------------------------------
    def on_enter(self, **kwargs) -> None:
        ctx = self.ctx
        self._t = 0.0
        menu = MenuList(bus=ctx.bus)
        panel_x = LOGICAL_W // 2 - 220
        y = LOGICAL_H // 2 - 60
        width = 440
        menu.add(Button("pause.resume", panel_x, y, width, "RESUME",
                        primary=True, hotkey="ESC"))
        y += 56
        menu.add(Button("pause.restart", panel_x, y, width, "RESTART MATCH",
                        hotkey="R"))
        y += 56
        menu.add(Button("pause.settings", panel_x, y, width, "SETTINGS",
                        hotkey="F4"))
        y += 56
        menu.add(Button("pause.quit", panel_x, y, width, "QUIT TO MAIN MENU",
                        hotkey="Q"))
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
        ctx.audio.pause_music()

    def on_exit(self) -> None:
        for unsubscribe in self._unsubs:
            unsubscribe()
        self._unsubs.clear()
        if self.ctx is not None:
            self.ctx.audio.unpause_music()

    # -- input ------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_p):
                self._action("pause.resume")
                return
            if event.key == pygame.K_r:
                self._action("pause.restart")
                return
            if event.key == pygame.K_q:
                self._action("pause.quit")
                return
            if event.key == pygame.K_F4:
                self._action("pause.settings")
                return
        action = self.menu.handle_event(event, self.ctx.bus)
        if action:
            self._action(action)

    def _action(self, action: str) -> None:
        from .gameplay import GameplayScene
        from .settings_scene import SettingsScene

        ctx = self.ctx
        stack = self.stack
        assert stack is not None
        ctx.audio.unpause_music()

        if action == "pause.resume":
            ctx.audio.play("ui_back")
            stack.pop(transition=Transition.FADE)
        elif action == "pause.restart":
            ctx.audio.play("ui_select")
            # Pop pause + the current match, then start fresh.
            stack.replace_top(2, GameplayScene(**self.params),
                              transition=Transition.FADE)
        elif action == "pause.settings":
            stack.push(SettingsScene(), transition=Transition.FADE)
        elif action == "pause.quit":
            from .menu import MenuScene
            ctx.audio.play("ui_back")
            stack.pop_to(MenuScene, transition=Transition.FADE)

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

        dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        dim.fill((*Color.BG, int(180 * t)))
        surface.blit(dim, (0, 0))

        panel = pygame.Rect(LOGICAL_W // 2 - 260, LOGICAL_H // 2 - 190, 520, 400)
        panel.y += int((1 - t) * 12)
        draw_panel(surface, panel, accent=Color.GOLD, alpha=int(225 * t),
                   title=None, fonts=fonts)

        title = draw_title(surface, "PAUSED", fonts, y=panel.y + 30, size=54,
                           color=Color.GOLD, center_x=LOGICAL_W // 2)
        subtitle = fonts.render("MATCH ON HOLD", 14, Color.TEXT_DIM, bold=True)
        surface.blit(subtitle, (LOGICAL_W // 2 - subtitle.get_width() // 2,
                                title.bottom + 8))

        self.menu.draw(surface, fonts)

        gameplay = None
        if ctx.stack is not None:
            from .gameplay import GameplayScene
            gameplay = ctx.stack.find(GameplayScene)
        if gameplay is not None and gameplay.match is not None:
            match = gameplay.match
            info = fonts.render(
                f"{gameplay._label()}   ·   "
                f"{match.score[0]} - {match.score[1]}   ·   "
                f"RALLY {match.rally}",
                15, Color.TEXT_DIM)
            surface.blit(info, (LOGICAL_W // 2 - info.get_width() // 2,
                                panel.bottom - 44))

        hint = fonts.render("ESC RESUME   ·   R RESTART   ·   Q QUIT TO MENU",
                            13, Color.TEXT_DIM)
        surface.blit(hint, (LOGICAL_W // 2 - hint.get_width() // 2,
                            panel.bottom - 22))


__all__ = ["PauseScene"]
