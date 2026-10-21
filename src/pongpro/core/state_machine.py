"""Stack-based scene (screen) state machine.

Scenes form a stack: the menu pushes a gameplay scene, gameplay pushes a pause
overlay on top of it.  Only the top scene receives ``update``/``handle_event``
when it is opaque; drawing walks down until an opaque scene, which lets an
overlay (pause, modal dialog) render the frozen screen underneath.

Transitions are animated by a small fade controller owned by the machine, so
individual scenes never duplicate tween logic.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

import pygame

log = logging.getLogger(__name__)


class Scene(ABC):
    """Base class for every screen in the game.

    Lifecycle:  ``on_enter`` -> (update/draw/handle_event)* -> ``on_exit``.
    When a scene above this one is popped, ``on_resume`` fires.
    """

    #: When False, scenes below still receive ``draw`` (used by overlays).
    opaque: bool = True
    #: When False, scenes below keep receiving input (never true for now,
    #: kept as a hook for non-blocking HUD overlays).
    exclusive_input: bool = True

    def __init__(self) -> None:
        self.stack: "SceneStack | None" = None
        #: Shared application context; assigned by the stack before on_enter.
        self.ctx: Any = None

    # -- lifecycle hooks --------------------------------------------------
    def on_enter(self, **kwargs: Any) -> None:
        """Called once when the scene becomes the top of the stack."""

    def on_resume(self) -> None:
        """Called when the scene above is removed and this one regains control."""

    def on_exit(self) -> None:
        """Called when the scene is removed from the stack."""

    def on_cover(self) -> None:
        """Called when another scene is pushed on top of this one."""

    # -- per-frame --------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        """React to a pygame event (only the top scene when exclusive)."""

    @abstractmethod
    def update(self, dt: float) -> None:
        """Advance simulation by a fixed ``dt`` seconds."""

    @abstractmethod
    def draw(self, surface: pygame.Surface) -> None:
        """Render onto the logical surface."""


class Transition(str, Enum):
    NONE = "none"
    FADE = "fade"
    CUT = "cut"


class SceneStack:
    """Owns the scene stack plus fade transitions between screens."""

    def __init__(self, surface_size: tuple[int, int], ctx: Any = None) -> None:
        self._stack: list[Scene] = []
        self.size = surface_size
        #: Shared application context injected into every pushed scene.
        self.ctx = ctx
        # transition state
        self._fade = 0.0  # 0.0 == fully visible, 1.0 == fully black
        self._fade_dir = 0  # -1 fading in, +1 fading out
        self._fade_speed = 4.0
        self._pending: tuple[str, Scene | None, dict[str, Any]] | None = None
        self._fade_surface = pygame.Surface(surface_size)

    # -- introspection ----------------------------------------------------
    @property
    def current(self) -> Scene | None:
        return self._stack[-1] if self._stack else None

    @property
    def depth(self) -> int:
        return len(self._stack)

    @property
    def transitioning(self) -> bool:
        return self._fade_dir != 0 or self._pending is not None

    def find(self, scene_type: type[Scene]) -> Scene | None:
        for scene in reversed(self._stack):
            if isinstance(scene, scene_type):
                return scene
        return None

    # -- mutations --------------------------------------------------------
    def push(self, scene: Scene, transition: Transition = Transition.FADE,
             **kwargs: Any) -> None:
        self._queue("push", scene, transition, kwargs)

    def replace(self, scene: Scene, transition: Transition = Transition.FADE,
                **kwargs: Any) -> None:
        self._queue("replace", scene, transition, kwargs)

    def pop(self, transition: Transition = Transition.FADE) -> None:
        self._queue("pop", None, transition, {})

    def pop_to(self, scene_type: type[Scene],
               transition: Transition = Transition.FADE) -> None:
        """Pop every scene above the nearest ``scene_type`` (queued, faded)."""
        self._queue("pop_to", None, transition, {"scene_type": scene_type})

    def replace_top(self, count: int, scene: Scene,
                    transition: Transition = Transition.FADE,
                    **kwargs: Any) -> None:
        """Pop the top ``count`` scenes and push ``scene`` as one transition.

        Used by restart flows: [menu, gameplay, pause] + replace_top(2, new
        gameplay) rebuilds the match without stacking duplicates.
        """
        kwargs["_count"] = max(1, int(count))
        self._queue("replace_top", scene, transition, kwargs)

    def clear(self, transition: Transition = Transition.CUT) -> None:
        while self._stack:
            scene = self._stack.pop()
            scene.on_exit()
            scene.stack = None
        self._queue("none", None, transition, {})

    def _queue(self, action: str, scene: Scene | None, transition: Transition,
               kwargs: dict[str, Any]) -> None:
        if transition in (Transition.NONE, Transition.CUT):
            self._apply(action, scene, kwargs)
            return
        # Animated: fade to black first, swap scenes at full black, fade back.
        # A newer request simply replaces a pending one (latest intent wins).
        self._pending = (action, scene, kwargs)
        if self._fade_dir != 1:
            self._fade_dir = 1

    def _apply(self, action: str, scene: Scene | None, kwargs: dict[str, Any]) -> None:
        if action == "push" and scene is not None:
            covering = self._stack[-1] if self._stack else None
            if covering is not None:
                covering.on_cover()
            scene.stack = self
            scene.ctx = self.ctx
            self._stack.append(scene)
            scene.on_enter(**kwargs)
            log.debug("push %s (depth=%d)", type(scene).__name__, len(self._stack))
        elif action == "replace" and scene is not None:
            if self._stack:
                old = self._stack.pop()
                old.on_exit()
                old.stack = None
            scene.stack = self
            scene.ctx = self.ctx
            self._stack.append(scene)
            scene.on_enter(**kwargs)
            log.debug("replace -> %s", type(scene).__name__)
        elif action == "pop":
            if self._stack:
                old = self._stack.pop()
                old.on_exit()
                old.stack = None
                log.debug("pop (depth=%d)", len(self._stack))
            if self._stack:
                self._stack[-1].on_resume()
        elif action == "pop_to":
            scene_type = kwargs.get("scene_type")
            while len(self._stack) > 1 and not isinstance(self._stack[-1],
                                                          scene_type):
                old = self._stack.pop()
                old.on_exit()
                old.stack = None
            if self._stack:
                self._stack[-1].on_resume()
            log.debug("pop_to %s (depth=%d)", scene_type, len(self._stack))
        elif action == "replace_top":
            count = int(kwargs.pop("_count", 1))
            for _ in range(max(1, count)):
                if not self._stack:
                    break
                old = self._stack.pop()
                old.on_exit()
                old.stack = None
            if scene is not None:
                scene.stack = self
                scene.ctx = self.ctx
                self._stack.append(scene)
                scene.on_enter(**kwargs)
            elif self._stack:
                self._stack[-1].on_resume()
            log.debug("replace_top(%d) -> %s (depth=%d)", count,
                      type(scene).__name__ if scene else None, len(self._stack))
        # action == "none": used purely to animate a fade

    def _begin_fade_out(self) -> None:
        self._fade_dir = 1

    def _begin_fade_in(self) -> None:
        self._fade_dir = -1

    # -- frame ------------------------------------------------------------
    def update(self, dt: float) -> None:
        # Fade animation (render-rate agnostic: called once per fixed step).
        if self._fade_dir == 1:
            self._fade = min(1.0, self._fade + self._fade_speed * dt)
            if self._fade >= 1.0 and self._pending is not None:
                action, scene, kwargs = self._pending
                self._pending = None
                self._apply(action, scene, kwargs)
                self._fade_dir = -1
            elif self._fade >= 1.0 and self._pending is None:
                self._fade_dir = 0
        elif self._fade_dir == -1:
            self._fade = max(0.0, self._fade - self._fade_speed * dt)
            if self._fade <= 0.0:
                self._fade_dir = 0

        scene = self.current
        if scene is not None:
            scene.update(dt)

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.transitioning and event.type == pygame.KEYDOWN:
            return  # swallow input during transitions
        scene = self.current
        if scene is None:
            return
        if scene.exclusive_input:
            scene.handle_event(event)
        else:
            # let the overlay see it first, then fall through
            scene.handle_event(event)
            for below in reversed(self._stack[:-1]):
                if below.exclusive_input:
                    break
                below.handle_event(event)

    def draw(self, surface: pygame.Surface) -> None:
        if not self._stack:
            surface.fill((0, 0, 0))
            return
        # Draw from the lowest opaque scene upwards so overlays composite over
        # a still-visible world.
        start = len(self._stack) - 1
        while start > 0 and not self._stack[start].opaque:
            start -= 1
        for scene in self._stack[start:]:
            scene.draw(surface)
        if self._fade > 0.0:
            self._fade_surface.set_alpha(int(255 * self._fade))
            surface.blit(self._fade_surface, (0, 0))
