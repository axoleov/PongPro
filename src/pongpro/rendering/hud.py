"""In-match HUD: scores, rally/match state, banners and telemetry.

Drawn last (on top of the world pass) and kept deliberately cheap: text comes
from the font cache, meters are a handful of ``draw.rect`` calls.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import pygame

from ..core.constants import (
    COURT_PAD_Y,
    Color,
    LOGICAL_H,
    LOGICAL_W,
    MatchPhase,
)
from .fonts import FontManager

_DIGIT_W = 58
_SCORE_SIZE = 96

#: Top of the match-state stack (target line).
STACK_TARGET_Y = 146
#: Top of the first match-state element that can collide (match point / deuce).
STACK_Y = 176
#: Ball-speed meter's top edge: its caption starts at ``SPEED_METER_Y - 18``,
#: which has to stay below the court's bottom wall (``LOGICAL_H - COURT_PAD_Y``)
#: and the meter itself has to stay above :data:`CONTROL_HINT_Y`.
SPEED_METER_Y = LOGICAL_H - 40
#: Baseline band for the in-match control hints drawn by the gameplay scene.
CONTROL_HINT_Y = LOGICAL_H - 24

#: How long the FOCUS life-pip caption swaps to a pickup confirmation.
LIFE_NOTE_SECONDS = 1.2

#: Powerup pill row.  Sits below the mode label (y=20..34) and beside the
#: score digits (which start around x=432 / end around x=848), so a pill
#: anchored at x=24 and one right-aligned at ``LOGICAL_W-24`` never collide
#: with the score, the serve marker or the FPS read-out.
POWERUP_Y = 58
POWERUP_H = 30
POWERUP_PAD_X = 24


class MatchStateLayout(NamedTuple):
    """Rectangles for every element sharing the HUD's centre strip."""

    target: pygame.Rect
    match_point: pygame.Rect | None = None
    deuce: pygame.Rect | None = None
    rally: pygame.Rect | None = None

    def rects(self) -> list[pygame.Rect]:
        return [r for r in (self.target, self.match_point, self.deuce,
                            self.rally) if r is not None]


def match_state_rects(fonts: FontManager, *, cx: int, target: int,
                      match_point: int | None, deuce: bool, rally: int,
                      rally_scale: float = 1.0) -> MatchStateLayout:
    """Lay out the target line, match-point pill, deuce label and rally counter.

    The elements share one vertical strip, so they are stacked in priority
    order here -- drawing them at fixed y coordinates made the rally counter
    render straight through the match-point pill.
    """
    target_surf = fonts.render(f"FIRST TO {target}", 15, Color.TEXT_DIM)
    out = MatchStateLayout(
        target=pygame.Rect(cx - target_surf.get_width() // 2,
                           STACK_TARGET_Y, *target_surf.get_size()))
    y = STACK_Y

    if match_point is not None:
        width = fonts.width("MATCH POINT", 17, bold=True) + 26
        out = out._replace(match_point=pygame.Rect(cx - width // 2, y, width, 28))
        y += 32

    if deuce:
        surf = fonts.render("DEUCE", 16, Color.WARN, bold=True,
                            outline=2, outline_color=Color.BG)
        out = out._replace(deuce=pygame.Rect(cx - surf.get_width() // 2, y,
                                             *surf.get_size()))
        y += surf.get_height() + 6

    if rally >= 2:
        surf = fonts.render(f"RALLY {rally}", max(1, int(26 * rally_scale)),
                            Color.BALL, bold=True,
                            outline=2, outline_color=Color.BG)
        out = out._replace(rally=pygame.Rect(cx - surf.get_width() // 2, y,
                                             *surf.get_size()))
    return out


class Hud:
    """Draws all persistent match information."""

    def __init__(self, fonts: FontManager) -> None:
        self.fonts = fonts
        self._flash = 0.0
        self._rally_pulse = 0.0
        self._banner_scale = 0.0
        self._life_pulse = 0.0
        self._life_note = ""
        self._life_note_timer = 0.0
        self._time = 0.0

    # -- animation --------------------------------------------------------
    def pulse_rally(self) -> None:
        self._rally_pulse = 1.0

    def pulse_life(self, note: str = "") -> None:
        """Kick the life-pip row (FOCUS), so a spend or a bank reads at once.

        ``note`` optionally swaps the row's caption for
        :data:`LIFE_NOTE_SECONDS`.  A pickup confirmation deliberately goes
        here rather than on the big centre banner: the ball is *live* when an
        orb is collected, and a banner across the middle of the court would be
        an obstacle the player has to steer around while already busy.
        """
        self._life_pulse = 1.0
        if note:
            self._life_note = note
            self._life_note_timer = LIFE_NOTE_SECONDS

    def flash(self) -> None:
        self._flash = 1.0

    def pop_banner(self) -> None:
        self._banner_scale = 1.0

    def update(self, dt: float) -> None:
        self._time += dt
        self._flash = max(0.0, self._flash - dt * 2.6)
        self._rally_pulse = max(0.0, self._rally_pulse - dt * 3.2)
        self._banner_scale = max(0.0, self._banner_scale - dt * 2.2)
        self._life_pulse = max(0.0, self._life_pulse - dt * 3.0)
        self._life_note_timer = max(0.0, self._life_note_timer - dt)

    # -- drawing ----------------------------------------------------------
    def draw(self, surface: pygame.Surface, *, score: tuple[int, int],
             phase: MatchPhase, rally: int, target: int,
             server: int | None, banner: str | None, countdown: str | None,
             fps: float, show_fps: bool, speed: float, max_speed: float,
             match_point: int | None, mode_label: str,
             match_over: bool, deuce: bool = False) -> None:
        fonts = self.fonts
        cx = LOGICAL_W // 2

        # --- scores -----------------------------------------------------
        left = fonts.render(str(score[0]), _SCORE_SIZE, Color.P1, bold=True,
                            outline=2, outline_color=Color.BG)
        right = fonts.render(str(score[1]), _SCORE_SIZE, Color.P2, bold=True,
                             outline=2, outline_color=Color.BG)
        surface.blit(left, (cx - 150 - left.get_width(), 44))
        surface.blit(right, (cx + 150, 44))

        divider = fonts.render(":", _SCORE_SIZE - 24, Color.TEXT_DIM, bold=True)
        surface.blit(divider, (cx - divider.get_width() // 2, 58))

        # --- match state stack ------------------------------------------
        # Target line, match-point pill, deuce label and the rally counter all
        # share the vertical centre strip; positions come from
        # ``match_state_rects`` so the stacking is testable.
        pop = 1.0 + self._rally_pulse * 0.35
        layout = match_state_rects(
            fonts, cx=cx, target=target, match_point=match_point,
            deuce=deuce, rally=rally, rally_scale=pop)

        # --- serve indicator -------------------------------------------
        if server is not None and not match_over:
            marker_x = cx - 150 - left.get_width() - 26 if server == 0 else cx + 150 + right.get_width() + 14
            color = Color.P1 if server == 0 else Color.P2
            pygame.draw.circle(surface, color, (int(marker_x), 96), 6)

        surface.blit(fonts.render(f"FIRST TO {target}", 15, Color.TEXT_DIM),
                     layout.target.topleft)

        # --- match point banner ----------------------------------------
        if layout.match_point is not None:
            rect = layout.match_point
            pulse = 0.5 + 0.5 * pygame.time.get_ticks() / 260.0
            pygame.draw.rect(surface,
                             Color.blend(Color.PANEL, Color.WARN, 0.35 + 0.35 * pulse),
                             rect, border_radius=6)
            rendered = fonts.render("MATCH POINT", 17, Color.TEXT, bold=True)
            surface.blit(rendered, (rect.x + 13, rect.y + 5))

        # --- deuce label ------------------------------------------------
        if layout.deuce is not None:
            surface.blit(fonts.render("DEUCE", 16, Color.WARN, bold=True,
                                      outline=2, outline_color=Color.BG),
                         layout.deuce.topleft)

        self._draw_chrome(
            surface, phase=phase, banner=banner, countdown=countdown, fps=fps,
            show_fps=show_fps, speed=speed, max_speed=max_speed,
            mode_label=mode_label, match_over=match_over,
            rally=rally, rally_pos=(layout.rally.topleft
                                    if layout.rally is not None else None),
            rally_scale=pop)

    def draw_focus(self, surface: pygame.Surface, *, lives: int, max_lives: int,
                   returns: int, time_label: str, phase: MatchPhase, rally: int,
                   banner: str | None, countdown: str | None, fps: float,
                   show_fps: bool, speed: float, max_speed: float,
                   mode_label: str, match_over: bool) -> None:
        """FOCUS has no score to put where the duel's digits live.

        The centre band is instead the life budget, because that is the only
        thing the player is spending; time and returns flank it the way the
        two scores used to, so the eye still lands in the same place.  Lives
        are drawn as pips rather than as text - a count you can *glance* at
        beats one you have to read when both hands are already busy.
        """
        fonts = self.fonts
        cx = LOGICAL_W // 2

        self._draw_life_pips(surface, cx=cx, lives=lives, max_lives=max_lives)

        # Flanking read-outs, on the same baseline as the old score digits.
        self._draw_focus_stat(surface, "TIME", time_label, Color.GOLD,
                              align="left")
        self._draw_focus_stat(surface, "RETURNS", str(max(0, int(returns))),
                              Color.P1, align="right")

        pop = 1.0 + self._rally_pulse * 0.35
        rally_pos = None
        if rally >= 2:
            rally_pos = (cx - fonts.width(f"RALLY {rally}",
                                          max(1, int(26 * pop)), bold=True) // 2,
                         STACK_Y)

        self._draw_chrome(
            surface, phase=phase, banner=banner, countdown=countdown, fps=fps,
            show_fps=show_fps, speed=speed, max_speed=max_speed,
            mode_label=mode_label, match_over=match_over,
            rally=rally, rally_pos=rally_pos, rally_scale=pop)

    def _draw_life_pips(self, surface: pygame.Surface, *, cx: int,
                        lives: int, max_lives: int) -> None:
        """The remaining-life row, centred in the band the scores used to fill."""
        fonts = self.fonts
        total = max(1, int(max_lives))
        remaining = max(0, min(total, int(lives)))
        pip_w, pip_h, gap = 26, 20, 9
        row_w = total * pip_w + (total - 1) * gap
        x0 = cx - row_w // 2
        y = 40

        last = remaining == 1 and total > 1
        # The single surviving pip breathes red so the closing seconds of a
        # run feel like the emergency they are.
        warn = 0.5 + 0.5 * math.sin(self._time * 6.0)
        spent = 0.35 + self._life_pulse * 0.65

        for i in range(total):
            rect = pygame.Rect(x0 + i * (pip_w + gap), y, pip_w, pip_h)
            if i < remaining:
                base = Color.WARN if last else Color.GOLD
                fill = Color.blend(Color.PANEL, base, 0.55 + 0.45 * spent)
                if last:
                    fill = Color.blend(fill, Color.WARN, 0.45 * warn)
                pygame.draw.rect(surface, fill, rect, border_radius=5)
                pygame.draw.rect(surface, Color.blend(fill, (255, 255, 255), 0.45),
                                 rect.move(2, 2).inflate(-4, -8),
                                 border_radius=3)
                pygame.draw.rect(surface, Color.blend(base, (255, 255, 255), 0.5),
                                 rect, width=2, border_radius=5)
            else:
                pygame.draw.rect(surface, Color.blend(Color.PANEL, Color.BG, 0.5),
                                 rect, border_radius=5)
                pygame.draw.rect(surface, Color.blend(Color.LINE_SOFT, Color.WARN,
                                                      0.45 * spent),
                                 rect, width=2, border_radius=5)

        # Caption priority: a live pickup confirmation outranks the standing
        # warning, which outranks the plain label.
        if self._life_note_timer > 0.0 and self._life_note:
            caption, color = self._life_note, Color.GOLD
        elif last:
            caption, color = "LAST LIFE", Color.WARN
        else:
            caption, color = "LIVES", Color.TEXT_DIM
        text = fonts.render(caption, 13, color, bold=True)
        surface.blit(text, (cx - text.get_width() // 2, y + pip_h + 8))

    def _draw_focus_stat(self, surface: pygame.Surface, label: str, value: str,
                         color: tuple[int, int, int], *, align: str) -> None:
        """One ``LABEL  value`` read-out pinned to a top corner."""
        fonts = self.fonts
        key = fonts.render(label, 13, Color.TEXT_DIM, bold=True)
        val = fonts.render(value, 26, color, bold=True)
        if align == "left":
            x = 24
            surface.blit(key, (x, 42))
            surface.blit(val, (x, 42 + key.get_height() + 2))
        else:
            x = LOGICAL_W - 24
            surface.blit(key, (x - key.get_width(), 42))
            surface.blit(val, (x - val.get_width(), 42 + key.get_height() + 2))

    def _draw_chrome(self, surface: pygame.Surface, *, phase: MatchPhase,
                     banner: str | None, countdown: str | None, fps: float,
                     show_fps: bool, speed: float, max_speed: float,
                     mode_label: str, match_over: bool, rally: int,
                     rally_pos: tuple[int, int] | None,
                     rally_scale: float = 1.0) -> None:
        """Everything the duel HUD and the FOCUS HUD genuinely share.

        Split out so the two layouts cannot drift: the speed meter, the
        countdown, the banner, the mode label and the telemetry are the same
        rules presentation in both modes, and only the band above them
        differs.
        """
        fonts = self.fonts
        cx = LOGICAL_W // 2

        # --- rally counter ---------------------------------------------
        if rally_pos is not None:
            surface.blit(fonts.render(f"RALLY {rally}", max(1, int(26 * rally_scale)),
                                      Color.BALL, bold=True,
                                      outline=2, outline_color=Color.BG),
                         rally_pos)

        # --- ball speed meter ------------------------------------------
        if speed > 0.0 and phase is not MatchPhase.COUNTDOWN:
            meter_w = 260
            # Kept clear of the control hints pinned to the bottom edge.
            rect = pygame.Rect(cx - meter_w // 2, SPEED_METER_Y, meter_w, 8)
            pygame.draw.rect(surface, Color.PANEL, rect, border_radius=4)
            fraction = max(0.0, min(1.0, speed / max_speed))
            fill = pygame.Rect(rect.x, rect.y, int(rect.w * fraction), rect.h)
            hue = Color.blend(Color.ACCENT, Color.WARN, fraction)
            pygame.draw.rect(surface, hue, fill, border_radius=4)
            label = fonts.render("BALL SPEED", 12, Color.TEXT_DIM)
            surface.blit(label, (rect.x, rect.y - 18))

        # --- countdown --------------------------------------------------
        if countdown is not None and banner is None:
            rendered = fonts.render(countdown, 128, Color.TEXT, bold=True,
                                    outline=3, outline_color=Color.BG)
            surface.blit(rendered, (cx - rendered.get_width() // 2,
                                    LOGICAL_H // 2 - 96))

        # --- big banner -------------------------------------------------
        if banner is not None:
            scale = 1.0 + self._banner_scale * 0.6
            size = int(64 * scale)
            color = Color.GOLD if match_over else (
                Color.ACCENT if banner in ("GO!", "READY") else Color.BALL)
            rendered = fonts.render(banner, size, color, bold=True,
                                    outline=3, outline_color=Color.BG)
            surface.blit(rendered, (cx - rendered.get_width() // 2,
                                    LOGICAL_H // 2 - rendered.get_height() - 10))

        # --- mode + telemetry ------------------------------------------
        mode = fonts.render(mode_label, 14, Color.TEXT_DIM)
        surface.blit(mode, (24, 20))

        if show_fps:
            fps_text = fonts.render(f"{fps:5.1f} FPS", 15,
                                    Color.ACCENT if fps >= 55 else
                                    (Color.GOLD if fps >= 30 else Color.WARN),
                                    bold=True)
            surface.blit(fps_text, (LOGICAL_W - fps_text.get_width() - 24, 20))

        if self._flash > 0.0:
            overlay = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
            overlay.fill((*Color.TEXT, int(70 * self._flash)))
            surface.blit(overlay, (0, 0))

    def draw_input_hint(self, surface: pygame.Surface, text: str,
                        align: str = "left", y: int | None = None) -> None:
        rendered = self.fonts.render(text, 14, Color.TEXT_DIM)
        if align == "left":
            x = 24
        else:
            x = LOGICAL_W - rendered.get_width() - 24
        surface.blit(rendered, (x, CONTROL_HINT_Y if y is None else y))

    def draw_powerup_pill(self, surface: pygame.Surface, *,
                          name: str, key: str, accent: tuple[int, int, int],
                          ready: bool, cooldown: float, active: float,
                          cooldown_total: float, align: str = "left") -> pygame.Rect:
        """Draw one player's powerup status pill and return its rectangle.

        The pill is a single line of text plus a 3px progress rail along its
        bottom edge: full when ready or firing, draining while on cooldown.
        ``key`` is the activation hint (``"SPACE"``, ``"ENTER"``) and may be
        empty for AI-driven paddles.
        """
        fonts = self.fonts
        if active > 0.0:
            state, state_color = f"ACTIVE {active:.1f}s", Color.GOLD
        elif ready:
            state, state_color = (f"{key} READY" if key else "READY"), Color.ACCENT
        else:
            state, state_color = (f"{key} {cooldown:.1f}s" if key
                                  else f"{cooldown:.1f}s"), Color.TEXT_DIM

        name_surf = fonts.render(name, 13, accent, bold=True)
        state_surf = fonts.render(state, 13, state_color, bold=True)
        width = 16 + name_surf.get_width() + 10 + state_surf.get_width() + 16
        x = POWERUP_PAD_X if align == "left" else LOGICAL_W - POWERUP_PAD_X - width
        rect = pygame.Rect(x, POWERUP_Y, width, POWERUP_H)

        pygame.draw.rect(surface, Color.blend(Color.PANEL, accent, 0.18),
                         rect, border_radius=8)
        pygame.draw.rect(surface, Color.blend(Color.LINE_SOFT, accent, 0.6),
                         rect, width=1, border_radius=8)
        surface.blit(name_surf, (rect.x + 8, rect.centery - name_surf.get_height() // 2))
        surface.blit(state_surf, (rect.right - state_surf.get_width() - 8,
                                  rect.centery - state_surf.get_height() // 2))

        # Progress rail: how close the powerup is to being usable again.
        if active > 0.0:
            fraction = 1.0
        elif cooldown_total > 0.0:
            fraction = max(0.0, min(1.0, 1.0 - cooldown / cooldown_total))
        else:
            fraction = 1.0
        rail = pygame.Rect(rect.x + 6, rect.bottom - 5, rect.w - 12, 3)
        pygame.draw.rect(surface, Color.blend(Color.PANEL_LIGHT, Color.BG, 0.4),
                         rail, border_radius=2)
        if fraction > 0.0:
            fill = pygame.Rect(rail.x, rail.y, max(1, int(rail.w * fraction)),
                               rail.h)
            pygame.draw.rect(surface, state_color, fill, border_radius=2)
        return rect
