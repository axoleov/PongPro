"""Main menu: mode selection, quick match rules, lifetime stats, system ops."""

from __future__ import annotations

import math

import pygame

from .. import __version__
from ..core.constants import (
    Color,
    LOGICAL_H,
    LOGICAL_W,
    Difficulty,
    GameMode,
)
from ..core.events import EventType
from ..core.state_machine import Scene, Transition
from ..rendering.ui import (
    Button,
    MenuList,
    OptionCycle,
    StaticText,
)
from .common import (
    AttractBall,
    draw_backdrop,
    draw_panel,
    draw_title,
    format_duration,
    format_percent,
)

MODE_ACTIONS: dict[str, GameMode] = {
    "play_solo": GameMode.SOLO,
    "play_two": GameMode.TWO_PLAYER,
    "play_watch": GameMode.AI_VS_AI,
    "play_focus": GameMode.FOCUS,
}

MODE_HINTS = {
    GameMode.SOLO: "W / S move   ·   ESC pause   ·   beat the machine",
    GameMode.TWO_PLAYER: "P1: W / S     P2: ↑ / ↓     ·   local versus",
    GameMode.AI_VS_AI: "sit back - the bots are warming up",
    GameMode.FOCUS: "W / S + I / K   ·   one player, two paddles, no opponent",
}

#: Shared baseline of the bottom band (mode hint on the left, key legend on
#: the right).  The menu column must finish well above this line.
FOOTER_Y = LOGICAL_H - 46

#: Wallet badge.  Sits in the top-right corner beside the title: the left
#: column is full down to ``FOOTER_Y`` and the profile panel occupies
#: 184..556, so this is the only empty band wide enough for a 300px badge.
WALLET_RECT = pygame.Rect(LOGICAL_W - 340, 60, 300, 48)

#: SHOP entry point, directly under the profile panel (bottom 556) and clear
#: of the toast band that starts at ``LOGICAL_H - 96`` (624).
SHOP_RECT = pygame.Rect(LOGICAL_W - 610, 566, 546, 46)


class MenuScene(Scene):
    opaque = True

    def __init__(self) -> None:
        super().__init__()
        self.ctx = None  # type: ignore[assignment]
        self.menu = MenuList()
        self._t = 0.0
        self._ball = AttractBall()
        self._toast: str | None = None
        self._toast_timer = 0.0
        self._stats: dict = {}
        self._unsubs: list = []
        self._x = 104
        self._width = 452
        #: Populated by :meth:`_draw_stats_panel`; the profile panel bounds.
        self.stats_panel = pygame.Rect(LOGICAL_W - 610, 184, 546, 372)
        #: Live coin balance, drawn beside the title.  Exposed for the layout
        #: tests, which assert it clears both the title and the profile panel.
        self.wallet_rect = pygame.Rect(WALLET_RECT)

    # -- lifecycle --------------------------------------------------------
    def on_enter(self, **kwargs) -> None:
        ctx = self.ctx
        self._t = 0.0
        self._ball = AttractBall()
        self._stats = ctx.storage.load_stats()
        self._build_menu()

        if not self._unsubs:
            self._unsubs = [
                ctx.bus.subscribe(EventType.UI_MOVE, self._on_ui_move),
                ctx.bus.subscribe(EventType.UI_SELECT, self._on_ui_select),
                ctx.bus.subscribe(EventType.UI_BACK, self._on_ui_back),
            ]

    def on_resume(self) -> None:
        # Settings / results may have changed stats or rules.
        self._stats = self.ctx.storage.load_stats()
        self._build_menu()

    def on_exit(self) -> None:
        for unsubscribe in self._unsubs:
            unsubscribe()
        self._unsubs.clear()

    # -- menu construction ------------------------------------------------
    def _build_menu(self) -> None:
        settings = self.ctx.settings.gameplay
        menu = MenuList(bus=self.ctx.bus)
        # Layout budget: the column must clear the footer band pinned to the
        # bottom of the viewport, so the rhythm below keeps every row above
        # FOOTER_Y.  Asserted by tests/test_layout.py.
        y = 184
        step = 50

        menu.add(Button("play_solo", self._x, y, self._width,
                        "1 PLAYER  ·  VS AI", primary=True, hotkey="1"))
        y += step
        menu.add(Button("play_two", self._x, y, self._width,
                        "2 PLAYERS  ·  LOCAL", hotkey="2"))
        y += step
        # The two "alternate" modes share one row instead of each claiming a
        # full-width entry.  The left column runs at zero vertical slack (see
        # FOOTER_Y) and QUIT would land in the footer band if FOCUS took a row
        # of its own, so the pairing is a layout constraint rather than a
        # statement about their importance.
        half = (self._width - 8) // 2
        menu.add(Button("play_focus", self._x, y, half,
                        "FOCUS MODE", hotkey="4"))
        menu.add(Button("play_watch", self._x + half + 8, y, half,
                        "AI VS AI", hotkey="3"))
        y += step + 6

        menu.add(StaticText(self._x, y, self._width, "match rules", size=13,
                            color=Color.ACCENT))
        y += 32
        menu.add(OptionCycle(
            "rule_difficulty", self._x, y, self._width, "Difficulty",
            [(d, d.value.upper()) for d in Difficulty],
            [d for d in Difficulty].index(settings.difficulty),
        ))
        y += step
        menu.add(OptionCycle(
            "rule_target", self._x, y, self._width, "First to",
            [(n, f"{n} POINTS") for n in (3, 5, 7, 11, 21)],
            [3, 5, 7, 11, 21].index(settings.target_score)
            if settings.target_score in (3, 5, 7, 11, 21) else 1,
        ))
        y += step + 6

        menu.add(StaticText(self._x, y, self._width, "system", size=13,
                            color=Color.P2))
        y += 32
        # SETTINGS and CONTROLS share the row for the same reason the two
        # alternate modes do: the column has no vertical slack left.  They
        # also belong together - both answer "how does this thing work?"
        # rather than "let me play".
        menu.add(Button("settings", self._x, y, half, "SETTINGS", hotkey="F4"))
        menu.add(Button("controls", self._x + half + 8, y, half,
                        "CONTROLS", hotkey="H"))
        y += step
        replay = self.ctx.storage.load_replay()
        replay_button = Button("replay", self._x, y, self._width,
                               "WATCH LAST REPLAY", hotkey="R")
        replay_button.enabled = replay is not None
        menu.add(replay_button)
        y += step
        menu.add(Button("quit", self._x, y, self._width, "QUIT", hotkey="ESC"))

        # Right column: the profile panel leaves a single clear band beneath
        # it, which is where the shop entry point lives (the left column has
        # zero vertical slack left by this point).
        menu.add(Button("shop", SHOP_RECT.x, SHOP_RECT.y, SHOP_RECT.w,
                        "SHOP  ·  COINS & LOADOUT", hotkey="F3"))

        self.menu = menu
        self._rows_bottom = y + step

    # -- events -----------------------------------------------------------
    def _on_ui_move(self, event) -> None:  # type: ignore[no-untyped-def]
        self.ctx.audio.play("ui_move", volume=0.7)

    def _on_ui_select(self, event) -> None:  # type: ignore[no-untyped-def]
        self.ctx.audio.play("ui_select")

    def _on_ui_back(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.get("blocked"):
            self.ctx.audio.play("deny", volume=0.8)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_F4:
                self._open_settings()
                return
            if event.key == pygame.K_F3:
                self._dispatch("shop")
                return
            if event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
                action = {pygame.K_1: "play_solo",
                          pygame.K_2: "play_two",
                          pygame.K_3: "play_watch",
                          pygame.K_4: "play_focus"}[event.key]
                self._dispatch(action)
                return
            if event.key == pygame.K_r:
                self._dispatch("replay")
                return
            if event.key == pygame.K_h:
                self._dispatch("controls")
                return
            if event.key == pygame.K_ESCAPE:
                self.ctx.request_quit()
                return

        action = self.menu.handle_event(event, self.ctx.bus)
        if action:
            self._dispatch(action)

    def _dispatch(self, action: str) -> None:
        if action == "__back__":
            self.ctx.request_quit()
            return
        if action in MODE_ACTIONS:
            self._start_match(MODE_ACTIONS[action])
        elif action == "rule_difficulty":
            widget = self.menu.get("rule_difficulty")
            assert isinstance(widget, OptionCycle)
            self.ctx.settings.gameplay.difficulty = widget.value  # type: ignore[assignment]
            self._save()
        elif action == "rule_target":
            widget = self.menu.get("rule_target")
            assert isinstance(widget, OptionCycle)
            self.ctx.settings.gameplay.target_score = int(widget.value)  # type: ignore[arg-type]
            self._save()
        elif action == "settings":
            self._open_settings()
        elif action == "controls":
            self._open_controls()
        elif action == "shop":
            self._open_shop()
        elif action == "replay":
            self._open_replay()
        elif action == "quit":
            self.ctx.request_quit()

    def _save(self) -> None:
        self.ctx.settings.validate()
        self.ctx.save_settings()
        self.ctx.audio.apply_volumes()

    def _open_settings(self) -> None:
        from .settings_scene import SettingsScene
        self.ctx.audio.play("ui_select")
        assert self.stack is not None
        self.stack.push(SettingsScene(), transition=Transition.FADE)

    def _open_controls(self) -> None:
        from .controls import ControlsScene
        self.ctx.audio.play("ui_select")
        assert self.stack is not None
        self.stack.push(ControlsScene(), transition=Transition.FADE)

    def _open_replay(self) -> None:
        payload = self.ctx.storage.load_replay()
        if payload is None:
            self.ctx.audio.play("deny")
            self._toast = "NO SAVED REPLAY YET - PLAY A MATCH FIRST"
            self._toast_timer = 2.4
            return
        from .replay_scene import ReplayScene
        self.ctx.audio.play("ui_select")
        assert self.stack is not None
        self.stack.push(ReplayScene(payload), transition=Transition.FADE)

    def _open_shop(self) -> None:
        from .shop import ShopScene
        self.ctx.audio.play("ui_select")
        assert self.stack is not None
        self.stack.push(ShopScene(), transition=Transition.FADE)

    def _start_match(self, mode: GameMode) -> None:
        gameplay_settings = self.ctx.settings.gameplay
        gameplay_settings.mode = mode
        self._save()
        self.ctx.audio.play("ui_select")
        assert self.stack is not None

        if mode is GameMode.FOCUS and not gameplay_settings.focus_intro_seen:
            # FOCUS breaks every rule the other three modes share, so it opens
            # with an explainer instead of dropping the player straight in.
            from .focus_intro import FocusIntroScene
            self.stack.push(FocusIntroScene(), transition=Transition.FADE)
            return

        self._start_match_now(mode)

    def _start_match_now(self, mode: GameMode) -> None:
        """Push the gameplay scene for ``mode`` using the saved rules."""
        assert self.stack is not None
        self.stack.push(self.build_match(mode), transition=Transition.FADE)

    def build_match(self, mode: GameMode) -> "GameplayScene":
        """Construct a gameplay scene from the saved rules.

        Public so :mod:`pongpro.scenes.focus_intro` can hand back a match
        built exactly the way the menu builds one, without either module
        duplicating the settings read.
        """
        from .gameplay import GameplayScene

        gameplay_settings = self.ctx.settings.gameplay
        return GameplayScene(
            mode=mode,
            difficulty=gameplay_settings.difficulty,
            target_score=gameplay_settings.target_score,
            rally_speedup=gameplay_settings.rally_speedup,
            english=gameplay_settings.english_enabled,
        )

    # -- frame ------------------------------------------------------------
    def update(self, dt: float) -> None:
        self._t += dt
        self._ball.update(dt)
        mouse = pygame.mouse.get_pos()
        # Convert window -> logical so widget hover matches what is drawn.
        if self.ctx.video is not None:
            mouse = self.ctx.video.to_logical(mouse)
        self.menu.update(dt, mouse)
        if self._toast_timer > 0.0:
            self._toast_timer = max(0.0, self._toast_timer - dt)

    def draw(self, surface: pygame.Surface) -> None:
        ctx = self.ctx
        fonts = ctx.fonts
        t = self._t

        draw_backdrop(surface, t, seed=42, vignette=84)
        # Attract ball bounces behind the stats panel area for visual life.
        self._ball.draw(surface, Color.blend(Color.P1, Color.P2,
                                             0.5 + 0.5 * math.sin(t * 0.9)))

        title_rect = draw_title(surface, "PONG PRO", fonts, y=52, size=86,
                                color=Color.TEXT)
        # Accent underline that sweeps in on scene entry.
        grow = min(1.0, t * 1.8)
        underline = pygame.Rect(title_rect.centerx - int(240 * grow),
                                title_rect.bottom + 4, int(480 * grow), 4)
        pygame.draw.rect(surface, Color.ACCENT, underline, border_radius=2)

        subtitle = fonts.render(
            f"PRODUCTION EDITION  ·  v{__version__}", 15, Color.TEXT_DIM,
            bold=True)
        surface.blit(subtitle, (title_rect.centerx - subtitle.get_width() // 2,
                                underline.bottom + 10))

        self._draw_stats_panel(surface)
        self._draw_wallet_badge(surface)
        self.menu.draw(surface, fonts)

        # Shared footer line: contextual mode hint (left) and the global key
        # legend (right) sit on one baseline, leaving a single clear band at
        # the bottom of the viewport for the menu column to end above.
        hint = fonts.render(self._current_mode_hint(), 14, Color.TEXT_DIM)
        surface.blit(hint, (self._x, FOOTER_Y))

        footer = fonts.render(
            "F3 SHOP  ·  F4 SETTINGS  ·  F11 FULLSCREEN  ·  ESC QUIT", 13,
            Color.TEXT_DIM)
        surface.blit(footer, (LOGICAL_W - footer.get_width() - 40, FOOTER_Y))

        if self._toast_timer > 0.0:
            alpha = min(1.0, self._toast_timer)
            width = fonts.width(self._toast, 15, bold=True) + 40
            # Bottom-right, clear of the menu column (x <= 556), the profile
            # panel (y <= 556) and the footer line below.
            x = max(self._x + self._width + 10, LOGICAL_W - width - 40)
            rect = pygame.Rect(x, LOGICAL_H - 96, width, 34)
            pygame.draw.rect(surface, Color.PANEL_LIGHT, rect, border_radius=8)
            pygame.draw.rect(surface, Color.WARN, rect, width=1, border_radius=8)
            text = fonts.render(self._toast, 15, Color.TEXT, bold=True)
            text.set_alpha(int(255 * alpha))
            surface.blit(text, (rect.centerx - text.get_width() // 2, rect.y + 8))

    def _draw_wallet_badge(self, surface: pygame.Surface) -> None:
        """Coin balance, top-right beside the title."""
        fonts = self.ctx.fonts
        rect = pygame.Rect(WALLET_RECT)
        self.wallet_rect = rect
        accent = Color.GOLD
        pygame.draw.rect(surface, Color.blend(Color.PANEL, accent, 0.16), rect,
                         border_radius=10)
        pygame.draw.rect(surface, Color.blend(Color.LINE_SOFT, accent, 0.7), rect,
                         width=1, border_radius=10)
        label = fonts.render("COINS", 13, Color.TEXT_DIM, bold=True)
        surface.blit(label, (rect.x + 14,
                             rect.centery - label.get_height() // 2))
        pygame.draw.circle(surface, accent, (rect.x + 92, rect.centery), 7)
        pygame.draw.circle(surface, Color.blend(accent, (255, 255, 255), 0.6),
                           (rect.x + 90, rect.centery - 2), 3)
        from ..economy.wallet import get_wallet
        coins = get_wallet(self.ctx).coins
        amount = fonts.render(f"{coins:,}", 24, Color.TEXT, bold=True,
                              shadow=True)
        surface.blit(amount, (rect.right - amount.get_width() - 16,
                              rect.centery - amount.get_height() // 2))

    def _current_mode_hint(self) -> str:
        widget = self.menu.get("play_solo")
        if widget is None:
            return ""
        focused = self.menu.current
        if focused is None:
            return MODE_HINTS[GameMode.SOLO]
        mode = MODE_ACTIONS.get(focused.action,
                                self.ctx.settings.gameplay.mode)
        return MODE_HINTS.get(mode, "")

    def _draw_stats_panel(self, surface: pygame.Surface) -> list[pygame.Rect]:
        """Draw the player-profile panel and return every rect it occupies.

        The returned rectangles exist so the layout can be asserted in
        ``tests/test_layout.py`` -- content used to run straight past the
        panel's bottom edge.
        """
        fonts = self.ctx.fonts
        stats = self._stats
        panel = pygame.Rect(LOGICAL_W - 610, 184, 546, 372)
        self.stats_panel = panel
        placed: list[pygame.Rect] = []
        draw_panel(surface, panel, accent=Color.P2, alpha=200,
                   title="player profile", fonts=fonts)
        title = fonts.render("PLAYER PROFILE", 15, Color.P2, bold=True)
        placed.append(pygame.Rect(panel.x + 20, panel.y + 16,
                                  *title.get_size()))

        played = int(stats.get("matches_played", 0))
        wins = int(stats.get("wins", 0))
        losses = int(stats.get("losses", 0))
        win_rate = (wins / played) if played else 0.0

        rows = [
            ("MATCHES PLAYED", f"{played}", Color.TEXT),
            ("WON / LOST", f"{wins} / {losses}", Color.ACCENT),
            ("WIN RATE", format_percent(win_rate), Color.GOLD),
            ("LONGEST RALLY", f"{int(stats.get('longest_rally', 0))}", Color.P1),
            ("TOTAL RETURNS", f"{int(stats.get('total_hits', 0))}", Color.P1),
            ("FASTEST BALL", f"{float(stats.get('fastest_ball', 0)):.0f} px/s",
             Color.WARN),
            ("PLAY TIME", format_duration(stats.get("playtime_seconds", 0.0)),
             Color.TEXT_DIM),
            # FOCUS has no score to headline, so its personal best is the
            # longest single run - the number the mode actually ranks.
            ("FOCUS BEST",
             format_duration(stats.get("focus_best_time", 0.0)),
             Color.GOLD),
        ]

        # Split the stat rows across two columns: eight single-line rows plus
        # the per-difficulty table and the rules summary cannot stack inside
        # the panel without running past its bottom edge.
        y0 = panel.y + 54
        row_h = 44
        col_w = 246
        col_x = (panel.x + 22, panel.x + 22 + col_w + 10)
        split = 4

        for i, (label, value, color) in enumerate(rows):
            col = 0 if i < split else 1
            row = i if i < split else i - split
            x = col_x[col]
            y = y0 + row * row_h
            key = fonts.render(label, 15, Color.TEXT_DIM)
            val = fonts.render(value, 19, color, bold=True)
            surface.blit(key, (x, y))
            placed.append(pygame.Rect(x, y, *key.get_size()))
            vx = x + col_w - 8 - val.get_width()
            surface.blit(val, (vx, y - 3))
            placed.append(pygame.Rect(vx, y - 3, *val.get_size()))
            pygame.draw.line(surface, Color.LINE_SOFT,
                             (x, y + 24), (x + col_w - 8, y + 24))
            placed.append(pygame.Rect(x, y + 24, col_w - 8, 1))

        y = y0 + split * row_h

        # Per-difficulty breakdown for solo play.
        by_diff = stats.get("by_difficulty") or {}
        if by_diff:
            y += 6
            header = fonts.render("SOLO RECORD BY DIFFICULTY", 13, Color.P2,
                                  bold=True)
            surface.blit(header, (panel.x + 22, y))
            placed.append(pygame.Rect(panel.x + 22, y, *header.get_size()))
            y += 24
            for diff in Difficulty:
                entry = by_diff.get(diff.value)
                if not entry:
                    continue
                line = (f"{diff.value.upper():<7} "
                        f"{entry.get('won', 0)}W - {entry.get('lost', 0)}L")
                text = fonts.render(line, 14, Color.TEXT_DIM)
                surface.blit(text, (panel.x + 22, y))
                placed.append(pygame.Rect(panel.x + 22, y, *text.get_size()))
                y += 20
        else:
            hint = fonts.render("play a solo match to start your record", 14,
                                Color.TEXT_DIM)
            surface.blit(hint, (panel.x + 22, y + 4))
            placed.append(pygame.Rect(panel.x + 22, y + 4, *hint.get_size()))

        # Current rules summary at the panel bottom.
        settings = self.ctx.settings.gameplay
        summary = fonts.render(
            f"NEXT MATCH: {settings.mode.value.upper()} · "
            f"{settings.difficulty.value.upper()} · FIRST TO "
            f"{settings.target_score}",
            13, Color.ACCENT, bold=True)
        surface.blit(summary, (panel.x + 22, panel.bottom - 30))
        placed.append(pygame.Rect(panel.x + 22, panel.bottom - 30,
                                  *summary.get_size()))
        return placed


__all__ = ["MenuScene"]
