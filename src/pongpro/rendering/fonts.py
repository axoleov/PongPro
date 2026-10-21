"""Font loading and glyph-surface caching.

On Windows we prefer Consolas (clean monospace, ships with the OS) and fall
back through Segoe UI / Arial, then to pygame's built-in font.  Rendered text
is memoised because the HUD re-draws the same score digits every frame.
"""

from __future__ import annotations

from collections import OrderedDict

import pygame

#: Preference order; pygame resolves a comma-separated family list itself.
FAMILIES = "consolas,segoeui,arial,tahoma"


class FontManager:
    """Scales-aware font registry with an LRU text cache."""

    def __init__(self, scale: float = 1.0, cache_size: int = 384) -> None:
        self._scale = scale
        self._fonts: dict[tuple[int, bool], pygame.font.Font] = {}
        self._cache: "OrderedDict[tuple, pygame.Surface]" = OrderedDict()
        self._cache_size = cache_size
        self.default_family = FAMILIES

    # -- scale ------------------------------------------------------------
    @property
    def scale(self) -> float:
        return self._scale

    def set_scale(self, scale: float) -> None:
        if abs(scale - self._scale) < 1e-6:
            return
        self._scale = scale
        self._fonts.clear()
        self.clear_cache()

    # -- fonts ------------------------------------------------------------
    def _resolve(self, size: int, bold: bool) -> pygame.font.Font:
        key = (size, bold)
        font = self._fonts.get(key)
        if font is None:
            try:
                font = pygame.font.SysFont(self.default_family, size, bold=bold)
            except pygame.error:  # pragma: no cover - extremely unusual
                font = pygame.font.Font(None, size)
            self._fonts[key] = font
        return font

    def font(self, size: int, *, bold: bool = False) -> pygame.font.Font:
        """Font at ``size`` *logical* pixels (adjusted by the UI scale)."""
        return self._resolve(max(8, int(round(size * self._scale))), bold)

    # -- rendering --------------------------------------------------------
    def render(
        self, text: str, size: int, color: tuple[int, int, int],
        *, bold: bool = False, shadow: bool = False,
        shadow_color: tuple[int, int, int] = (0, 0, 0),
        outline: int = 0,
        outline_color: tuple[int, int, int] = (0, 0, 0),
    ) -> pygame.Surface:
        """Render (or fetch from cache) a text surface."""
        key = (text, size, color, bold, shadow, outline)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        font = self.font(size, bold=bold)
        base = font.render(text, True, color)
        if outline > 0:
            # 8-direction outline for text over busy backgrounds.
            width, height = base.get_size()
            surface = pygame.Surface(
                (width + outline * 2, height + outline * 2), pygame.SRCALPHA
            )
            for dx in (-outline, 0, outline):
                for dy in (-outline, 0, outline):
                    if dx == 0 and dy == 0:
                        continue
                    surface.blit(base, (outline + dx, outline + dy),
                                 special_flags=pygame.BLEND_RGBA_MIN)
            surface.blit(base, (outline, outline))
            result = surface
        elif shadow:
            width, height = base.get_size()
            surface = pygame.Surface((width + 2, height + 2), pygame.SRCALPHA)
            shadow_surface = font.render(text, True, shadow_color)
            surface.blit(shadow_surface, (2, 2))
            surface.blit(base, (0, 0))
            result = surface
        else:
            result = base

        self._cache[key] = result
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return result

    def width(self, text: str, size: int, *, bold: bool = False) -> int:
        return self.font(size, bold=bold).size(text)[0]

    def clear_cache(self) -> None:
        self._cache.clear()
