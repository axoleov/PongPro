"""Replay viewer: scrubs the recorded match frame-by-frame.

The recorder captured raw simulation snapshots at 120 Hz, so playback is a
matter of rebuilding paddles/ball from one frame - no physics re-simulation,
which means replays stay perfectly accurate even after balance patches.
"""

from __future__ import annotations

import pygame

from ..core.constants import (
    BALL_RADIUS,
    Color,
    LOGICAL_H,
    LOGICAL_W,
    PADDLE_H,
    PADDLE_W,
)
from ..core.state_machine import Scene, Transition
from ..economy.catalog import (
    ITEMS_BY_ID,
    BackgroundLook,
    BallLook,
    ImpactLook,
    PaddleLook,
    ShopCategory,
    TrailLook,
    get_item,
)
from ..gameplay.entities import default_court
from ..gameplay.replay import Frame, ReplayPlayer
from ..rendering.particles import ParticleSystem
from ..rendering.skins import (
    CLASSIC_BACKGROUND,
    draw_ball,
    draw_paddle,
    draw_trail,
    emit_impact,
    glow_sprite,
)
from .common import draw_backdrop, draw_panel, render_court

SPEEDS = (0.25, 0.5, 1.0, 2.0)

# -- transport block -------------------------------------------------------
# The whole block lives in the band *below* the court's bottom wall
# (``LOGICAL_H - COURT_PAD_Y`` = 656).  It used to be drawn at
# ``LOGICAL_H - 104`` / ``-74`` / ``-44``, which put the status line straight
# through the court's left vertical wall and the scrub bar through both side
# walls.  Order top -> bottom: status line, scrub bar, key legend.
TRANSPORT_Y = LOGICAL_H - 58  # status (15px)  -> 662..677
BAR_Y = LOGICAL_H - 38        # scrub  (10px)  -> 682..692
CONTROLS_Y = LOGICAL_H - 20   # legend (13px)  -> 700..713
BAR_H = 10
STATUS_H = 15
CONTROLS_H = 13


class ReplayScene(Scene):
    """Playback with transport controls (play/pause, seek, speed)."""

    opaque = True

    def __init__(self, payload: dict) -> None:
        super().__init__()
        self.payload = payload
        self.player: ReplayPlayer | None = None
        self.court = default_court()
        self.index = 0.0  # fractional frame index for smooth scrubbing
        self.playing = True
        self.speed = 1.0
        self._t = 0.0
        self._court_surface: pygame.Surface | None = None
        self._particles: ParticleSystem | None = None
        self._last_impact_frame = -1
        # The cosmetics worn during the recorded match.  Defaults until
        # _load_looks() reads them out of the payload.
        self.ball_look: BallLook = get_item("ball.classic").data
        self.paddle_look: PaddleLook = get_item("paddle.classic").data
        self.background_look: BackgroundLook = CLASSIC_BACKGROUND
        self.trail_look: TrailLook = get_item("trail.classic").data
        self.impact_look: ImpactLook = get_item("impact.classic").data
        self._glow_ball: pygame.Surface | None = None
        self._glow_p1: pygame.Surface | None = None
        self._glow_p2: pygame.Surface | None = None

    # -- lifecycle --------------------------------------------------------
    def on_enter(self, **kwargs) -> None:
        self.player = ReplayPlayer(self.payload)
        self.index = 0.0
        self.playing = True
        self.speed = 1.0
        self._t = 0.0
        self._last_impact_frame = -1
        self._load_looks()
        if self.ctx is not None:
            self._particles = ParticleSystem(self.ctx.rng.fork())
        self._court_surface = render_court(self.court, self.background_look)
        self._glow_ball = glow_sprite(self.ball_look.fill, 64)
        self._glow_p1 = glow_sprite(Color.P1, 48)
        self._glow_p2 = glow_sprite(Color.P2, 48)

    def _load_looks(self) -> None:
        """Resolve the cosmetics frozen into the recording.

        Replays saved before the loadout was recorded - or by a build whose
        catalog has since changed - fall back to the classic skins, so the
        viewer never refuses to open an old file.
        """
        loadout = self.payload.get("loadout")
        if not isinstance(loadout, dict):
            loadout = {}

        def look_for(category: ShopCategory, fallback_id: str):
            item = ITEMS_BY_ID.get(loadout.get(category.value, fallback_id))
            if item is not None and item.category is category:
                return item.data
            return get_item(fallback_id).data

        self.ball_look = look_for(ShopCategory.BALL, "ball.classic")
        self.paddle_look = look_for(ShopCategory.PADDLE, "paddle.classic")
        self.background_look = look_for(ShopCategory.BACKGROUND, "bg.classic")
        self.trail_look = look_for(ShopCategory.TRAIL, "trail.classic")
        self.impact_look = look_for(ShopCategory.IMPACT, "impact.classic")

    def _seek(self, delta_seconds: float) -> None:
        if self.player is None:
            return
        target = (self.index / self.player.fps) + delta_seconds
        self.index = max(0.0, min(self.player.frame_count - 1,
                                  target * self.player.fps))

    # -- input ------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        key = event.key
        if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
            assert self.stack is not None
            self.ctx.audio.play("ui_back")
            self.stack.pop(transition=Transition.FADE)
        elif key in (pygame.K_SPACE, pygame.K_k):
            self._toggle()
        elif key in (pygame.K_LEFT, pygame.K_COMMA):
            mod = getattr(event, "mod", 0)
            self._seek(-5.0 if (mod & pygame.KMOD_SHIFT) else -1.0)
            self.ctx.audio.play("ui_move", volume=0.7)
        elif key in (pygame.K_RIGHT, pygame.K_PERIOD):
            mod = getattr(event, "mod", 0)
            self._seek(5.0 if (mod & pygame.KMOD_SHIFT) else 1.0)
            self.ctx.audio.play("ui_move", volume=0.7)
        elif key == pygame.K_r:
            self.index = 0.0
            self.playing = True
        elif key in (pygame.K_LEFTBRACKET, pygame.K_MINUS):
            self._cycle_speed(-1)
        elif key in (pygame.K_RIGHTBRACKET, pygame.K_EQUALS):
            self._cycle_speed(1)
        elif key == pygame.K_HOME:
            self.index = 0.0
        elif key == pygame.K_END:
            if self.player:
                self.index = float(self.player.frame_count - 1)
                self.playing = False

    def _toggle(self) -> None:
        if self.player is None:
            return
        if not self.playing and self.index >= self.player.frame_count - 1:
            self.index = 0.0
        self.playing = not self.playing
        self.ctx.audio.play("ui_select" if self.playing else "ui_back")

    def _cycle_speed(self, direction: int) -> None:
        current = SPEEDS.index(self.speed) if self.speed in SPEEDS else 2
        self.speed = SPEEDS[(current + direction) % len(SPEEDS)]
        self.ctx.audio.play("ui_move", volume=0.7)

    # -- frame ------------------------------------------------------------
    def update(self, dt: float) -> None:
        self._t += dt
        if self._particles is not None:
            self._particles.update(dt)
        if self.player is None:
            return
        if self.playing:
            self.index += dt * self.player.fps * self.speed
            if self.index >= self.player.frame_count - 1:
                self.index = float(self.player.frame_count - 1)
                self.playing = False
                self.ctx.audio.play("ui_back", volume=0.6)

    def draw(self, surface: pygame.Surface) -> None:
        assert self.player is not None and self._court_surface is not None
        fonts = self.ctx.fonts
        draw_backdrop(surface, self._t, seed=5, vignette=70,
                      look=self.background_look)
        surface.blit(self._court_surface, (0, 0))

        frame_index = int(self.index)
        frame = self.player.at(frame_index)
        self._draw_world(surface, frame, frame_index)
        self._draw_overlay(surface, frame, frame_index)

    # -- world ------------------------------------------------------------
    def _draw_world(self, surface: pygame.Surface, frame: Frame,
                    frame_index: int) -> None:
        # Trail sampled from the preceding recorded frames, expressed in the
        # same [x, y, life] shape the match scene feeds to the skin renderer,
        # so replay and live play draw the ball with one code path.
        points: list[list[float]] = []
        trail_start = max(0, frame_index - 16)
        span = max(1.0, float(frame_index - trail_start))
        for i in range(trail_start, frame_index + 1, 2):
            sample = self.player.at(i)
            points.append([sample.bx, sample.by,
                           1.0 - (frame_index - i) / span])
        draw_trail(surface, points, self.trail_look, BALL_RADIUS)

        # Paddles
        half_w, half_h = PADDLE_W // 2, PADDLE_H // 2
        for x, y, color, glow in (
            (self.court.left + 26 + half_w, frame.p1y, Color.P1, self._glow_p1),
            (self.court.right - 26 - half_w, frame.p2y, Color.P2,
             self._glow_p2),
        ):
            rect = pygame.Rect(int(x - half_w), int(y - half_h),
                               PADDLE_W, PADDLE_H)
            draw_paddle(surface, rect, color, self.paddle_look, glow=glow)

        # Ball - the halo grows with recorded speed, as it does in a match.
        speed_boost = 1.0 + min(0.6, frame.ball_speed / 1400.0)
        draw_ball(surface, frame.bx, frame.by, BALL_RADIUS, self.ball_look,
                  glow=self._glow_ball, glow_boost=speed_boost)

        self._emit_recorded_impacts(frame, frame_index)
        if self._particles is not None:
            self._particles.draw(surface)

    def _emit_recorded_impacts(self, frame: Frame, frame_index: int) -> None:
        """Fire the equipped hit effect wherever the recording turned around.

        A sign flip in the recorded ball velocity *is* the contact event, so
        the viewer can show real impacts without re-simulating the physics -
        which keeps playback exact even after a balance patch.
        """
        if (self._particles is None or self.player is None
                or frame_index <= 0 or frame_index == self._last_impact_frame):
            return
        self._last_impact_frame = frame_index
        previous = self.player.at(frame_index - 1)
        # One recorded step is ~8ms, so a real bounce flips the sign outright
        # and carries speed; a near-miss does neither.
        if (previous.bvx > 0) != (frame.bvx > 0) and abs(frame.bvx) > 20.0:
            emit_impact(self._particles, self.impact_look,
                        frame.bx, frame.by, self.ball_look.fill,
                        outgoing=frame.bvx, scale=0.8)
        if (previous.bvy > 0) != (frame.bvy > 0) and abs(frame.bvy) > 20.0:
            emit_impact(self._particles, self.impact_look,
                        frame.bx, frame.by, self.ball_look.fill,
                        normal=frame.bvy, scale=0.6)

    # -- overlay ----------------------------------------------------------
    def _draw_overlay(self, surface: pygame.Surface, frame: Frame,
                      frame_index: int) -> None:
        assert self.player is not None
        fonts = self.ctx.fonts
        player = self.player

        banner = pygame.Rect(LOGICAL_W // 2 - 300, 24, 600, 84)
        draw_panel(surface, banner, accent=Color.GOLD, alpha=190, fonts=fonts)
        label = fonts.render("REPLAY", 15, Color.GOLD, bold=True)
        surface.blit(label, (banner.x + 20, banner.y + 14))
        title = fonts.render(str(player.payload.get("label", "MATCH")), 18,
                             Color.TEXT, bold=True)
        surface.blit(title, (banner.x + 20, banner.y + 38))

        score = fonts.render(f"{frame.s1}  -  {frame.s2}", 40, Color.TEXT,
                             bold=True)
        surface.blit(score, (banner.right - 20 - score.get_width(),
                             banner.y + 18))
        rally = fonts.render(f"RALLY {frame.rally}", 13, Color.TEXT_DIM,
                             bold=True)
        surface.blit(rally, (banner.right - 20 - rally.get_width(),
                             banner.y + 64))

        # Transport bar
        bar = pygame.Rect(60, BAR_Y, LOGICAL_W - 120, BAR_H)
        pygame.draw.rect(surface, Color.PANEL_LIGHT, bar, border_radius=5)
        progress = frame_index / max(1, player.frame_count - 1)
        fill = pygame.Rect(bar.x, bar.y, int(bar.w * progress), bar.h)
        pygame.draw.rect(surface, Color.GOLD, fill, border_radius=5)
        pygame.draw.circle(surface, Color.TEXT, (fill.right, bar.centery), 8)

        state = "PLAYING" if self.playing else "PAUSED"
        speed_text = f"{self.speed:g}x" if self.speed != 1.0 else "1x"
        left = fonts.render(
            f"{state}  ·  {speed_text}  ·  "
            f"{frame.t:05.1f}s / {player.duration:05.1f}s",
            15, Color.TEXT, bold=True)
        surface.blit(left, (bar.x, TRANSPORT_Y))

        controls = fonts.render(
            "SPACE PLAY/PAUSE   ·   ←/→ SEEK (SHIFT = 5s)   ·   "
            "[ ] SPEED   ·   R RESTART   ·   ESC BACK",
            13, Color.TEXT_DIM)
        surface.blit(controls, (LOGICAL_W // 2 - controls.get_width() // 2,
                                CONTROLS_Y))

        if not self.playing and frame_index >= player.frame_count - 1:
            end = fonts.render("END OF REPLAY", 30, Color.TEXT, bold=True,
                               outline=3, outline_color=Color.BG)
            surface.blit(end, (LOGICAL_W // 2 - end.get_width() // 2,
                               LOGICAL_H // 2 - 90))


__all__ = ["ReplayScene"]
