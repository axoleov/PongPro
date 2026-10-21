"""Typed publish/subscribe event bus.

Decouples gameplay from presentation: the physics layer emits ``GOAL`` without
knowing that a banner, a sound and a screen-shake all listen for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

log = logging.getLogger(__name__)

Handler = Callable[["GameEvent"], None]


class EventType(str, Enum):
    BALL_HIT_PADDLE = "ball_hit_paddle"
    BALL_HIT_WALL = "ball_hit_wall"
    GOAL = "goal"
    SERVE = "serve"
    RALLY_END = "rally_end"
    MATCH_POINT = "match_point"
    MATCH_END = "match_end"
    PHASE_CHANGED = "phase_changed"
    SETTINGS_CHANGED = "settings_changed"
    UI_MOVE = "ui_move"
    UI_SELECT = "ui_select"
    UI_BACK = "ui_back"


@dataclass(frozen=True, slots=True)
class GameEvent:
    """Immutable message. ``payload`` carries event-specific data."""

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)


class EventBus:
    """Fan-out bus.  Subscriptions are stored per event type.

    Iteration happens over a snapshot so handlers may subscribe/unsubscribe
    during dispatch without raising ``RuntimeError``.
    """

    __slots__ = ("_subs", "_history", "_max_history")

    def __init__(self, history: int = 0) -> None:
        self._subs: dict[EventType, list[Handler]] = {}
        self._max_history = history
        self._history: list[GameEvent] = []

    def subscribe(self, event_type: EventType, handler: Handler) -> Callable[[], None]:
        """Register ``handler``; returns an unsubscribe callable."""
        self._subs.setdefault(event_type, []).append(handler)

        def _unsubscribe() -> None:
            bucket = self._subs.get(event_type)
            if bucket and handler in bucket:
                bucket.remove(handler)

        return _unsubscribe

    def emit(self, event: GameEvent | EventType, payload: dict[str, Any] | None = None) -> None:
        """Dispatch an event to every subscriber of its type."""
        if isinstance(event, EventType):
            event = GameEvent(event, payload or {})
        if self._max_history:
            self._history.append(event)
            if len(self._history) > self._max_history:
                del self._history[0]
        for handler in list(self._subs.get(event.type, ())):
            try:
                handler(event)
            except Exception:  # noqa: BLE001 - a bad listener must not kill the frame
                log.exception("Event handler failed for %s", event.type)

    def clear(self) -> None:
        self._subs.clear()
        self._history.clear()
