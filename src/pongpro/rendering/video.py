"""Video output: logical-resolution rendering scaled into a real window.

Architecture
------------
Scenes always draw onto a fixed **logical surface** (1280x720).  The display
surface is the actual window/desktop surface, which may be any size (the
window is resizable, fullscreen uses the native desktop resolution).  Each
frame the logical surface is scaled into the largest 16:9 letterbox rect, so:

* gameplay coordinates never change with window size (design stays stable),
* any aspect mismatch shows safe black bars instead of distortion,
* mouse coordinates convert exactly (``to_logical`` / ``convert_event``).

VSync is requested via ``set_mode(..., vsync=1)``; pygame accepts it on the
plain (non-SCALED) path, and if a host/driver rejects it we simply retry
without it rather than crashing.
"""

from __future__ import annotations

import logging

import pygame

from ..core.constants import LOGICAL_H, LOGICAL_W

log = logging.getLogger(__name__)


class VideoSystem:
    """Owns the display surface, scaling and coordinate conversion."""

    def __init__(self, settings) -> None:  # type: ignore[no-untyped-def]
        self.settings = settings
        self.logical_size = (LOGICAL_W, LOGICAL_H)
        self.using_vsync = False
        self.last_present_mode = "n/a"
        self._dst_rect = pygame.Rect(0, 0, LOGICAL_W, LOGICAL_H)
        self._scale_x = 1.0
        self._scale_y = 1.0
        self._offset = (0, 0)
        self._icon: pygame.Surface | None = None

    # -- mode management --------------------------------------------------
    def apply(self) -> pygame.Surface:
        """(Re)create the display mode from current settings."""
        video = self.settings.video
        flags = pygame.RESIZABLE
        if video.fullscreen:
            size = self._desktop_size()
            flags |= pygame.FULLSCREEN
        else:
            size = (int(video.window_width), int(video.window_height))

        self._apply_icon()
        surface = self._set_mode(size, flags, video.vsync)
        self._update_mapping(surface.get_size())
        log.info("Video mode: %dx%d %s vsync=%s driver=%s",
                 size[0], size[1],
                 "fullscreen" if video.fullscreen else "windowed",
                 self.using_vsync, pygame.display.get_driver())
        return surface

    def _apply_icon(self) -> None:
        """Install the window icon, before ``set_mode``.

        Some window managers only honour a call made prior to the first
        ``set_mode``, and recreating the display (fullscreen toggles, a UI
        scale change) can drop it, so this runs on every reconfiguration.
        The surface is rendered once and cached - drawing it is the expensive
        part, and the mark never changes.
        """
        if self._icon is None:
            try:
                from .icon import window_icon

                self._icon = window_icon()
            except Exception:  # noqa: BLE001 - an icon is never worth a crash
                log.exception("window icon could not be rendered")
                return
        try:
            pygame.display.set_icon(self._icon)
        except pygame.error:  # pragma: no cover - driver dependent
            log.warning("set_icon rejected by the video driver")

    def _set_mode(self, size: tuple[int, int], flags: int,
                  want_vsync: bool) -> pygame.Surface:
        if want_vsync:
            try:
                surface = pygame.display.set_mode(size, flags, vsync=1)
                self.using_vsync = True
                return surface
            except (pygame.error, ValueError) as exc:
                log.warning("vsync unavailable (%s); retrying without", exc)
        try:
            surface = pygame.display.set_mode(size, flags)
        except pygame.error as exc:  # pragma: no cover - catastrophic host issue
            log.error("set_mode(%s, %s) failed: %s", size, flags, exc)
            surface = pygame.display.set_mode((LOGICAL_W, LOGICAL_H))
        self.using_vsync = False
        return surface

    @staticmethod
    def _desktop_size() -> tuple[int, int]:
        try:
            sizes = pygame.display.get_desktop_sizes()
            if sizes:
                return (int(sizes[0][0]), int(sizes[0][1]))
        except pygame.error:  # pragma: no cover
            pass
        return (LOGICAL_W, LOGICAL_H)

    def toggle_fullscreen(self) -> None:
        self.settings.video.fullscreen = not self.settings.video.fullscreen
        self.apply()

    # -- geometry ---------------------------------------------------------
    @staticmethod
    def _letterbox(window: tuple[int, int]) -> pygame.Rect:
        """Largest centred 16:9 rect that fits inside ``window``."""
        ww, wh = window
        if ww <= 0 or wh <= 0:
            return pygame.Rect(0, 0, LOGICAL_W, LOGICAL_H)
        target = LOGICAL_W / LOGICAL_H
        if ww / wh > target:
            height = wh
            width = int(round(wh * target))
        else:
            width = ww
            height = int(round(ww / target))
        width = max(1, width)
        height = max(1, height)
        return pygame.Rect((ww - width) // 2, (wh - height) // 2, width, height)

    def _update_mapping(self, window: tuple[int, int]) -> None:
        self._dst_rect = self._letterbox(window)
        self._scale_x = LOGICAL_W / self._dst_rect.w
        self._scale_y = LOGICAL_H / self._dst_rect.h
        self._offset = (self._dst_rect.x, self._dst_rect.y)

    @property
    def dst_rect(self) -> pygame.Rect:
        return self._dst_rect

    @property
    def window_size(self) -> tuple[int, int]:
        surface = pygame.display.get_surface()
        return surface.get_size() if surface else (LOGICAL_W, LOGICAL_H)

    # -- coordinate conversion -------------------------------------------
    def to_logical(self, pos: tuple[int, int]) -> tuple[int, int]:
        """Window pixel -> logical pixel (clamped into the letterbox)."""
        x = (pos[0] - self._dst_rect.x) * self._scale_x
        y = (pos[1] - self._dst_rect.y) * self._scale_y
        if x < 0:
            x = 0.0
        elif x > LOGICAL_W - 1:
            x = float(LOGICAL_W - 1)
        if y < 0:
            y = 0.0
        elif y > LOGICAL_H - 1:
            y = float(LOGICAL_H - 1)
        return (int(x), int(y))

    def convert_event(self, event: pygame.event.Event) -> pygame.event.Event:
        """Rewrite mouse ``pos``/``rel`` in-place so scenes see logical units."""
        if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN,
                          pygame.MOUSEBUTTONUP):
            if hasattr(event, "pos"):
                event.pos = self.to_logical(event.pos)
            if event.type == pygame.MOUSEMOTION and hasattr(event, "rel"):
                event.rel = (
                    int(round(event.rel[0] * self._scale_x)),
                    int(round(event.rel[1] * self._scale_y)),
                )
        elif event.type == pygame.WINDOWRESIZED or event.type == pygame.VIDEORESIZE:
            pass  # handled next frame via display surface size
        return event

    # -- present ----------------------------------------------------------
    def present(self, logical: pygame.Surface) -> None:
        """Scale the logical frame into the window with letterboxing."""
        display = pygame.display.get_surface()
        if display is None:  # pragma: no cover
            return
        window = display.get_size()
        target = self._letterbox(window)
        if target != self._dst_rect:
            self._update_mapping(window)

        display.fill((0, 0, 0))
        if window == self.logical_size:
            display.blit(logical, (0, 0))
        else:
            pygame.transform.scale(logical, self._dst_rect.size,
                                   dest_surface=display.subsurface(self._dst_rect))
        self.last_present_mode = "1:1" if window == self.logical_size else "scaled"

    def describe(self) -> str:
        window = self.window_size
        mode = "FULLSCREEN" if self.settings.video.fullscreen else "WINDOW"
        return (f"{mode} {window[0]}x{window[1]} "
                f"(render {LOGICAL_W}x{LOGICAL_H}) "
                f"vsync={'on' if self.using_vsync else 'off'}")
