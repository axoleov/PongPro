"""Settings screen: audio, video and gameplay options in one scroll-free list.

Values are written back to :class:`Settings` **continuously** (so sliders feel
live), validated, persisted atomically, and pushed to the running subsystems
(audio volumes, video mode, particle quality) the moment they change.
"""

from __future__ import annotations

import pygame

from ..core.constants import (
    Color,
    Difficulty,
    GameMode,
    ParticleQuality,
)
from ..core.events import EventType
from ..core.state_machine import Scene, Transition
from ..rendering.ui import (
    Button,
    MenuList,
    OptionCycle,
    Slider,
    StaticText,
    Toggle,
)
from .common import draw_backdrop, draw_panel, draw_title

_WINDOW_SIZES = [(1280, 720), (1600, 900), (1920, 1080), (2560, 1440)]


class SettingsScene(Scene):
    opaque = True

    def __init__(self) -> None:
        super().__init__()
        self.menu = MenuList()
        self._t = 0.0
        self._unsubs: list = []
        self._dirty_video = False
        self._dirty_quality = False
        # Three fixed columns keep every section on screen: the old two-column
        # split needed ~600px of vertical space in a 720px viewport, so the
        # gameplay rows collided with the action bar and the preview panel.
        self._cols = (55, 455, 855)
        self._x = self._cols[0]
        self._width = 370
        self._header_y = 160
        self._top = 200
        self._step = 50
        self._action_top = 474
        self._preview_rect = pygame.Rect(self._cols[0], self._action_top,
                                         self._width, 116)

    # -- lifecycle --------------------------------------------------------
    def on_enter(self, **kwargs) -> None:
        self._t = 0.0
        self._dirty_video = False
        self._dirty_quality = False
        self._build()
        if not self._unsubs:
            ctx = self.ctx
            self._unsubs = [
                ctx.bus.subscribe(EventType.UI_MOVE, lambda e: ctx.audio.play(
                    "ui_move", volume=0.6)),
                ctx.bus.subscribe(EventType.UI_SELECT, lambda e: ctx.audio.play(
                    "ui_select")),
                ctx.bus.subscribe(EventType.UI_BACK, lambda e: ctx.audio.play(
                    "deny", volume=0.7) if e.get("blocked") else None),
            ]

    def on_exit(self) -> None:
        for unsubscribe in self._unsubs:
            unsubscribe()
        self._unsubs.clear()
        self._commit(persist=True)

    def _build(self) -> None:
        ctx = self.ctx
        settings = ctx.settings
        audio, video, gameplay = settings.audio, settings.video, settings.gameplay
        menu = MenuList(bus=ctx.bus)

        col_audio, col_video, col_game = self._cols
        width = self._width
        top = self._top
        step = self._step
        header_y = self._header_y

        # ---------------- audio (column 1) ----------------
        menu.add(StaticText(col_audio, header_y, width, "audio", size=13,
                            color=Color.ACCENT))
        menu.add(Slider("audio.master", col_audio, top, width, "Master",
                        0.0, 1.0, audio.master, step=0.05,
                        formatter=lambda v: f"{v * 100:.0f}%"))
        menu.add(Slider("audio.sfx", col_audio, top + step, width, "Effects",
                        0.0, 1.0, audio.sfx, step=0.05,
                        formatter=lambda v: f"{v * 100:.0f}%"))
        menu.add(Slider("audio.music", col_audio, top + step * 2, width, "Music",
                        0.0, 1.0, audio.music, step=0.05,
                        formatter=lambda v: f"{v * 100:.0f}%"))
        menu.add(Toggle("audio.muted", col_audio, top + step * 3, width,
                        "Mute all", audio.muted))
        menu.add(Toggle("audio.music_enabled", col_audio, top + step * 4, width,
                        "Music enabled", audio.music_enabled))

        # ---------------- video (column 2) ----------------
        menu.add(StaticText(col_video, header_y, width, "video", size=13,
                            color=Color.GOLD))
        menu.add(Toggle("video.fullscreen", col_video, top, width, "Fullscreen",
                        video.fullscreen))
        size_index = 0
        for i, (w, h) in enumerate(_WINDOW_SIZES):
            if (video.window_width, video.window_height) == (w, h):
                size_index = i
        menu.add(OptionCycle("video.window", col_video, top + step, width,
                             "Window size",
                             [(s, f"{s[0]} x {s[1]}") for s in _WINDOW_SIZES],
                             size_index))
        menu.add(OptionCycle("video.fps", col_video, top + step * 2, width,
                             "Frame limit",
                             [(0, "UNCAPPED"), (60, "60 FPS"), (120, "120 FPS"),
                              (144, "144 FPS"), (240, "240 FPS")],
                             [0, 60, 120, 144, 240].index(video.fps_cap)
                             if video.fps_cap in (0, 60, 120, 144, 240) else 3))
        menu.add(Toggle("video.vsync", col_video, top + step * 3, width, "VSync",
                        video.vsync))
        menu.add(Toggle("video.show_fps", col_video, top + step * 4, width,
                        "Show FPS counter", video.show_fps))
        menu.add(Toggle("video.screen_shake", col_video, top + step * 5, width,
                        "Screen shake", video.screen_shake))
        menu.add(OptionCycle("video.particles", col_video, top + step * 6, width,
                             "Particle FX",
                             [(q, q.value.upper()) for q in ParticleQuality],
                             [q for q in ParticleQuality].index(video.particles)))
        menu.add(Slider("video.ui_scale", col_video, top + step * 7, width,
                        "Text size", 0.75, 2.0, video.ui_scale, step=0.05,
                        formatter=lambda v: f"{v * 100:.0f}%"))

        # ---------------- gameplay (column 3) ----------------
        menu.add(StaticText(col_game, header_y, width, "gameplay", size=13,
                            color=Color.P2))
        menu.add(OptionCycle("gameplay.mode", col_game, top, width, "Mode",
                             [(m, m.value.replace("_", " ").upper())
                              for m in GameMode],
                             [m for m in GameMode].index(gameplay.mode)))
        menu.add(OptionCycle("gameplay.difficulty", col_game, top + step, width,
                             "AI level",
                             [(d, d.value.upper()) for d in Difficulty],
                             [d for d in Difficulty].index(gameplay.difficulty)))
        menu.add(OptionCycle("gameplay.target", col_game, top + step * 2, width,
                             "First to",
                             [(n, f"{n} POINTS") for n in (1, 3, 5, 7, 11, 21)],
                             [1, 3, 5, 7, 11, 21].index(gameplay.target_score)
                             if gameplay.target_score in (1, 3, 5, 7, 11, 21)
                             else 2))
        menu.add(Toggle("gameplay.rally_speedup", col_game, top + step * 3,
                        width, "Rally speed-up", gameplay.rally_speedup))
        menu.add(Toggle("gameplay.english_enabled", col_game, top + step * 4,
                        width, "Paddle english (spin)", gameplay.english_enabled))

        # ---------------- actions (column 3, under gameplay) ----------------
        menu.add(Button("actions.reset", col_game, self._action_top, width,
                        "RESET DEFAULTS"))
        menu.add(Button("actions.back", col_game, self._action_top + 62, width,
                        "SAVE & BACK", primary=True, hotkey="ESC"))

        self.menu = menu

    # -- input ------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE,
                                                          pygame.K_BACKSPACE):
            self._leave()
            return
        action = self.menu.handle_event(event, self.ctx.bus)
        if action:
            self._on_action(action)

    def _on_action(self, action: str) -> None:
        if action == "actions.back":
            self._leave()
        elif action == "actions.reset":
            from ..core.settings import Settings as SettingsModel
            self.ctx.settings.audio = SettingsModel().audio
            self.ctx.settings.video = SettingsModel().video
            self.ctx.settings.gameplay = SettingsModel().gameplay
            self.ctx.settings.validate()
            self._build()
            self.menu.set_focus_by_action("actions.back")
            self.ctx.audio.play("ui_back")
            self._commit(persist=True)
            self._dirty_video = True
            self._dirty_quality = True
        else:
            self._commit(persist=True)

    def _leave(self) -> None:
        self.ctx.audio.play("ui_back")
        self._commit(persist=True)
        assert self.stack is not None
        self.stack.pop(transition=Transition.FADE)

    # -- continuous value sync --------------------------------------------
    def _commit(self, *, persist: bool) -> None:
        ctx = self.ctx
        settings = ctx.settings
        menu = self.menu

        def value(action: str, default):  # type: ignore[no-untyped-def]
            widget = menu.get(action)
            return widget.value if widget is not None else default

        def flag(action: str, default: bool) -> bool:
            widget = menu.get(action)
            return bool(widget.value) if widget is not None else default

        # audio
        for name in ("master", "sfx", "music"):
            widget = menu.get(f"audio.{name}")
            if isinstance(widget, Slider):
                setattr(settings.audio, name, float(widget.value))
        settings.audio.muted = flag("audio.muted", settings.audio.muted)
        settings.audio.music_enabled = flag("audio.music_enabled",
                                            settings.audio.music_enabled)

        # gameplay
        mode = value("gameplay.mode", settings.gameplay.mode)
        if isinstance(mode, GameMode):
            settings.gameplay.mode = mode
        diff = value("gameplay.difficulty", settings.gameplay.difficulty)
        if isinstance(diff, Difficulty):
            settings.gameplay.difficulty = diff
        settings.gameplay.target_score = int(value("gameplay.target",
                                                   settings.gameplay.target_score))
        settings.gameplay.rally_speedup = flag("gameplay.rally_speedup",
                                               settings.gameplay.rally_speedup)
        settings.gameplay.english_enabled = flag("gameplay.english_enabled",
                                                 settings.gameplay.english_enabled)

        # video
        settings.video.fullscreen = flag("video.fullscreen",
                                         settings.video.fullscreen)
        window = value("video.window", (settings.video.window_width,
                                        settings.video.window_height))
        if isinstance(window, tuple):
            settings.video.window_width, settings.video.window_height = window
        settings.video.fps_cap = int(value("video.fps", settings.video.fps_cap))
        settings.video.vsync = flag("video.vsync", settings.video.vsync)
        settings.video.show_fps = flag("video.show_fps", settings.video.show_fps)
        settings.video.screen_shake = flag("video.screen_shake",
                                           settings.video.screen_shake)
        quality = value("video.particles", settings.video.particles)
        if isinstance(quality, ParticleQuality) and quality != settings.video.particles:
            settings.video.particles = quality
            self._dirty_quality = True
        scale = value("video.ui_scale", settings.video.ui_scale)
        settings.video.ui_scale = float(scale)

        settings.validate()
        ctx.audio.apply_volumes()

        # UI scale changes need a font refresh; video flags need a set_mode.
        if ctx.fonts.scale != settings.video.ui_scale:
            ctx.fonts.set_scale(settings.video.ui_scale)
        if self._dirty_video:
            self._dirty_video = False
            ctx.apply_video()
        if persist:
            ctx.save_settings()

    # -- frame ------------------------------------------------------------
    def update(self, dt: float) -> None:
        self._t += dt
        mouse = pygame.mouse.get_pos()
        if self.ctx.video is not None:
            mouse = self.ctx.video.to_logical(mouse)
        self.menu.update(dt, mouse)

        # Detect video-affecting widgets changing value (slider/toggle live).
        video = self.ctx.settings.video
        widget = self.menu.get("video.fullscreen")
        if widget is not None and bool(widget.value) != video.fullscreen:
            self._dirty_video = True
        widget = self.menu.get("video.vsync")
        if widget is not None and bool(widget.value) != video.vsync:
            self._dirty_video = True
        widget = self.menu.get("video.window")
        if widget is not None and isinstance(widget.value, tuple) and (
                tuple(widget.value) != (video.window_width, video.window_height)):
            self._dirty_video = True

        self._commit(persist=False)

    def draw(self, surface: pygame.Surface) -> None:
        fonts = self.ctx.fonts
        t = self._t
        draw_backdrop(surface, t, seed=99, vignette=80)

        draw_title(surface, "SETTINGS", fonts, y=44, size=64, color=Color.TEXT)
        hint = fonts.render("ARROWS ADJUST  ·  ENTER TOGGLES  ·  ESC SAVES & EXITS",
                            14, Color.TEXT_DIM, bold=True)
        surface.blit(hint, (surface.get_width() // 2 - hint.get_width() // 2, 122))

        # Column separators as soft glowing rules.
        for sep_x in (440, 840):
            pygame.draw.line(surface, Color.LINE_SOFT, (sep_x, 150), (sep_x, 610))

        # Live preview panel: shows how the output is configured plus a live
        # level meter for each audio bus.
        preview = self._preview_rect
        draw_panel(surface, preview, accent=Color.ACCENT, alpha=200,
                   fonts=fonts, title="output")
        info_text = (self.ctx.video.describe() if self.ctx.video
                     else "video n/a")
        info = fonts.render(info_text, 15, Color.TEXT)
        if info.get_width() > preview.w - 40:
            info = fonts.render(info_text, 13, Color.TEXT)
        surface.blit(info, (preview.x + 20, preview.y + 40))
        scale_text = fonts.render(
            f"UI SCALE {self.ctx.settings.video.ui_scale * 100:.0f}%  ·  "
            f"PARTICLES {self.ctx.settings.video.particles.value.upper()}",
            13, Color.TEXT_DIM)
        surface.blit(scale_text, (preview.x + 20, preview.y + 62))

        self.menu.draw(surface, fonts)
        self._draw_meters(surface, preview)

    def _draw_meters(self, surface: pygame.Surface,
                     panel: pygame.Rect) -> None:
        """Three thin level bars for master / sfx / music."""
        audio = self.ctx.settings.audio
        bar_x = panel.x + 20
        bar_y = panel.bottom - 34
        bar_w = panel.w - 40
        buses = (
            (0.0 if audio.muted else audio.master, Color.ACCENT),
            (0.0 if audio.muted else audio.sfx, Color.P1),
            (0.0 if audio.muted or not audio.music_enabled else audio.music,
             Color.P2),
        )
        for i, (level, color) in enumerate(buses):
            row_y = bar_y + i * 9
            back = pygame.Rect(bar_x, row_y, bar_w, 5)
            pygame.draw.rect(surface, Color.PANEL_LIGHT, back, border_radius=3)
            fill = pygame.Rect(bar_x, row_y, int(bar_w * level), 5)
            if fill.w > 0:
                pygame.draw.rect(surface, color, fill, border_radius=3)
