"""Results screen: outcome headline, match summary, lifetime delta, next steps."""

from __future__ import annotations

import pygame

from ..core.constants import Color, LOGICAL_H, LOGICAL_W, GameMode
from ..core.events import EventType
from ..core.state_machine import Scene, Transition
from ..rendering.ui import Button, MenuList
from .common import draw_backdrop, draw_panel, draw_title, format_duration

#: Vertical rhythm of the results screen.  Kept as module constants so
#: ``tests/test_layout.py`` can assert the action row still clears the summary
#: text above it and the hint line below it.
PANEL_Y = 344
PANEL_H = 200
EARNED_DY = 6        # coin award, the headline of the bottom band
LIFETIME_DY = 36     # lifetime record, below the coin award
NOTE_DY = 56         # difficulty note, last line before the action row
HINT_Y = LOGICAL_H - 40
BUTTON_Y = LOGICAL_H - 96
BUTTON_H = 46
#: Height the earned-coins line occupies under the panel, so the layout test
#: can check the whole bottom band against the action row in real pixels.
EARNED_H = 24


class ResultsScene(Scene):
    """End-of-match summary with rematch / replay / menu actions."""

    opaque = True

    def __init__(self, payload: dict | None = None,
                 resume_params: dict | None = None) -> None:
        super().__init__()
        self.payload = dict(payload or {})
        self.params = dict(resume_params or {})
        self.menu = MenuList()
        self._t = 0.0
        self._unsubs: list = []

    # -- lifecycle --------------------------------------------------------
    def on_enter(self, **kwargs) -> None:
        if kwargs.get("payload"):
            self.payload.update(kwargs["payload"])
        ctx = self.ctx
        self._t = 0.0

        menu = MenuList(bus=ctx.bus)
        # Centred button row pinned above the footer hint; the old offset
        # pushed the last button past the right edge of the viewport.
        width = 320
        gap = 30
        x = (LOGICAL_W - (width * 3 + gap * 2)) // 2
        y = BUTTON_Y
        menu.add(Button("results.rematch", x, y, width, "REMATCH",
                        primary=True, hotkey="ENTER"))
        menu.add(Button("results.replay", x + width + gap, y, width,
                        "WATCH REPLAY", hotkey="W"))
        menu.add(Button("results.menu", x + (width + gap) * 2, y, width,
                        "MAIN MENU", hotkey="ESC"))
        self.menu = menu

        replay = ctx.storage.load_replay()
        button = self.menu.get("results.replay")
        if button is not None:
            button.enabled = replay is not None

        if not self._unsubs:
            self._unsubs = [
                ctx.bus.subscribe(EventType.UI_MOVE,
                                  lambda e: ctx.audio.play("ui_move",
                                                           volume=0.6)),
                ctx.bus.subscribe(EventType.UI_SELECT,
                                  lambda e: ctx.audio.play("ui_select")),
            ]

    def on_exit(self) -> None:
        for unsubscribe in self._unsubs:
            unsubscribe()
        self._unsubs.clear()

    # -- input ------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._action("results.menu")
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_w:
            self._action("results.replay")
            return
        action = self.menu.handle_event(event, self.ctx.bus)
        if action:
            self._action(action)

    def _action(self, action: str) -> None:
        from .gameplay import GameplayScene
        from .menu import MenuScene
        from .replay_scene import ReplayScene

        ctx = self.ctx
        stack = self.stack
        assert stack is not None

        if action == "results.rematch":
            ctx.audio.play("ui_select")
            stack.replace_top(2, GameplayScene(**self.params),
                              transition=Transition.FADE)
        elif action == "results.replay":
            payload = ctx.storage.load_replay()
            if payload is None:
                ctx.audio.play("deny")
                return
            ctx.audio.play("ui_select")
            stack.push(ReplayScene(payload), transition=Transition.FADE)
        elif action == "results.menu":
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
        t = self._t
        draw_backdrop(surface, t, seed=4242, vignette=92)

        payload = self.payload
        winner = payload.get("winner", 0)
        score = payload.get("score", (0, 0))
        mode = payload.get("mode", GameMode.SOLO)
        difficulty = payload.get("difficulty")
        duration = float(payload.get("duration", 0.0))
        longest = int(payload.get("longest_rally", 0))
        summary = payload.get("summary", {}) or {}
        focus = payload.get("focus") if mode is GameMode.FOCUS else None

        # -- headline ----------------------------------------------------
        headline, color = self._headline(winner, mode, fonts)
        y_rect = draw_title(surface, headline, fonts, y=96, size=78,
                            color=color, center_x=LOGICAL_W // 2)

        # A run's "score" is how long it survived, so that is the number that
        # takes the place of the two duel digits.
        if focus is not None:
            headline_line = format_duration(float(focus.get("time", 0.0)))
        else:
            headline_line = f"{score[0]}  -  {score[1]}"
        score_line = fonts.render(headline_line, 64,
                                  Color.TEXT, bold=True, outline=3,
                                  outline_color=Color.BG)
        surface.blit(score_line, (LOGICAL_W // 2 - score_line.get_width() // 2,
                                  y_rect.bottom + 18))

        rule = payload.get("label", "")
        rule_text = fonts.render(rule, 16, Color.TEXT_DIM, bold=True)
        surface.blit(rule_text, (LOGICAL_W // 2 - rule_text.get_width() // 2,
                                 y_rect.bottom + 96))

        # -- summary panel ----------------------------------------------
        panel = pygame.Rect(LOGICAL_W // 2 - 430, PANEL_Y, 860, PANEL_H)
        draw_panel(surface, panel, accent=color, alpha=205,
                   title=("run summary" if focus is not None
                          else "match summary"), fonts=fonts)

        cells = self._cells(summary, duration=duration, longest=longest,
                            score=score, focus=focus)
        col_w = panel.w // 3
        row_h = 74
        for i, cell in enumerate(cells):
            label, value, value_color = cell[0], cell[1], cell[2]
            new_best = cell[3] if len(cell) > 3 else False
            col = i % 3
            row = i // 3
            cx = panel.x + 26 + col * col_w
            cy = panel.y + 52 + row * row_h
            label_surf = fonts.render(label, 13, Color.TEXT_DIM, bold=True)
            surface.blit(label_surf, (cx, cy))
            value_surf = fonts.render(value, 27, value_color, bold=True)
            surface.blit(value_surf, (cx, cy + 20))
            if new_best:
                # Pinned to the value's baseline so it reads as a caption on
                # that figure rather than as a seventh cell.
                tag = fonts.render("NEW BEST", 12, Color.GOLD, bold=True)
                surface.blit(tag, (cx + value_surf.get_width() + 10,
                                   cy + value_surf.get_height() - tag.get_height()))

        # -- coin award ----------------------------------------------------
        # Sits immediately under the panel: it is the reason the player is
        # looking at this screen.  `earned` already folds in any Gold Rush
        # coins banked live during the match.
        earned = int(payload.get("earned", 0) or 0)
        coins = int(payload.get("coins", 0) or 0)
        live = int(payload.get("live_coins", 0) or 0)
        award_line = f"+{earned} COINS EARNED  ·  BALANCE {coins:,}"
        if live > 0:
            # A duel pays this out per return from Gold Rush; a FOCUS run's
            # live coins are all life-orb top-ups at full health.
            award_line += ("  (+{0} BONUS)".format(live) if focus is not None
                           else f"  (+{live} GOLD RUSH)")
        award = fonts.render(award_line, EARNED_H, Color.GOLD, bold=True,
                             shadow=True)
        surface.blit(award, (LOGICAL_W // 2 - award.get_width() // 2,
                             panel.bottom + EARNED_DY))

        # -- lifetime delta ---------------------------------------------
        stats = payload.get("stats", {}) or {}
        played = int(stats.get("matches_played", 0))
        wins = int(stats.get("wins", 0))
        win_rate = (wins / played) if played else 0.0
        if focus is not None:
            # A run never moves the win/loss counters, so quoting them here
            # would read as "you lost" on a screen that has just said there
            # is no loser.  Bests are what carry over instead.
            lifetime = fonts.render(
                f"BEST RUN  ·  {format_duration(stats.get('focus_best_time', 0.0))}"
                f"  ·  {int(stats.get('focus_best_returns', 0))} RETURNS  "
                f"·  {played} RUNS PLAYED",
                14, Color.ACCENT, bold=True)
        else:
            lifetime = fonts.render(
                f"LIFETIME  ·  {played} MATCHES  ·  {wins} WINS  "
                f"({win_rate * 100:.0f}%)  ·  BEST RALLY "
                f"{int(stats.get('longest_rally', 0))}",
                14, Color.ACCENT, bold=True)
        surface.blit(lifetime, (LOGICAL_W // 2 - lifetime.get_width() // 2,
                                panel.bottom + LIFETIME_DY))

        if difficulty is not None and mode is GameMode.SOLO:
            diff_note = fonts.render(
                f"DIFFICULTY {getattr(difficulty, 'value', difficulty).upper()}",
                13, Color.TEXT_DIM)
            surface.blit(diff_note, (LOGICAL_W // 2 - diff_note.get_width() // 2,
                                     panel.bottom + NOTE_DY))

        self.menu.draw(surface, fonts)

        hint = fonts.render("ENTER REMATCH   ·   W REPLAY   ·   ESC MAIN MENU",
                            13, Color.TEXT_DIM)
        surface.blit(hint, (LOGICAL_W // 2 - hint.get_width() // 2, HINT_Y))

    def _cells(self, summary, *, duration, longest, score, focus):  # type: ignore[no-untyped-def]
        """The six summary figures, chosen for the mode that just finished.

        Returns ``(label, value, colour[, new_best])`` tuples; the fourth
        element only appears where the payload can tell us a record moved.
        """
        rally_hits = int(summary.get("total_hits", 0))
        goals = int(summary.get("total_goals", 0))
        fastest = float(summary.get("fastest_ball", 0.0))
        p1_hits = (summary.get("hits_by_player") or (0, 0))[0]
        p2_hits = (summary.get("hits_by_player") or (0, 0))[1]

        if focus is not None:
            left = int(focus.get("lives_left", 0))
            start = int(focus.get("lives_start", 0))
            lost = int(focus.get("lives_lost", 0))
            return [
                ("SURVIVED", format_duration(duration), Color.GOLD,
                 bool(focus.get("new_time_best"))),
                ("RETURNS", f"{rally_hits}", Color.TEXT,
                 bool(focus.get("new_returns_best"))),
                ("LIVES LEFT", f"{left} / {start}", Color.ACCENT),
                ("LIVES LOST", f"{lost}", Color.WARN),
                ("LONGEST RALLY", f"{longest}", Color.TEXT),
                ("FASTEST BALL", f"{fastest:.0f} px/s", Color.WARN),
            ]
        return [
            ("DURATION", format_duration(duration), Color.TEXT),
            ("LONGEST RALLY", f"{longest}", Color.GOLD),
            ("TOTAL RETURNS", f"{rally_hits}", Color.TEXT),
            ("POINTS", f"{goals}", Color.TEXT),
            ("FASTEST BALL", f"{fastest:.0f} px/s", Color.WARN),
            ("RETURNS P1 / P2", f"{p1_hits} / {p2_hits}", Color.TEXT_DIM),
        ]

    def _headline(self, winner, mode, fonts):  # type: ignore[no-untyped-def]
        # Checked before the None branch: a FOCUS run ends with no winner at
        # all, which is a *run* rather than a draw between two players.
        if mode is GameMode.FOCUS:
            return "RUN OVER", Color.GOLD
        if winner is None:
            return "DRAW", Color.TEXT_DIM
        if mode is GameMode.TWO_PLAYER or mode is GameMode.AI_VS_AI:
            return f"PLAYER {int(winner) + 1} WINS", (
                Color.P1 if winner == 0 else Color.P2)
        if winner == 0:
            return "VICTORY", Color.ACCENT
        return "DEFEAT", Color.WARN


__all__ = ["ResultsScene"]
