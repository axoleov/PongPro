"""Application shell: start-up, the frame loop, and orderly shutdown.

Frame loop contract (see ``pongpro.core.timestep``):

1. ``pygame.time.Clock.tick(fps_cap)`` measures the frame and enforces the
   cap (vsync already blocks inside ``flip`` when enabled),
2. events are pumped and translated to logical coordinates, then offered to
   the scene stack,
3. the fixed-step accumulator decides how many simulation ticks to run,
4. the stack draws into a logical 1280x720 surface with an interpolation
   ``alpha``, and the video system scales that into the real window.

The loop also implements the usual "production" niceties: focus-loss auto
pause, F11 fullscreen toggle, crash reporting and clean save-on-exit.
"""

from __future__ import annotations

import logging
import os
import random
import time

import pygame

from . import __version__
from .audio.manager import AudioManager
from .core import logging_setup, paths
from .core.constants import FIXED_DT, LOGICAL_H, LOGICAL_W, Color
from .core.context import AppContext
from .core.events import EventBus
from .core.rng import Rng
from .core.settings import Settings
from .core.state_machine import SceneStack, Transition
from .core.timestep import FixedStepClock
from .rendering.fonts import FontManager
from .rendering.icon import window_icon
from .rendering.video import VideoSystem
from .scenes.splash import SplashScene
from .storage import Storage

log = logging.getLogger(__name__)


def _enable_dpi_awareness() -> None:  # pragma: no cover - Windows only
    """Stop Windows from bitmap-stretching the window on HiDPI displays."""
    if os.name != "nt":
        return
    try:
        import ctypes

        # Per-monitor v2, then fall back to v1 / system aware.
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
            return
        except Exception:  # noqa: BLE001
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except Exception:  # noqa: BLE001
            pass
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        log.debug("DPI awareness could not be enabled")


class Application:
    """Owns every long-lived service and the main loop."""

    def __init__(self, *, max_frames: int | None = None,
                 quiet: bool = False) -> None:
        self.max_frames = max_frames
        self.quiet = quiet
        self.running = False
        self._frame = 0

        # -- logging & crash reporting --------------------------------
        logging_setup.configure(level=logging.DEBUG if not quiet else logging.INFO,
                                console=not quiet)
        logging_setup.install_crash_hook(__version__)
        log.info("PongPro %s starting (Python %s)", __version__,
                 ".".join(map(str, __import__("sys").version_info[:3])))

        # -- persistent data ------------------------------------------
        self.storage = Storage()
        self.settings: Settings = self.storage.load_settings()
        self.settings.validate()

        # -- pygame core ----------------------------------------------
        _enable_dpi_awareness()
        pygame.init()
        if not pygame.font.get_init():  # pragma: no cover
            pygame.font.init()

        self.seed = random.SystemRandom().randrange(2**31)
        self.bus = EventBus(history=64)
        self.fonts = FontManager(self.settings.video.ui_scale)
        self.audio = AudioManager(self.settings)
        self.video = VideoSystem(self.settings)
        self.video.apply()

        # -- logical frame --------------------------------------------
        self.frame = pygame.Surface((LOGICAL_W, LOGICAL_H))

        # -- scene stack ----------------------------------------------
        self.ctx = AppContext(
            settings=self.settings,
            storage=self.storage,
            audio=self.audio,
            bus=self.bus,
            fonts=self.fonts,
            rng=Rng(self.seed),
            seed=self.seed,
            video=self.video,
            request_quit=self.stop,
            apply_video=self._apply_video,
            save_settings=self._save_settings,
        )
        self.stack = SceneStack((LOGICAL_W, LOGICAL_H), self.ctx)
        self.ctx.stack = self.stack
        self.stack.push(SplashScene(), transition=Transition.NONE)

        self.timestep = FixedStepClock()
        self.clock = pygame.time.Clock()
        pygame.display.set_caption(f"PongPro {__version__}")
        log.info("Ready: %s", self.video.describe())

    # -- context callbacks -------------------------------------------------
    def _apply_video(self) -> None:
        try:
            self.video.apply()
        except pygame.error:  # pragma: no cover
            log.exception("Video reconfiguration failed; keeping current mode")
        self._save_settings()

    def _save_settings(self) -> None:
        self.storage.save_settings(self.settings)

    # -- input ------------------------------------------------------------
    def _handle_global_event(self, event: pygame.event.Event) -> bool:
        """Events handled before scenes see them. Returns True if consumed."""
        if event.type == pygame.QUIT:
            self.stop()
            return True

        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self.video.toggle_fullscreen()
            self.settings.validate()
            self._save_settings()
            return True

        # Losing focus mid-match auto-pauses (prevents accidental deaths).
        if event.type == pygame.WINDOWFOCUSLOST or (
                event.type == pygame.ACTIVEEVENT and getattr(event, "state", 1) == 0
                and getattr(event, "gain", 1) == 0):
            from .scenes.gameplay import GameplayScene
            from .scenes.pause import PauseScene

            if (self.stack.find(GameplayScene) is not None
                    and self.stack.current.__class__ is GameplayScene):
                self.stack.push(PauseScene(
                    getattr(self.stack.current, "params", {})),
                    transition=Transition.NONE)
                log.info("Window lost focus - auto pause")
                return True
        return False

    # -- main loop --------------------------------------------------------
    def step_frame(self, frame_time: float | None = None) -> bool:
        """One full frame (events, simulation, render, present).

        Returns ``False`` when the application should stop.  Passing an
        explicit ``frame_time`` bypasses the frame limiter, which is what the
        headless smoke test uses to advance deterministically.
        """
        settings = self.settings
        frame = self.frame

        if frame_time is None:
            frame_time = self.clock.tick(settings.video.fps_cap) / 1000.0
        if frame_time <= 0.0:
            frame_time = FIXED_DT

        for event in pygame.event.get():
            if self._handle_global_event(event):
                continue
            self.stack.handle_event(self.video.convert_event(event))

        steps = self.timestep.advance(frame_time)
        for _ in range(steps):
            self.stack.update(FIXED_DT)

        self.ctx.render_alpha = self.timestep.alpha
        self.ctx.fps = self.timestep.measured_fps
        self.ctx.frame_index = self._frame
        self.ctx.elapsed += frame_time

        frame.fill(Color.BG)
        self.stack.draw(frame)
        self.video.present(frame)
        pygame.display.flip()

        self._frame += 1
        if self.max_frames is not None and self._frame >= self.max_frames:
            log.info("Frame budget reached (%d)", self.max_frames)
            self.stop()
        return self.running

    def run(self) -> int:
        self.running = True
        while self.running:
            self.step_frame()
        return self.shutdown()

    def stop(self) -> None:
        if self.running:
            log.info("Quit requested")
        self.running = False

    def shutdown(self) -> int:
        """Persist state and release every OS resource."""
        try:
            self._save_settings()
        except Exception:  # noqa: BLE001
            log.exception("Failed to save settings on exit")
        try:
            self.audio.shutdown()
        except Exception:  # noqa: BLE001
            log.exception("Audio shutdown failed")
        pygame.quit()
        log.info("Shutdown complete (%d frames, %.1fs)",
                 self._frame, self.ctx.elapsed)
        return 0
