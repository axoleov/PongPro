"""Core gameplay simulation: entities, physics, AI, match rules, replay.

This package must stay free of any pygame *display* dependency so the logic
can be unit-tested headlessly (``pygame.Rect``/``Vector2`` maths only).
"""

from __future__ import annotations

__all__: list[str] = []
