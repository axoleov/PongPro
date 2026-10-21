"""Retained-mode UI toolkit: buttons, sliders, toggles and option rows.

Widgets are focusable (keyboard *and* mouse), animate their focus state, and
return a *string action* on activation so scenes can switch on intent instead
of holding widget references.  :class:`MenuList` owns navigation: UP/DOWN to
move focus, LEFT/RIGHT to adjust values, ENTER/SPACE to activate, mouse hover
to focus and click to interact.

All coordinates are logical pixels; the video layer converts window events.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable

import pygame

from ..core.constants import Color
from ..core.events import EventBus, EventType
from .fonts import FontManager

WIDGET_H = 46
LABEL_W = 190  # label column on rows (slider labels are short)
VALUE_W = 210  # right-hand value chip on OptionCycle rows
#: Right-hand gutter a Slider reserves for its numeric read-out.  The
#: LABEL_W + gutter sum must stay below the widget width (~470) or the track
#: rect inverts and the slider stops responding to the mouse.
TRACK_VALUE_GUTTER = 72


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class Widget:
    """Base class. Subclasses override drawing and interaction."""

    focusable = True

    def __init__(self, action: str, rect: pygame.Rect, label: str = "") -> None:
        self.action = action
        self.rect = rect
        self.label = label
        self.focused = False
        self._focus_t = 0.0
        self.hovered = False
        self.enabled = True

    # -- interaction ------------------------------------------------------
    def on_activate(self) -> str | None:
        """Called when the widget is confirmed. Returns an action id."""
        return self.action if self.enabled else None

    def on_adjust(self, delta: int) -> bool:
        """LEFT/RIGHT handling. Return True when the value changed."""
        return False

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Consume a mouse event targeted at this widget."""
        return False

    # -- frame ------------------------------------------------------------
    def update(self, dt: float, mouse_pos: tuple[int, int]) -> None:
        target = 1.0 if (self.focused or self.hovered) else 0.0
        speed = 10.0 if target > self._focus_t else 14.0
        self._focus_t = max(0.0, min(1.0, self._focus_t + math.copysign(
            speed * dt, target - self._focus_t)))
        self.hovered = self.rect.collidepoint(mouse_pos)

    @property
    def focus_t(self) -> float:
        return self._focus_t

    # -- drawing ----------------------------------------------------------
    def draw(self, surface: pygame.Surface, fonts: FontManager) -> None:
        raise NotImplementedError


class Button(Widget):
    """Standard menu entry with a filled hover glow."""

    def __init__(self, action: str, x: int, y: int, width: int,
                 label: str, *, primary: bool = False, hotkey: str = "") -> None:
        super().__init__(action, pygame.Rect(x, y, width, WIDGET_H), label)
        self.primary = primary
        self.hotkey = hotkey  # e.g. "F1" shown right-aligned

    def draw(self, surface: pygame.Surface, fonts: FontManager) -> None:
        t = self._focus_t
        base = Color.PANEL_LIGHT if not self.primary else Color.PANEL
        fill = Color.blend(base, Color.P1 if not self.primary else Color.PANEL_LIGHT,
                           t * 0.55)
        rect = self.rect.inflate(int(6 * t), 0)
        pygame.draw.rect(surface, fill, rect, border_radius=8)
        accent = Color.ACCENT if self.primary else Color.P1
        pygame.draw.rect(surface, Color.blend(Color.LINE_SOFT, accent, t),
                         rect, width=1, border_radius=8)
        if t > 0.01:
            glow = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            glow.fill((*accent, int(36 * t)))
            surface.blit(glow, rect.topleft)

        text_color = Color.blend(Color.TEXT_DIM, Color.TEXT, max(t, 0.55))
        label = fonts.render(self.label, 22, text_color, bold=self.primary,
                             shadow=True)
        surface.blit(label, (rect.x + 18, rect.centery - label.get_height() // 2))
        if self.hotkey:
            key = fonts.render(self.hotkey, 14, Color.TEXT_DIM)
            surface.blit(key, (rect.right - key.get_width() - 14,
                               rect.centery - key.get_height() // 2))


class Slider(Widget):
    """Horizontal value slider with drag support and a formatted read-out."""

    def __init__(self, action: str, x: int, y: int, width: int,
                 label: str, minimum: float, maximum: float, value: float,
                 *, step: float = 1.0,
                 formatter: Callable[[float], str] | None = None) -> None:
        super().__init__(action, pygame.Rect(x, y, width, WIDGET_H), label)
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.value = value
        self.formatter = formatter or (lambda v: f"{v:.0f}")
        self._dragging = False

    @property
    def dragging(self) -> bool:
        return self._dragging

    @property
    def fraction(self) -> float:
        span = (self.maximum - self.minimum) or 1.0
        return max(0.0, min(1.0, (self.value - self.minimum) / span))

    def _apply_fraction(self, fraction: float) -> bool:
        raw = self.minimum + fraction * (self.maximum - self.minimum)
        if self.step > 0:
            raw = round(raw / self.step) * self.step
        raw = self._snap(raw)
        if abs(raw - self.value) < 1e-9:
            return False
        self.value = raw
        return True

    def _snap(self, raw: float) -> float:
        """Clamp to range and eliminate float dust at the two bounds."""
        raw = max(self.minimum, min(self.maximum, raw))
        if abs(raw - self.minimum) < 1e-9:
            return self.minimum
        if abs(raw - self.maximum) < 1e-9:
            return self.maximum
        return raw

    def on_adjust(self, delta: int) -> bool:
        span = (self.maximum - self.minimum)
        increment = (span / 20.0) if self.step <= 0 else self.step
        current = self._snap(self.value)  # heal any float drift first
        new_value = self._snap(current + delta * increment)
        self.value = new_value
        return abs(new_value - current) >= 1e-9

    def handle_event(self, event: pygame.event.Event) -> bool:
        track = pygame.Rect(self.rect.x + LABEL_W, self.rect.centery - 9,
                            self.rect.w - LABEL_W - TRACK_VALUE_GUTTER, 18)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if track.inflate(8, 26).collidepoint(event.pos):
                self._dragging = True
                self._apply_fraction((event.pos[0] - track.x) / track.w)
                return True
        elif event.type == pygame.MOUSEMOTION and self._dragging:
            self._apply_fraction((event.pos[0] - track.x) / track.w)
            return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._dragging:
                self._dragging = False
                return True
        return False

    def update(self, dt: float, mouse_pos: tuple[int, int]) -> None:
        super().update(dt, mouse_pos)
        if self._dragging and not pygame.mouse.get_pressed()[0]:
            self._dragging = False

    def draw(self, surface: pygame.Surface, fonts: FontManager) -> None:
        t = self._focus_t
        label = fonts.render(self.label, 20,
                             Color.blend(Color.TEXT_DIM, Color.TEXT, max(t, 0.5)))
        surface.blit(label, (self.rect.x, self.rect.centery - label.get_height() // 2))

        track_x = self.rect.x + LABEL_W
        track_y = self.rect.centery - 3
        track_w = self.rect.w - LABEL_W - TRACK_VALUE_GUTTER
        pygame.draw.rect(surface, Color.PANEL_LIGHT,
                         (track_x, track_y, track_w, 6), border_radius=3)
        fill_w = int(track_w * self.fraction)
        pygame.draw.rect(surface, Color.blend(Color.LINE, Color.ACCENT, t),
                         (track_x, track_y, fill_w, 6), border_radius=3)
        knob_x = track_x + fill_w
        knob_r = int(7 + 3 * t)
        pygame.draw.circle(surface, Color.BG, (knob_x, track_y + 3), knob_r + 2)
        pygame.draw.circle(surface, Color.blend(Color.TEXT_DIM, Color.ACCENT, t),
                           (knob_x, track_y + 3), knob_r)

        value_text = fonts.render(self.formatter(self.value), 18,
                                  Color.blend(Color.TEXT_DIM, Color.TEXT, t),
                                  bold=True)
        surface.blit(value_text, (self.rect.right - value_text.get_width(),
                                  self.rect.centery - value_text.get_height() // 2))


class Toggle(Widget):
    """On/off switch (used for video & gameplay flags)."""

    def __init__(self, action: str, x: int, y: int, width: int,
                 label: str, value: bool) -> None:
        super().__init__(action, pygame.Rect(x, y, width, WIDGET_H), label)
        self.value = value

    def on_activate(self) -> str | None:
        if not self.enabled:
            return None
        self.value = not self.value
        return self.action

    def on_adjust(self, delta: int) -> bool:
        new = bool(delta > 0)
        if new == self.value:
            return False
        self.value = new
        return True

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            track = pygame.Rect(self.rect.right - 74, self.rect.y + 9, 64, 28)
            if track.collidepoint(event.pos):
                self.value = not self.value
                return True
        return False

    def draw(self, surface: pygame.Surface, fonts: FontManager) -> None:
        t = self._focus_t
        label = fonts.render(self.label, 20,
                             Color.blend(Color.TEXT_DIM, Color.TEXT, max(t, 0.5)))
        surface.blit(label, (self.rect.x, self.rect.centery - label.get_height() // 2))

        track = pygame.Rect(self.rect.right - 64, self.rect.centery - 14, 56, 28)
        on = self.value
        pygame.draw.rect(surface,
                         Color.blend(Color.PANEL, Color.ACCENT if on else Color.WARN,
                                     0.45 if on else 0.20),
                         track, border_radius=14)
        knob_x = track.right - 14 if on else track.x + 14
        pygame.draw.circle(surface, Color.TEXT if on else Color.TEXT_DIM,
                           (knob_x, track.centery), 11)
        state = fonts.render("ON" if on else "OFF", 15,
                             Color.blend(Color.TEXT_DIM, Color.TEXT, 0.75),
                             bold=True)
        surface.blit(state, (track.x - state.get_width() - 12,
                             track.centery - state.get_height() // 2))


class OptionCycle(Widget):
    """Cycles through a list of options with LEFT/RIGHT or click."""

    def __init__(self, action: str, x: int, y: int, width: int,
                 label: str, options: list[tuple[object, str]], index: int = 0) -> None:
        super().__init__(action, pygame.Rect(x, y, width, WIDGET_H), label)
        self.options = options
        self.index = max(0, min(len(options) - 1, index))

    @property
    def value(self) -> object:
        return self.options[self.index][0]

    @property
    def text(self) -> str:
        return self.options[self.index][1]

    def _cycle(self, delta: int) -> bool:
        if not self.options:
            return False
        new = (self.index + delta) % len(self.options)
        if new == self.index:
            return False
        self.index = new
        return True

    def on_activate(self) -> str | None:
        if not self.enabled:
            return None
        self._cycle(1)
        return self.action

    def on_adjust(self, delta: int) -> bool:
        return self._cycle(delta)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
            zone = pygame.Rect(self.rect.right - VALUE_W, self.rect.y,
                               VALUE_W, self.rect.h)
            if zone.collidepoint(event.pos):
                self._cycle(1 if event.button == 1 else -1)
                return True
        return False

    def draw(self, surface: pygame.Surface, fonts: FontManager) -> None:
        t = self._focus_t
        label = fonts.render(self.label, 20,
                             Color.blend(Color.TEXT_DIM, Color.TEXT, max(t, 0.5)))
        surface.blit(label, (self.rect.x, self.rect.centery - label.get_height() // 2))

        zone = pygame.Rect(self.rect.right - VALUE_W, self.rect.y + 7,
                           VALUE_W, self.rect.h - 14)
        pygame.draw.rect(surface, Color.blend(Color.PANEL_LIGHT, Color.P1, t * 0.35),
                         zone, border_radius=7)
        pygame.draw.rect(surface, Color.blend(Color.LINE_SOFT, Color.P1, t),
                         zone, width=1, border_radius=7)

        chevron = fonts.render("‹", 22, Color.blend(Color.TEXT_DIM, Color.TEXT, t),
                               bold=True)
        value = fonts.render(self.text, 18, Color.TEXT, bold=True)
        surface.blit(chevron, (zone.x + 8, zone.centery - chevron.get_height() // 2))
        surface.blit(value, (zone.centerx - value.get_width() // 2,
                             zone.centery - value.get_height() // 2))
        chevron_r = fonts.render("›", 22,
                                 Color.blend(Color.TEXT_DIM, Color.TEXT, t),
                                 bold=True)
        surface.blit(chevron_r, (zone.right - chevron_r.get_width() - 8,
                                 zone.centery - chevron_r.get_height() // 2))


class StaticText(Widget):
    """Non-interactive separator / caption that the navigator skips."""

    focusable = False

    def __init__(self, x: int, y: int, width: int, text: str,
                 size: int = 16, color: tuple[int, int, int] | None = None,
                 *, uppercase: bool = True) -> None:
        super().__init__("", pygame.Rect(x, y, width, 28), text)
        self.text = text
        self.size = size
        self.color = color or Color.TEXT_DIM
        self.uppercase = uppercase

    def draw(self, surface: pygame.Surface, fonts: FontManager) -> None:
        text = self.text.upper() if self.uppercase else self.text
        rendered = fonts.render(text, self.size, self.color, bold=True)
        surface.blit(rendered, (self.rect.x, self.rect.y))


class MenuList:
    """Vertical focus navigator owning a group of widgets."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self.widgets: list[Widget] = []
        self.focus = 0
        self.bus = bus
        self._sounds_enabled = True

    # -- construction -----------------------------------------------------
    def add(self, widget: Widget) -> Widget:
        self.widgets.append(widget)
        return widget

    def extend(self, widgets: Iterable[Widget]) -> None:
        for widget in widgets:
            self.add(widget)

    def get(self, action: str) -> Widget | None:
        for widget in self.widgets:
            if widget.action == action:
                return widget
        return None

    def typed(self, action: str, cls: type) -> object | None:
        widget = self.get(action)
        return widget if isinstance(widget, cls) else None

    @property
    def current(self) -> Widget | None:
        focusable = self._focusable()
        if not focusable:
            return None
        self.focus = max(0, min(self.focus, len(focusable) - 1))
        return focusable[self.focus]

    def _focusable(self) -> list[Widget]:
        return [w for w in self.widgets if w.focusable and w.enabled]

    def set_focus_by_action(self, action: str) -> None:
        focusable = self._focusable()
        for index, widget in enumerate(focusable):
            if widget.action == action:
                self.focus = index
                return

    def reset_focus(self) -> None:
        self.focus = 0

    # -- input ------------------------------------------------------------
    def _move_focus(self, delta: int, bus: EventBus | None) -> None:
        focusable = self._focusable()
        if not focusable:
            return
        self.focus = (self.focus + delta) % len(focusable)
        if bus:
            bus.emit(EventType.UI_MOVE, {"index": self.focus})

    def handle_event(self, event: pygame.event.Event,
                     bus: EventBus | None = None) -> str | None:
        """Process an event; returns the action id of an activation, if any."""
        bus = bus or self.bus

        # A slider mid-drag must receive every motion/release even when the
        # cursor is over another widget.
        if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP,
                          pygame.MOUSEBUTTONDOWN):
            for widget in self.widgets:
                if isinstance(widget, Slider) and widget.dragging:
                    widget.handle_event(event)
                    if event.type != pygame.MOUSEBUTTONDOWN:
                        return None
                    break

        if event.type == pygame.KEYDOWN:
            mod = getattr(event, "mod", 0)
            if event.key in (pygame.K_UP, pygame.K_TAB) and not (
                    mod & pygame.KMOD_SHIFT):
                self._move_focus(-1, bus)
                return None
            if event.key in (pygame.K_DOWN, pygame.K_TAB):
                self._move_focus(1, bus)
                return None
            current = self.current
            if current is None:
                return None
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                delta = 1 if event.key == pygame.K_RIGHT else -1
                if current.on_adjust(delta):
                    if bus:
                        bus.emit(EventType.UI_MOVE, {"adjust": True})
                    return current.action
                if bus:
                    bus.emit(EventType.UI_BACK, {"blocked": True})
                return None
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                action = current.on_activate()
                if action and bus:
                    bus.emit(EventType.UI_SELECT, {"action": action})
                return action
            return None

        # Mouse routing: hover changes focus, clicks hit the widget.
        if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN,
                          pygame.MOUSEBUTTONUP):
            if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
                if event.button == 3:
                    return "__back__"
                for index, widget in enumerate(self._focusable()):
                    if not widget.rect.inflate(8, 8).collidepoint(event.pos):
                        continue
                    self.focus = index
                    if not widget.rect.collidepoint(event.pos):
                        return None
                    consumed = bool(widget.handle_event(event))
                    if consumed:
                        # Value changed in place (toggle/option/slider grab).
                        if not isinstance(widget, Slider):
                            if bus:
                                bus.emit(EventType.UI_SELECT,
                                         {"action": widget.action})
                            return widget.action
                        return None
                    if not isinstance(widget, Slider):
                        action = widget.on_activate()
                        if action and bus:
                            bus.emit(EventType.UI_SELECT, {"action": action})
                        return action
                    return None
                return None

            # Motion / release: forward to everything (hover + drag tracking).
            focusable = self._focusable()
            for index, widget in enumerate(focusable):
                if widget.rect.inflate(8, 8).collidepoint(event.pos):
                    if event.type == pygame.MOUSEMOTION and index != self.focus:
                        self.focus = index
                        if bus:
                            bus.emit(EventType.UI_MOVE, {"mouse": True})
                    widget.handle_event(event)
                    return None
            for widget in self.widgets:
                widget.handle_event(event)
            return None
        return None

    # -- frame ------------------------------------------------------------
    def update(self, dt: float, mouse_pos: tuple[int, int]) -> None:
        focusable = self._focusable()
        self.focus = max(0, min(self.focus, len(focusable) - 1)) if focusable else 0
        current = focusable[self.focus] if focusable else None
        for widget in self.widgets:
            widget.focused = widget is current
            widget.update(dt, mouse_pos)

    def draw(self, surface: pygame.Surface, fonts: FontManager) -> None:
        for widget in self.widgets:
            widget.draw(surface, fonts)
