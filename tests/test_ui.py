"""UI toolkit: focus navigation, value adjustment, mouse activation."""

from __future__ import annotations

import unittest

import pygame

from pongpro.core.events import EventBus, EventType
from pongpro.rendering.fonts import FontManager
from pongpro.rendering.ui import (
    Button,
    MenuList,
    OptionCycle,
    Slider,
    StaticText,
    Toggle,
)

pygame.init()
pygame.font.init()


def key(event_key: int, mod: int = 0) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=event_key, mod=mod)


def click(pos: tuple[int, int]) -> pygame.event.Event:
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)


class MenuListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.menu = MenuList(bus=EventBus())
        self.menu.add(Button("one", 10, 10, 200, "One"))
        self.menu.add(Button("two", 10, 70, 200, "Two"))
        self.menu.add(Button("three", 10, 130, 200, "Three"))

    def test_focus_starts_on_first_focusable(self) -> None:
        assert self.menu.current is not None
        self.assertEqual(self.menu.current.action, "one")

    def test_down_moves_focus_and_wraps(self) -> None:
        self.menu.handle_event(key(pygame.K_DOWN))
        self.assertEqual(self.menu.current.action, "two")  # type: ignore[union-attr]
        self.menu.handle_event(key(pygame.K_DOWN))
        self.menu.handle_event(key(pygame.K_DOWN))
        self.assertEqual(self.menu.current.action, "one")  # wrapped

    def test_up_wraps_backwards(self) -> None:
        self.menu.handle_event(key(pygame.K_UP))
        self.assertEqual(self.menu.current.action, "three")  # type: ignore[union-attr]

    def test_enter_activates_focused_widget(self) -> None:
        self.menu.handle_event(key(pygame.K_DOWN))
        action = self.menu.handle_event(key(pygame.K_RETURN))
        self.assertEqual(action, "two")

    def test_disabled_widgets_are_skipped(self) -> None:
        self.menu.get("two").enabled = False  # type: ignore[union-attr]
        self.menu.handle_event(key(pygame.K_DOWN))
        self.assertEqual(self.menu.current.action, "three")  # type: ignore[union-attr]

    def test_static_text_is_not_focusable(self) -> None:
        self.menu.add(StaticText(10, 190, 200, "caption"))
        self.menu.handle_event(key(pygame.K_DOWN))
        self.menu.handle_event(key(pygame.K_DOWN))
        self.assertEqual(self.menu.current.action, "three")  # type: ignore[union-attr]

    def test_mouse_click_activates_button(self) -> None:
        button: Button = self.menu.get("two")  # type: ignore[assignment,union-attr]
        action = self.menu.handle_event(click(button.rect.center))
        self.assertEqual(action, "two")

    def test_mouse_motion_changes_focus(self) -> None:
        button: Button = self.menu.get("three")  # type: ignore[assignment,union-attr]
        self.menu.handle_event(
            pygame.event.Event(pygame.MOUSEMOTION, pos=button.rect.center, rel=(0, 0)))
        self.assertEqual(self.menu.current.action, "three")  # type: ignore[union-attr]

    def test_right_click_reports_back(self) -> None:
        action = self.menu.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(5, 5)))
        self.assertEqual(action, "__back__")

    def test_set_focus_by_action(self) -> None:
        self.menu.set_focus_by_action("three")
        self.assertEqual(self.menu.current.action, "three")  # type: ignore[union-attr]

    def test_ui_events_are_emitted(self) -> None:
        seen: list[str] = []
        bus = EventBus()
        bus.subscribe(EventType.UI_MOVE, lambda e: seen.append("move"))
        bus.subscribe(EventType.UI_SELECT, lambda e: seen.append("select"))
        menu = MenuList(bus=bus)
        menu.add(Button("a", 0, 0, 100, "A"))
        menu.handle_event(key(pygame.K_DOWN))
        menu.handle_event(key(pygame.K_RETURN))
        self.assertIn("move", seen)
        self.assertIn("select", seen)


class SliderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.menu = MenuList(bus=EventBus())
        self.slider: Slider = self.menu.add(  # type: ignore[assignment]
            Slider("vol", 0, 0, 460, "Volume", 0.0, 1.0, 0.5, step=0.05))

    def test_arrow_keys_adjust_value(self) -> None:
        action = self.menu.handle_event(key(pygame.K_RIGHT))
        self.assertEqual(action, "vol")
        self.assertAlmostEqual(self.slider.value, 0.55)
        self.menu.handle_event(key(pygame.K_LEFT))
        self.assertAlmostEqual(self.slider.value, 0.5)

    def test_adjust_is_clamped(self) -> None:
        for _ in range(50):
            self.menu.handle_event(key(pygame.K_LEFT))
        self.assertEqual(self.slider.value, 0.0)
        for _ in range(50):
            self.menu.handle_event(key(pygame.K_RIGHT))
        self.assertEqual(self.slider.value, 1.0)

    def test_click_on_track_starts_drag_without_action(self) -> None:
        track_x = self.slider.rect.x + 300
        action = self.menu.handle_event(click((track_x, self.slider.rect.centery)))
        self.assertIsNone(action)
        self.assertLess(self.slider.value, 0.9)
        self.assertTrue(self.slider.dragging)

    def test_drag_updates_value(self) -> None:
        self.menu.handle_event(click((self.slider.rect.x + 300,
                                      self.slider.rect.centery)))
        self.menu.handle_event(
            pygame.event.Event(pygame.MOUSEMOTION,
                               pos=(self.slider.rect.right, self.slider.rect.centery),
                               rel=(40, 0)))
        self.assertGreater(self.slider.value, 0.8)

    def test_release_ends_drag(self) -> None:
        self.menu.handle_event(click((self.slider.rect.x + 300,
                                      self.slider.rect.centery)))
        self.menu.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)))
        self.assertFalse(self.slider.dragging)

    def test_fraction_matches_value(self) -> None:
        self.slider.value = 0.25
        self.assertAlmostEqual(self.slider.fraction, 0.25)


class ToggleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.menu = MenuList(bus=EventBus())
        self.toggle: Toggle = self.menu.add(  # type: ignore[assignment]
            Toggle("shake", 0, 0, 460, "Shake", False))

    def test_enter_toggles(self) -> None:
        action = self.menu.handle_event(key(pygame.K_RETURN))
        self.assertEqual(action, "shake")
        self.assertTrue(self.toggle.value)
        self.menu.handle_event(key(pygame.K_RETURN))
        self.assertFalse(self.toggle.value)

    def test_click_switch_track_toggles(self) -> None:
        track = pygame.Rect(self.toggle.rect.right - 74, self.toggle.rect.y + 9,
                            64, 28)
        action = self.menu.handle_event(click(track.center))
        self.assertEqual(action, "shake")
        self.assertTrue(self.toggle.value)


class OptionCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.menu = MenuList(bus=EventBus())
        self.options: OptionCycle = self.menu.add(  # type: ignore[assignment]
            OptionCycle("level", 0, 0, 460, "Level",
                        [(0, "EASY"), (1, "NORMAL"), (2, "HARD")], 0))

    def test_arrow_keys_cycle(self) -> None:
        self.menu.handle_event(key(pygame.K_RIGHT))
        self.assertEqual(self.options.value, 1)
        self.menu.handle_event(key(pygame.K_LEFT))
        self.assertEqual(self.options.value, 0)

    def test_wraps_around(self) -> None:
        self.menu.handle_event(key(pygame.K_LEFT))
        self.assertEqual(self.options.value, 2)
        self.menu.handle_event(key(pygame.K_RIGHT))
        self.assertEqual(self.options.value, 0)

    def test_click_cycles_forward(self) -> None:
        zone_center = (self.options.rect.right - 30, self.options.rect.centery)
        self.menu.handle_event(click(zone_center))
        self.assertEqual(self.options.value, 1)


class FontManagerTests(unittest.TestCase):
    def test_render_and_cache(self) -> None:
        fonts = FontManager(scale=1.0, cache_size=8)
        first = fonts.render("PONG", 24, (255, 255, 255))
        second = fonts.render("PONG", 24, (255, 255, 255))
        self.assertIs(first, second)

    def test_different_sizes_are_different_surfaces(self) -> None:
        fonts = FontManager()
        small = fonts.render("PONG", 16, (255, 255, 255))
        large = fonts.render("PONG", 48, (255, 255, 255))
        self.assertGreater(large.get_width(), small.get_width())

    def test_cache_evicts_oldest(self) -> None:
        fonts = FontManager(cache_size=4)
        for i in range(10):
            fonts.render(f"text{i}", 16, (255, 255, 255))
        self.assertLessEqual(len(fonts._cache), 4)

    def test_scale_invalidation(self) -> None:
        fonts = FontManager(scale=1.0)
        before = fonts.render("PONG", 20, (255, 255, 255))
        fonts.set_scale(2.0)
        after = fonts.render("PONG", 20, (255, 255, 255))
        self.assertGreater(after.get_width(), before.get_width())

    def test_outline_output_is_larger(self) -> None:
        fonts = FontManager()
        plain = fonts.render("X", 32, (255, 255, 255))
        outlined = fonts.render("X", 32, (255, 255, 255), outline=3)
        self.assertGreaterEqual(outlined.get_width(), plain.get_width())


if __name__ == "__main__":
    unittest.main()
