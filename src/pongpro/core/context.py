"""Shared application context passed to every scene.

Keeps scenes free of "service locator" globals while avoiding a circular
import of the application module: :class:`AppContext` only holds references to
services, and the handful of app-owned objects are attached at start-up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from ..audio.manager import AudioManager
from ..core.events import EventBus
from ..core.rng import Rng
from ..core.settings import Settings
from ..rendering.fonts import FontManager
from ..storage import Storage

if TYPE_CHECKING:  # pragma: no cover
    from ..rendering.video import VideoSystem


@dataclass
class AppContext:
    """Everything a scene is allowed to reach for."""

    settings: Settings
    storage: Storage
    audio: AudioManager
    bus: EventBus
    fonts: FontManager
    rng: Rng
    seed: int = 0
    #: Populated by the application after construction.
    video: "VideoSystem | None" = None
    stack: Any = None  # SceneStack (typed loosely to dodge an import cycle)
    request_quit: Callable[[], None] = lambda: None
    apply_video: Callable[[], None] = lambda: None
    save_settings: Callable[[], None] = lambda: None
    #: Rolling telemetry for the HUD.
    fps: float = 0.0
    frame_index: int = 0
    elapsed: float = 0.0
    #: Interpolation factor between the previous and current physics state,
    #: written by the application immediately before every draw call.
    render_alpha: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)
