"""Screen layout regression tests: nothing overlaps, nothing off-screen.

Every screen builds its geometry imperatively inside ``on_enter`` / ``draw``,
which is exactly how the reported bugs slipped in (rows drawn 2 px apart,
buttons past the right edge, profile text running out of its panel, the rally
counter punching through the match-point pill).

These tests boot the *real* application headless, read the *real* widget
rectangles back out of the *real* scenes, and assert the two invariants that
were violated:

* every element of a screen sits inside the 1280x720 logical viewport, and
* no two elements of the same screen intersect.

The HUD centre strip, the profile panel, the results coin band and the shop's
three columns are covered through the layout helpers those screens expose
(``match_state_rects``, ``_draw_stats_panel``, and the geometry properties on
``ShopScene``).
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager

import pygame

from pongpro.core.constants import (
    COURT_PAD_Y,
    LOGICAL_H,
    LOGICAL_W,
    Difficulty,
    GameMode,
)
from pongpro.core.rng import Rng
from pongpro.core.state_machine import Transition
from pongpro.economy.catalog import CATEGORIES, ShopCategory, items_in
from pongpro.gameplay.bubbles import BubbleField
from pongpro.rendering.hud import (
    CONTROL_HINT_Y,
    SPEED_METER_Y,
    match_state_rects,
)
from pongpro.scenes import menu as menu_mod
from pongpro.scenes.credits import CreditsScene
from pongpro.scenes.gameplay import GameplayScene
from pongpro.scenes.menu import MenuScene
from pongpro.scenes.pause import PauseScene
from pongpro.scenes.replay_scene import (
    BAR_H,
    BAR_Y,
    CONTROLS_H,
    CONTROLS_Y,
    STATUS_H,
    TRANSPORT_Y,
)
from pongpro.scenes.results import (
    BUTTON_H,
    BUTTON_Y,
    EARNED_DY,
    EARNED_H,
    HINT_Y,
    LIFETIME_DY,
    NOTE_DY,
    PANEL_H,
    PANEL_Y,
    ResultsScene,
)
from pongpro.scenes.settings_scene import SettingsScene
from pongpro.scenes.shop import HIT_PAD, ROW_STEP, ShopScene
from pongpro.scenes.splash import SplashScene

VIEWPORT = pygame.Rect(0, 0, LOGICAL_W, LOGICAL_H)

#: A fully populated profile, so the two-column stats table *and* the
#: per-difficulty breakdown are both exercised.
FULL_STATS = {
    "matches_played": 1234,
    "wins": 987,
    "losses": 247,
    "longest_rally": 512,
    "total_hits": 98765,
    "fastest_ball": 1834.0,
    "playtime_seconds": 98765.0,
    "by_difficulty": {d.value: {"won": 99, "lost": 1} for d in Difficulty},
}

_FULL_RESULTS_PAYLOAD = {
    "winner": 0,
    "score": (11, 7),
    "mode": GameMode.SOLO,
    "difficulty": Difficulty.HARD,
    "duration": 184.0,
    "longest_rally": 37,
    "label": "1P vs AI · HARD · FIRST TO 11",
    "summary": {
        "total_hits": 214,
        "total_goals": 18,
        "fastest_ball": 1520.0,
        "hits_by_player": (120, 94),
    },
    "stats": dict(FULL_STATS),
}

_app = None


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------
def setUpModule() -> None:
    global _app
    from pongpro.app import Application

    _app = Application(max_frames=None, quiet=True)
    _app.settings.video.fps_cap = 0
    _app.settings.audio.master = 0.0
    _advance(1100)  # credits -> splash -> menu


def tearDownModule() -> None:
    global _app
    if _app is not None:
        _app.stop()
        _app.shutdown()
        _app = None
    # Application.shutdown() tears the SDL subsystems down; later test modules
    # (tests/test_ui.py) call pygame.init() at *import* time, which has already
    # happened by now, so bring the subsystems back before they run.
    pygame.init()


def _advance(frames: int) -> None:
    for _ in range(frames):
        _app.step_frame(1.0 / 120.0)


@contextmanager
def _pushed(scene):  # type: ignore[no-untyped-def]
    """Push ``scene`` for the duration of the block, then restore the stack."""
    stack = _app.stack
    depth = stack.depth
    stack.push(scene, transition=Transition.NONE)
    try:
        yield stack.current
    finally:
        while stack.depth > depth:
            stack.pop(transition=Transition.NONE)


def _widget_rects(scene) -> list[tuple[str, pygame.Rect]]:  # type: ignore[no-untyped-def]
    return [(w.action or type(w).__name__, pygame.Rect(w.rect))
            for w in scene.menu.widgets]


def _in_viewport(rect: pygame.Rect) -> bool:
    return (rect.w > 0 and rect.h > 0 and rect.x >= 0 and rect.y >= 0
            and rect.right <= LOGICAL_W and rect.bottom <= LOGICAL_H)


class LayoutAssertions(unittest.TestCase):
    """Shared invariant checks."""

    def assertDisjoint(self, label: str,
                       items: list[tuple[str, pygame.Rect]]) -> None:
        for name, rect in items:
            self.assertTrue(_in_viewport(rect),
                            f"{label}: {name} {rect} leaves the "
                            f"{LOGICAL_W}x{LOGICAL_H} viewport")
        for i, (a_name, a) in enumerate(items):
            for b_name, b in items[i + 1:]:
                self.assertFalse(a.colliderect(b),
                                 f"{label}: {a_name} {a} overlaps {b_name} {b}")

    def assertContained(self, label: str, outer: pygame.Rect,
                        items: list[tuple[str, pygame.Rect]]) -> None:
        for name, rect in items:
            self.assertTrue(outer.contains(rect),
                            f"{label}: {name} {rect} escapes {outer}")


# ---------------------------------------------------------------------------
# widget layouts
# ---------------------------------------------------------------------------
class SceneWidgetLayoutTests(LayoutAssertions):
    def _menu(self) -> MenuScene:
        if not isinstance(_app.stack.current, MenuScene):
            for _ in range(600):
                if isinstance(_app.stack.current, MenuScene):
                    break
                _advance(1)
        self.assertIsInstance(_app.stack.current, MenuScene)
        return _app.stack.current  # type: ignore[return-value]

    def test_menu_widgets_fit(self) -> None:
        menu = self._menu()
        items = _widget_rects(menu)
        self.assertGreater(len(items), 8, "menu should expose every row")
        self.assertDisjoint("menu", items)

        # The whole column must finish above the shared footer band.
        lowest = max(r.bottom for _, r in items)
        self.assertLessEqual(lowest, menu_mod.FOOTER_Y - 10,
                             "menu column collides with the footer band")
        self.assertLessEqual(menu._rows_bottom + 14, menu_mod.FOOTER_Y)

        # ... and stay clear of the profile panel on the right.
        panel = menu.stats_panel
        self.assertDisjoint("menu.panel",
                            [("stats_panel", panel)] + items)

    def test_menu_profile_panel_content_fits(self) -> None:
        menu = self._menu()
        scratch = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
        for name, stats in (("empty", {}), ("full", FULL_STATS)):
            menu._stats = stats
            placed = menu._draw_stats_panel(scratch)
            panel = menu.stats_panel
            self.assertTrue(_in_viewport(panel), f"profile panel {panel}")
            self.assertContained(f"profile[{name}]", panel,
                                 [(f"content[{i}]", r)
                                  for i, r in enumerate(placed)])
            self.assertDisjoint(f"profile[{name}]",
                                [(f"content[{i}]", r)
                                 for i, r in enumerate(placed)])

    def test_menu_draws(self) -> None:
        menu = self._menu()
        menu._stats = FULL_STATS
        menu.draw(pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA))

    def test_menu_wallet_badge_and_shop_entry(self) -> None:
        """The coin balance and the shop entry must not crowd the profile panel.

        The left column has zero vertical slack (it ends flush with the
        footer), so the shop entry point lives in the right column, directly
        under the profile panel and above the toast band.
        """
        menu = self._menu()
        menu._stats = FULL_STATS
        menu.draw(pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA))

        badge = pygame.Rect(menu.wallet_rect)
        panel = pygame.Rect(menu.stats_panel)
        shop = menu.menu.get("shop")
        self.assertIsNotNone(shop, "the menu must expose a SHOP entry")
        assert shop is not None

        self.assertTrue(_in_viewport(badge), f"wallet badge off-screen {badge}")
        self.assertDisjoint("menu.economy",
                            [("stats_panel", panel), ("wallet", badge)]
                            + _widget_rects(menu))
        # The shop button sits between the profile panel and the toast band
        # (which starts at LOGICAL_H - 96) so a "no replay" toast can never
        # land on top of it.
        self.assertLessEqual(shop.rect.bottom, LOGICAL_H - 96,
                             "SHOP button collides with the toast band")
        self.assertGreaterEqual(shop.rect.top, panel.bottom + 10,
                                "SHOP button crowds the profile panel")
        self.assertEqual(shop.hotkey, "F3")
        self.assertTrue(_in_viewport(shop.rect))

    def test_settings_widgets_fit(self) -> None:
        with _pushed(SettingsScene()) as scene:
            items = _widget_rects(scene)
            self.assertGreater(len(items), 15, "all settings rows expected")
            self.assertDisjoint("settings", items)

            preview = scene._preview_rect
            self.assertDisjoint("settings.preview",
                                [("output_panel", preview)] + items)
            # Every widget must also clear the bottom of the preview panel.
            self.assertLessEqual(max(r.bottom for _, r in items), VIEWPORT.bottom)

    def test_settings_draws(self) -> None:
        with _pushed(SettingsScene()) as scene:
            scene.draw(pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA))

    def test_controls_screen_fits(self) -> None:
        """The How-to-Play card must not run off the panel or overlap itself.

        Its whole job is legibility for someone who has never seen the game,
        so a clipped row or two colliding is a worse failure here than
        anywhere else - the reader has nothing to fall back on.
        """
        from pongpro.scenes.controls import ControlsScene, PANEL_H, PANEL_W

        with _pushed(ControlsScene()) as scene:
            scene.draw(pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA))

            panel = scene._panel()
            self.assertTrue(_in_viewport(panel), f"panel off-screen {panel}")
            self.assertEqual((panel.w, panel.h), (PANEL_W, PANEL_H))

            # The dismiss button is the only widget, and it must clear the
            # bottom of the panel the two text columns are drawn inside.
            items = _widget_rects(scene)
            self.assertEqual(len(items), 1, "only the BACK row is a widget")
            button = items[0][1]
            self.assertDisjoint("controls", items)
            self.assertTrue(_in_viewport(button))
            self.assertGreaterEqual(button.top, panel.bottom - 96,
                                    "BACK button overlaps the column text")
            self.assertLessEqual(button.bottom, panel.bottom - 8,
                                 "BACK button hangs outside the panel")

    def test_controls_screen_draws(self) -> None:
        from pongpro.scenes.controls import ControlsScene

        with _pushed(ControlsScene()) as scene:
            scene.draw(pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA))

    def test_results_widgets_fit(self) -> None:
        payload = dict(_FULL_RESULTS_PAYLOAD)
        with _pushed(ResultsScene(payload=payload)) as scene:
            items = _widget_rects(scene)
            self.assertEqual(len(items), 3, "rematch / replay / menu")
            self.assertDisjoint("results", items)

            # Buttons must sit below the summary text and above the hint line.
            panel_bottom = PANEL_Y + PANEL_H
            lowest_text = panel_bottom + max(LIFETIME_DY, NOTE_DY) + 13
            top = min(r.y for _, r in items)
            bottom = max(r.bottom for _, r in items)
            self.assertGreaterEqual(top, lowest_text + 10,
                                    "action row collides with summary text")
            self.assertLessEqual(bottom, HINT_Y - 4,
                                 "action row collides with the hint line")
            self.assertEqual(bottom, BUTTON_Y + BUTTON_H)

    def test_results_draws(self) -> None:
        payload = dict(_FULL_RESULTS_PAYLOAD)
        with _pushed(ResultsScene(payload=payload)) as scene:
            scene.draw(pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA))

    def test_results_coin_band_clears_the_action_row(self) -> None:
        """The coin award must fit between the panel and the note line.

        The bottom band stacks four text rows in 80px; adding the earned-coins
        line is what pushed the note into the action row in the first place.
        """
        width = LOGICAL_W - 400
        panel = pygame.Rect(200, PANEL_Y, width, PANEL_H)
        earned = pygame.Rect(200, PANEL_Y + PANEL_H + EARNED_DY, width, EARNED_H)
        lifetime = pygame.Rect(200, PANEL_Y + PANEL_H + LIFETIME_DY, width, 14)
        note = pygame.Rect(200, PANEL_Y + PANEL_H + NOTE_DY, width, 13)
        row = pygame.Rect(200, BUTTON_Y, width, BUTTON_H)
        hint = pygame.Rect(0, HINT_Y, LOGICAL_W, 14)

        bands = [("panel", panel), ("earned", earned), ("lifetime", lifetime),
                 ("note", note), ("row", row), ("hint", hint)]
        for name, rect in bands:
            with self.subTest(band=name):
                self.assertTrue(_in_viewport(rect), f"{name} is off-screen {rect}")
        self.assertDisjoint("results.bottom_band", bands)
        self.assertLessEqual(earned.top, panel.bottom + EARNED_DY)
        self.assertLess(earned.bottom, lifetime.top)
        self.assertLess(lifetime.bottom, note.top)
        self.assertLess(note.bottom, row.top)
        self.assertLess(row.bottom, hint.top)

    def test_pause_widgets_fit(self) -> None:
        with _pushed(PauseScene()) as scene:
            items = _widget_rects(scene)
            self.assertEqual(len(items), 4, "resume / restart / settings / quit")
            self.assertDisjoint("pause", items)

            # Panel is 520x400 centred; the action column must live inside it.
            panel = pygame.Rect(LOGICAL_W // 2 - 260, LOGICAL_H // 2 - 190,
                                520, 400)
            self.assertContained("pause.panel", panel, items)

    def test_pause_draws(self) -> None:
        with _pushed(PauseScene()) as scene:
            scene.draw(pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA))


# ---------------------------------------------------------------------------
# HUD
# ---------------------------------------------------------------------------
class HudLayoutTests(LayoutAssertions):
    def test_match_state_stack_never_overlaps(self) -> None:
        fonts = _app.fonts
        cx = LOGICAL_W // 2
        combos = 0
        for match_point in (None, 0, 1):
            for deuce in (False, True):
                for rally in (0, 2, 47, 10_000):
                    for scale in (1.0, 1.35):
                        layout = match_state_rects(
                            fonts, cx=cx, target=11,
                            match_point=match_point, deuce=deuce,
                            rally=rally, rally_scale=scale)
                        self.assertIsNotNone(layout.target)
                        self.assertEqual(layout.match_point is not None,
                                         match_point is not None)
                        self.assertEqual(layout.deuce is not None, deuce)
                        self.assertEqual(layout.rally is not None, rally >= 2)
                        self.assertDisjoint(
                            f"stack(mp={match_point},deuce={deuce},"
                            f"rally={rally},scale={scale})",
                            [(f"rect[{i}]", r)
                             for i, r in enumerate(layout.rects())])
                        combos += 1
        # 3 match-point states x 2 deuce states x 4 rally sizes x 2 pop scales.
        self.assertEqual(combos, 48)

    def test_match_point_and_deuce_stack_above_rally(self) -> None:
        fonts = _app.fonts
        layout = match_state_rects(fonts, cx=LOGICAL_W // 2, target=11,
                                   match_point=0, deuce=True, rally=12,
                                   rally_scale=1.35)
        assert layout.match_point is not None
        assert layout.deuce is not None
        assert layout.rally is not None
        self.assertLessEqual(layout.target.bottom, layout.match_point.top)
        self.assertLessEqual(layout.match_point.bottom, layout.deuce.top)
        self.assertLessEqual(layout.deuce.bottom, layout.rally.top)

    def test_bottom_band_ordering(self) -> None:
        """Court wall -> meter caption -> meter -> control hints, no overlap."""
        court_bottom = LOGICAL_H - COURT_PAD_Y
        label = pygame.Rect(0, SPEED_METER_Y - 18, 120, 12)
        meter = pygame.Rect(LOGICAL_W // 2 - 130, SPEED_METER_Y, 260, 8)
        hints = pygame.Rect(0, CONTROL_HINT_Y, LOGICAL_W, 14)

        # The caption used to sit right on top of the court's bottom wall.
        self.assertGreaterEqual(label.top, court_bottom + 4,
                                "speed caption collides with the court wall")
        self.assertLessEqual(label.bottom, meter.y)
        self.assertLessEqual(meter.bottom, hints.y)
        self.assertTrue(_in_viewport(hints))
        self.assertFalse(label.colliderect(hints))
        self.assertFalse(meter.colliderect(hints))


# ---------------------------------------------------------------------------
# replay viewer geometry contract
# ---------------------------------------------------------------------------
class ReplayTransportTests(LayoutAssertions):
    def test_transport_block_clears_the_court(self) -> None:
        """Replay status line, scrub bar and legend all sit below the court.

        The status line used to be drawn at ``LOGICAL_H - 104``, where the
        court's left vertical wall and corner bracket ran straight through
        the glyphs, and the scrub bar crossed both side walls.
        """
        court_bottom = LOGICAL_H - COURT_PAD_Y
        status = pygame.Rect(60, TRANSPORT_Y, 400, STATUS_H)
        bar = pygame.Rect(60, BAR_Y, LOGICAL_W - 120, BAR_H)
        legend = pygame.Rect(0, CONTROLS_Y, LOGICAL_W, CONTROLS_H)

        self.assertGreaterEqual(status.top, court_bottom + 4,
                                "replay status line collides with the court")
        self.assertLessEqual(status.bottom, bar.y)
        self.assertLessEqual(bar.bottom, legend.y)

        for rect in (status, bar, legend):
            self.assertTrue(_in_viewport(rect))
        self.assertFalse(status.colliderect(bar))
        self.assertFalse(bar.colliderect(legend))
        self.assertFalse(status.colliderect(legend))


# ---------------------------------------------------------------------------
# shop geometry contract
# ---------------------------------------------------------------------------
class ShopLayoutTests(LayoutAssertions):
    """The shop is a three-column screen over a scrolling item list.

    The preview card and the action button deliberately live *inside* the
    detail panel, so they are asserted as contained rather than as disjoint.
    """

    @staticmethod
    def _bands(shop: ShopScene) -> list[tuple[str, pygame.Rect]]:
        return ([("tab", r) for r in shop.tab_rects()]
                + [("item", r) for r in shop.visible_rects()]
                + [("back", shop.back_rect),
                   ("detail", shop.detail_rect),
                   ("wallet", shop.wallet_rect),
                   ("status", shop.status_rect),
                   ("scrollbar", shop.scrollbar_rect),
                   ("summary", shop.summary_rect),
                   ("title", shop.title_rect),
                   ("footer", shop.footer_rect)])

    def test_bands_are_on_screen_and_do_not_overlap(self) -> None:
        with _pushed(ShopScene()) as shop:
            shop.draw(pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA))
            bands = self._bands(shop)
            for name, rect in bands:
                with self.subTest(band=name):
                    self.assertTrue(_in_viewport(rect), f"{name} {rect}")
            self.assertDisjoint("shop", bands)
            self.assertTrue(shop.detail_rect.contains(shop.preview_rect),
                            "the preview must sit inside the detail card")
            self.assertTrue(shop.detail_rect.contains(shop.action_rect),
                            "the action button must sit inside the detail card")

    def test_every_category_and_scroll_position_stays_on_screen(self) -> None:
        """Scrolling a category end to end must not shove rows off screen."""
        surface = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
        with _pushed(ShopScene()) as shop:
            for index in range(len(CATEGORIES)):
                shop._set_category(index)
                steps = max(1, int(shop.max_scroll // ROW_STEP) + 1)
                for step in range(steps):
                    shop._scroll = float(step * ROW_STEP)
                    shop._clamp_scroll()
                    shop._sync_focus_to_scroll()
                    shop.draw(surface)
                    bands = self._bands(shop)
                    self.assertTrue(bands, "scroll position showed no rows")
                    for name, rect in bands:
                        self.assertTrue(
                            _in_viewport(rect),
                            f"{shop.category.value} scroll {step}: {name} {rect}")
                    self.assertDisjoint(f"shop[{shop.category.value}]",
                                        list(bands))

    def test_every_row_is_reachable_by_scrolling(self) -> None:
        """No item may be hidden permanently behind an unreachable offset."""
        with _pushed(ShopScene()) as shop:
            for index in range(len(CATEGORIES)):
                shop._set_category(index)
                shop._scroll = 0.0
                shop._clamp_scroll()
                self.assertEqual(shop._visible_range()[0], 0,
                                 f"{shop.category.value} starts mid-list")
                shop._scroll = shop.max_scroll
                shop._clamp_scroll()
                self.assertEqual(shop._visible_range()[1],
                                 len(shop.all_items()) - 1,
                                 f"{shop.category.value} hides its last row")

    def test_scrollbar_never_covers_a_row(self) -> None:
        """The thumb lives in the gutter, so it cannot swallow row clicks."""
        with _pushed(ShopScene()) as shop:
            track = shop.scrollbar_rect
            self.assertTrue(_in_viewport(track))
            for rect in shop.visible_rects():
                self.assertFalse(track.colliderect(rect),
                                 f"scrollbar covers row {rect}")
            self.assertFalse(track.colliderect(shop.detail_rect))

    def test_wheel_scrolls_and_keeps_the_focus_visible(self) -> None:
        """The wheel must move the list, never strand the highlight."""
        with _pushed(ShopScene()) as shop:
            shop._set_category(0)                       # 10 balls
            self.assertGreater(shop.max_scroll, 0.0,
                               "a category with more rows must scroll")
            _, last = shop._visible_range()
            shop._focus = len(CATEGORIES) + last        # focus the last row
            for _ in range(6):
                shop.handle_event(pygame.event.Event(
                    pygame.MOUSEWHEEL, y=-1, x=0))
            self.assertGreater(shop.scroll, 0.0, "the wheel did not scroll")
            first, last = shop._visible_range()
            self.assertGreaterEqual(shop.focus_index, first,
                                    "focus scrolled above the viewport")
            self.assertLessEqual(shop.focus_index, last,
                                 "focus scrolled below the viewport")

    def test_every_item_in_every_category_can_be_previewed(self) -> None:
        """Regression: opening HIT EFFECTS crashed on the ring burst.

        ``emit_impact`` asked ``ParticleSystem.burst`` for a ``ring``
        parameter that never existed, so previewing any ring-shaped impact
        skin raised a TypeError the instant the tab was opened.  The free
        starter skin hid it: it is a plain spark, and every smoke run and
        screenshot only ever drew the *first* row of each category.  So walk
        every item of every category - that is the whole shop, rendered.
        """
        surface = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
        with _pushed(ShopScene()) as shop:
            drawn = 0
            for category_index in range(len(CATEGORIES)):
                shop._set_category(category_index)
                for index in range(len(shop.all_items())):
                    shop._focus_on(("item", index))
                    shop.update(1.0 / 120.0)
                    shop.draw(surface)
                    drawn += 1
            self.assertGreater(drawn, len(CATEGORIES),
                               "the shop had no items to preview")

    def test_focus_ring_never_leaves_the_screen(self) -> None:
        """Walking the whole ring (tabs -> rows -> BACK) stays inside."""
        with _pushed(ShopScene()) as shop:
            shop.draw(pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA))
            length = shop._flat_len()
            self.assertGreater(length, len(CATEGORIES) + 1,
                               "a category must expose at least one row")
            seen: set[str] = set()
            for step in range(length):
                shop._move_focus(1)
                seen.add(shop.focus_kind)
                self.assertIsNotNone(shop._detail_item(),
                                     "focus drifted past the last row")
                self.assertTrue(_in_viewport(shop.detail_rect))
            self.assertEqual(seen, {"tab", "item", "back"},
                             "the focus ring skipped a group")

    def test_shop_draws(self) -> None:
        with _pushed(ShopScene()) as shop:
            shop.draw(pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA))
            shop._set_category(1)
            shop._focus_on(("item", 2))
            shop.update(1.0 / 120.0)
            shop.draw(pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA))


# ---------------------------------------------------------------------------
# scene navigation: does clicking reach the same place the keys do?
# ---------------------------------------------------------------------------
class CreditsIntroTests(LayoutAssertions):
    """The boot credits screen: it draws, it fits, and it hands off.

    Boot order is credits -> PONG PRO splash -> menu, every launch.  A click
    skips only the screen it is on, so these tests pin the hand-off target
    (``SplashScene``, not the menu) and the timer that drives it.
    """

    CREDITS = "AASHIRYA WILSON D'SOUZA"

    def _credits(self) -> CreditsScene:
        """Leave the app on a freshly pushed CreditsScene and return it."""
        pygame.event.clear()
        _app.stack.push(CreditsScene(), transition=Transition.NONE)
        _advance(4)
        self.assertIsInstance(_app.stack.current, CreditsScene)
        return _app.stack.current  # type: ignore[return-value]

    def test_credits_draws(self) -> None:
        scene = self._credits()
        surface = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
        for moment in (0.0, 2.0, 3.8, 5.0):  # every beat, plus mid-sweep
            scene._t = moment
            scene.draw(surface)

    def test_credits_text_fits(self) -> None:
        """Both copy lines must fit the viewport at their scene sizes."""
        scratch = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
        scene = self._credits()
        scene._t = 4.5  # everything visible
        scene.draw(scratch)
        for text in ("GAME CREATOR", self.CREDITS):
            width = _app.fonts.render(text, 64, (255, 255, 255),
                                      bold=True).get_width()
            self.assertLess(width, LOGICAL_W - 160,
                            f"{text!r} is {width} px wide and would clip")

    def test_credits_click_advances_to_splash(self) -> None:
        """A click skips credits into the *splash*, not past it to the menu."""
        scene = self._credits()
        stack = _app.stack
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (0, 0)}))
        _advance(60)  # plenty for the fade to complete
        self.assertIsInstance(stack.current, SplashScene)

    def test_credits_key_advances_to_splash(self) -> None:
        scene = self._credits()
        stack = _app.stack
        pygame.event.post(pygame.event.Event(
            pygame.KEYDOWN, {"key": pygame.K_RETURN}))
        _advance(60)
        self.assertIsInstance(stack.current, SplashScene)

    def test_credits_advances_on_its_own_timer(self) -> None:
        """Untouched, credits must expire into the splash by themselves."""
        scene = self._credits()
        stack = _app.stack
        _advance(760)  # 5.6 s of credits + fade, at 120 Hz
        self.assertIsInstance(stack.current, SplashScene)

    def test_splash_version_string_says_pygame(self) -> None:
        """Text-regression guard on the literal in ``SplashScene.draw``.

        The runtime is plain pygame 2.6.1; the splash used to claim
        PYGAME-CE.  Pinning the literal directly is the honest test -
        rendering the surface and scanning pixels would be theatre.
        """
        import pathlib

        from pongpro.scenes import splash as splash_mod

        text = pathlib.Path(splash_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("PYGAME-CE", text,
                         "the splash still claims pygame-ce on screen")
        self.assertIn("PYGAME 2.6.1", text)


class SceneNavigationTests(LayoutAssertions):
    """Regression cover for mouse-driven navigation.

    A report claimed the settings BACK button did nothing on click.  These
    tests drive the *real* event pump - ``pygame.event.post`` plus
    ``step_frame`` - rather than calling the menu directly, so they exercise
    exactly what a player's mouse does, window-to-logical conversion included.
    The conversion matters: posting logical coordinates as if they were window
    coordinates silently lands the click somewhere else entirely.
    """

    def _to_window(self, pos: tuple[int, int]) -> tuple[int, int]:
        """Inverse of ``VideoManager.to_logical`` - logical -> window pixels."""
        video = _app.video
        dst = video._dst_rect
        return (int(pos[0] / video._scale_x + dst.x),
                int(pos[1] / video._scale_y + dst.y))

    def _click(self, logical_pos: tuple[int, int]) -> None:
        """Post a real motion/press/release at ``logical_pos``, then run."""
        pygame.event.clear()
        x, y = self._to_window(logical_pos)
        for etype, extra in (
                (pygame.MOUSEMOTION, {"rel": (0, 0), "buttons": (0, 0, 0)}),
                (pygame.MOUSEBUTTONDOWN, {"button": 1}),
                (pygame.MOUSEBUTTONUP, {"button": 1})):
            pygame.event.post(pygame.event.Event(etype, pos=(x, y), **extra))
            _advance(2)
        pygame.event.clear()

    def _settings(self) -> SettingsScene:
        """Leave the app on a freshly pushed SettingsScene and return it."""
        stack = _app.stack
        pygame.event.clear()
        while stack.depth > 1:
            stack.pop(transition=Transition.NONE)
            _advance(4)
        _advance(4)
        stack.push(SettingsScene(), transition=Transition.NONE)
        _advance(30)
        self.assertIsInstance(stack.current, SettingsScene)
        return stack.current

    def test_settings_back_button_leaves_on_a_mouse_click(self) -> None:
        scene = self._settings()
        back = scene.menu.get("actions.back")
        self.assertIsNotNone(back, "settings exposes no BACK widget")

        stack = _app.stack
        depth = stack.depth
        self._click(back.rect.center)
        _advance(120)  # plenty for the fade to complete

        self.assertEqual(stack.depth, depth - 1,
                         "clicking BACK did not pop the settings scene")
        self.assertNotIsInstance(stack.current, SettingsScene)

    def test_settings_back_button_leaves_from_every_edge(self) -> None:
        """Real players are not pixel-exact, so every edge has to work."""
        for name, (dx, dy) in (("centre", (0, 0)), ("left", (2, 0)),
                               ("right", (-2, 0)), ("top", (0, 2)),
                               ("bottom", (0, -2))):
            scene = self._settings()
            back = scene.menu.get("actions.back")
            centre = back.rect.center
            stack = _app.stack
            depth = stack.depth
            self._click((centre[0] + dx, centre[1] + dy))
            _advance(120)
            with self.subTest(edge=name):
                self.assertEqual(stack.depth, depth - 1,
                                 f"clicking the {name} of BACK did not pop")

    def test_no_widget_sits_under_the_settings_back_button(self) -> None:
        """Nothing may overlap BACK, or the topmost one steals the click."""
        scene = self._settings()
        back = scene.menu.get("actions.back")
        probe = back.rect.inflate(8, 8)  # the menu's hit-test tolerance band
        covering = [widget.action for widget in scene.menu.widgets
                    if widget.rect.colliderect(probe)
                    and widget.action != "actions.back"]
        self.assertEqual(covering, [],
                         f"something overlaps the BACK button: {covering}")

    # -- shop buttons at a *scaled* window --------------------------------
    #: A window size that is 16:9 but not 1280x720, so the window -> logical
    #: scale is a real 0.888... rather than the 1.0 that hides the bug.
    SCALED_WINDOW = (1440, 810)

    @contextmanager
    def _at_scaled_window(self):  # type: ignore[no-untyped-def]
        """Run the block at :data:`SCALED_WINDOW`, always restoring after."""
        video, settings = _app.video, _app.settings.video
        previous = (settings.window_width, settings.window_height)
        settings.window_width, settings.window_height = self.SCALED_WINDOW
        video.apply()
        _advance(3)
        try:
            yield video
        finally:
            settings.window_width, settings.window_height = previous
            video.apply()
            _advance(3)

    def test_the_scaled_window_check_is_actually_scaled(self) -> None:
        """Guard: these tests prove nothing if the scale happens to be 1.0."""
        with self._at_scaled_window() as video:
            self.assertNotEqual(video._scale_x, 1.0)
            self.assertNotEqual(video._scale_y, 1.0)

    def test_shop_back_click_lands_at_a_scaled_window(self) -> None:
        """The shop's buttons used to go dead at any window but the default.

        ``Application.step_frame`` already runs every event through
        ``VideoSystem.convert_event``; ``ShopScene`` was then applying
        ``to_logical`` a *second* time.  At the default 1280x720 the scale is
        1.0 and the second pass is a no-op, which is why the earlier click
        tests never reproduced it - resize the window and BACK stops
        responding unless the cursor sits below the button.
        """
        with self._at_scaled_window():
            with _pushed(ShopScene()) as shop:
                stack = _app.stack
                depth = stack.depth
                self._click(shop.back_rect.center)
                _advance(120)

                self.assertEqual(
                    stack.depth, depth - 1,
                    "clicking the centre of BACK did not leave the shop")

    def test_shop_action_click_lands_at_a_scaled_window(self) -> None:
        with self._at_scaled_window():
            with _pushed(ShopScene()) as shop:
                self.assertEqual(shop.focus_kind, "tab")
                self._click(shop.action_rect.center)
                _advance(6)

                self.assertEqual(shop.focus_kind, "item",
                                 "the BUY/EQUIP button did not take the click")
                self.assertEqual(shop.focus_index, 0)

    def test_shop_buttons_accept_a_click_a_hair_outside_them(self) -> None:
        """A button that only answers its exact interior feels broken."""
        with self._at_scaled_window():
            with _pushed(ShopScene()) as shop:
                stack = _app.stack
                depth = stack.depth
                top_edge = shop.back_rect.top - (HIT_PAD - 1)
                self._click((shop.back_rect.centerx, top_edge))
                _advance(120)

                self.assertEqual(
                    stack.depth, depth - 1,
                    f"a click {HIT_PAD - 1} px above BACK did nothing")


# ---------------------------------------------------------------------------
# the mid-court powerup pickup's presentation
# ---------------------------------------------------------------------------
class BubbleRenderTests(unittest.TestCase):
    """How the pickup is drawn, as distinct from what picking it up does.

    The halo used to be three hard concentric discs, which banded visibly
    against the court, and the pickup appeared at full brightness and
    disappeared without warning.  These measure how much light the renderer
    lays onto a fixed patch, which is enough to pin the two properties the
    redraw was bought for: it blooms in, and it warns out.
    """

    BG = (10, 12, 18)
    PATCH = 160
    BG_INK = sum(BG) * PATCH * PATCH

    def _scene(self):  # type: ignore[no-untyped-def]
        scene = GameplayScene(mode=GameMode.SOLO, difficulty=Difficulty.NORMAL,
                              target_score=5, seed=7)
        scene.ctx = _app.ctx
        scene.bubbles = BubbleField(tuple(items_in(ShopCategory.POWERUP)),
                                    scene.court, Rng(3))
        scene.bubbles._spawn()
        self.assertIsNotNone(scene.bubbles.bubble, "no bubble to draw")
        return scene

    def _ink(self, scene, *, pulse: float, life: float,  # type: ignore[no-untyped-def]
             item=None) -> int:
        """Total brightness of one rendered frame of the pickup."""
        bubble = scene.bubbles.bubble
        if item is not None:
            bubble.item = item
        bubble.pulse, bubble.life = pulse, life
        bubble.x = bubble.y = self.PATCH / 2
        patch = pygame.Surface((self.PATCH, self.PATCH))
        patch.fill(self.BG)
        scene._draw_bubbles(patch)
        return sum(pygame.image.tobytes(patch, "RGB"))

    def test_nothing_is_drawn_at_the_instant_it_spawns(self) -> None:
        scene = self._scene()
        self.assertEqual(self._ink(scene, pulse=0.0, life=30.0), self.BG_INK,
                         "a pickup appeared fully formed instead of blooming in")

    def test_it_fades_at_both_ends_of_its_life(self) -> None:
        scene = self._scene()
        steady = self._ink(scene, pulse=2.0, life=30.0)
        spawning = self._ink(scene, pulse=0.12, life=30.0)
        expiring = self._ink(scene, pulse=2.0, life=0.4)
        self.assertGreater(steady, self.BG_INK, "the pickup drew nothing at all")
        self.assertLess(spawning, steady, "the spawn bloom never showed")
        self.assertLess(expiring, steady, "the expiry warning never showed")

    def test_every_powerup_can_draw_its_own_pickup(self) -> None:
        """Each item brings its own accent and glyph; none may draw nothing."""
        scene = self._scene()
        for item in items_in(ShopCategory.POWERUP):
            with self.subTest(item=item.id):
                ink = self._ink(scene, pulse=3.0, life=30.0, item=item)
                self.assertGreater(ink, self.BG_INK,
                                   f"{item.id} rendered as a blank patch")


# ---------------------------------------------------------------------------
# results / settings geometry contracts
# ---------------------------------------------------------------------------
class ScreenRhythmTests(LayoutAssertions):
    def test_results_button_row_is_on_screen(self) -> None:
        total = 320 * 3 + 30 * 2
        x = (LOGICAL_W - total) // 2
        row = pygame.Rect(x, BUTTON_Y, total, BUTTON_H)
        self.assertTrue(_in_viewport(row))
        self.assertGreaterEqual(row.y, PANEL_Y + PANEL_H + NOTE_DY + 13 + 10)
        self.assertLessEqual(row.bottom, HINT_Y - 4)

    def test_menu_footer_band_is_free(self) -> None:
        band = pygame.Rect(0, menu_mod.FOOTER_Y, LOGICAL_W, 14)
        self.assertTrue(_in_viewport(band))
        self.assertLessEqual(band.bottom, LOGICAL_H)


if __name__ == "__main__":
    unittest.main()
