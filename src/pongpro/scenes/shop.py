"""The shop: browse, buy and equip cosmetics and powerups.

Layout (all constants live at module level so ``tests/test_layout.py`` can
assert in-bounds + non-overlap without rendering anything)::

    940..1240   wallet badge            (34..82)
    40..248     category tabs x6        (116..432)
    40..248     owned summary           (452..472)
    40..248     BACK                    (580..626)
    272..812    item list, viewport x7  (116..486, clipped)
    818..822    scrollbar track         (116..478, gutter)
    272..812    "showing 1-7 of 10"     (500..524)
    836..1240   detail + live preview   (116..636)
    40..1240    footer hint             (660..680)

Navigation: UP/DOWN walks tabs -> items -> BACK, LEFT/RIGHT switches category,
ENTER buys or equips, ESC leaves.  Mouse hover focuses, clicks activate, and
the wheel scrolls the list (which is what people expect of a wheel - there is
no second "page" key to learn).  The list holds all of a category's items and
scrolls a viewport of seven rows over them; the focused row is always pulled
back into view, so the highlight can never sit somewhere off screen.

The detail panel draws a *live preview* using the same
:mod:`pongpro.rendering.skins` code that will draw the item in a match, so
there is no second, drift-prone "preview renderer" to keep honest.
"""

from __future__ import annotations

import math

import pygame

from ..core.constants import Color, LOGICAL_W
from ..core.state_machine import Scene, Transition
from ..economy.catalog import (
    CATEGORIES,
    RARITY_COLORS,
    BackgroundLook,
    BallLook,
    PaddleLook,
    PowerEffect,
    PowerupSpec,
    ShopCategory,
    ShopItem,
    TrailLook,
    default_item,
    items_in,
)
from ..economy.wallet import Wallet, get_wallet, save_wallet
from ..gameplay.entities import default_court
from ..rendering.particles import ParticleSystem
from ..rendering.skins import (
    CLASSIC_BACKGROUND,
    draw_ball,
    draw_paddle,
    draw_trail,
    emit_impact,
    glow_sprite,
)
from .common import draw_backdrop, draw_panel, draw_title

# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------
TITLE_Y = 32
TITLE_SIZE = 56

WALLET_RECT = pygame.Rect(940, 34, 300, 48)

TAB_X = 40
TAB_W = 208
TAB_H = 46
TAB_Y0 = 116
TAB_STEP = 54            # 6 tabs -> last bottom 432

LIST_X = 272
LIST_W = 540
LIST_Y0 = 116
ROW_H = 46
ROW_STEP = 54
#: How many rows fit on screen at once.  The rest scroll into view, so a
#: category never needs a "page" key - there is no second page to forget about.
VIEW_ROWS = 7
LIST_TOP = LIST_Y0
LIST_BOTTOM = LIST_Y0 + (VIEW_ROWS - 1) * ROW_STEP + ROW_H   # 486
VIEWPORT_H = LIST_BOTTOM - LIST_TOP                            # 370
#: One mouse-wheel notch scrolls exactly one row.
WHEEL_STEP = ROW_STEP

SUMMARY_RECT = pygame.Rect(TAB_X, 452, TAB_W, 20)
BACK_RECT = pygame.Rect(TAB_X, 580, TAB_W, 46)
#: "SHOWING 1-7 OF 10" line, where the old page counter used to live.
STATUS_RECT = pygame.Rect(LIST_X, 500, LIST_W, 24)
#: Scrollbar, parked in the gutter between the list and the detail card so it
#: can never cover a row or swallow a click meant for one.
SCROLLBAR_RECT = pygame.Rect(LIST_X + LIST_W + 6, LIST_Y0, 4, VIEWPORT_H - 8)

DETAIL_RECT = pygame.Rect(836, 116, 404, 520)
PREVIEW_W = 292
PREVIEW_H = 164          # 16:9, so backgrounds are not stretched
PREVIEW_RECT = pygame.Rect(
    DETAIL_RECT.centerx - PREVIEW_W // 2, 186, PREVIEW_W, PREVIEW_H)

#: First baseline of the detail panel's description block.
DETAIL_TEXT_Y = 362
DETAIL_LINE = 20
#: First baseline of the spec block (powerup stats, or cosmetic metadata),
#: sitting below the tallest description the card can show.
DETAIL_STAT_Y = 474
DETAIL_STAT_LINE = 19
ACTION_RECT = pygame.Rect(DETAIL_RECT.x + 18, 572,
                          DETAIL_RECT.w - 36, 46)

FOOTER_Y = 660
FOOTER_RECT = pygame.Rect(40, FOOTER_Y, LOGICAL_W - 80, 20)

#: How long a toast ("BOUGHT ...") stays on screen, and how long the preview
#: impact effect waits between replays.
TOAST_SECONDS = 1.6
IMPACT_PERIOD = 0.7

#: Column (in characters) at which a spec block's value starts, so
#: TARGET / DURATION / COOLDOWN line up regardless of label length.
_SPEC_LABEL_W = 16

#: Number of tabs - the focus model is tabs, then items, then BACK.
_TAB_COUNT = len(CATEGORIES)

#: Extra pixels of forgiveness grown onto every clickable rect, for
#: hit-testing only - never for drawing.  A control is 46 px tall on a 54 px
#: pitch, so +/-4 px tiles the screen exactly: a click lands on whatever looks
#: like a button (including the gutter just outside it) and no two targets can
#: ever overlap.  Padding is what makes a hit target survive the rounding a
#: real cursor does on its way to the middle of a button.
HIT_PAD = 4


def _clickable(rect: pygame.Rect) -> pygame.Rect:
    """``rect`` grown by :data:`HIT_PAD` on every side, for hit-testing."""
    return rect.inflate(HIT_PAD * 2, HIT_PAD * 2)


def _spec_row(label: str, value: str) -> str:
    """One ``LABEL ...... VALUE`` line for the detail panel's spec block."""
    return f"{label.upper():<{_SPEC_LABEL_W}}{value}"


def _wrap(fonts, text: str, size: int, max_w: int) -> list[str]:  # type: ignore[no-untyped-def]
    """Greedy word wrap using the real font metrics."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if not current or fonts.width(trial, size) <= max_w:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


class ShopScene(Scene):
    """Browse, buy and equip.  Pushed from the menu; pops back to it."""

    opaque = True

    def __init__(self) -> None:
        super().__init__()
        self._t = 0.0
        self.wallet: Wallet | None = None
        self.background: BackgroundLook = CLASSIC_BACKGROUND
        self._cat_index = 0
        self._scroll = 0.0
        self._focus = 0
        self._toast = ""
        self._toast_t = 0.0
        self._impact_t = 0.0
        self._title_rect = pygame.Rect(0, 0, 0, 0)
        self._preview_particles: ParticleSystem | None = None
        self._court_cache: dict[str, pygame.Surface] = {}

    # -- lifecycle --------------------------------------------------------
    def on_enter(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._t = 0.0
        self._toast = ""
        self._toast_t = 0.0
        self._impact_t = IMPACT_PERIOD
        self.wallet = get_wallet(self.ctx)
        look = self.wallet.equipped_item(ShopCategory.BACKGROUND).data
        self.background = look if isinstance(look, BackgroundLook) else CLASSIC_BACKGROUND
        self._preview_particles = ParticleSystem(self.ctx.rng.fork())
        self._cat_index = 0
        self._scroll = 0.0
        self._focus = 0

    def on_exit(self) -> None:
        # Persist anything bought or equipped even if we are popped by a
        # scene change rather than by the BACK button.
        if self.wallet is not None:
            save_wallet(self.ctx, self.wallet)

    # -- geometry (read back by the layout tests) -------------------------
    @property
    def category(self) -> ShopCategory:
        return CATEGORIES[self._cat_index]

    @property
    def scroll(self) -> float:
        """Current list scroll offset in pixels (0 = first row flush)."""
        return self._scroll

    @property
    def max_scroll(self) -> float:
        return self._max_scroll()

    def tab_rects(self) -> tuple[pygame.Rect, ...]:
        return tuple(pygame.Rect(TAB_X, TAB_Y0 + i * TAB_STEP, TAB_W, TAB_H)
                     for i in range(_TAB_COUNT))

    @property
    def wallet_rect(self) -> pygame.Rect:
        return pygame.Rect(WALLET_RECT)

    @property
    def back_rect(self) -> pygame.Rect:
        return pygame.Rect(BACK_RECT)

    @property
    def detail_rect(self) -> pygame.Rect:
        return pygame.Rect(DETAIL_RECT)

    @property
    def preview_rect(self) -> pygame.Rect:
        return pygame.Rect(PREVIEW_RECT)

    @property
    def action_rect(self) -> pygame.Rect:
        return pygame.Rect(ACTION_RECT)

    @property
    def title_rect(self) -> pygame.Rect:
        return pygame.Rect(self._title_rect)

    @property
    def footer_rect(self) -> pygame.Rect:
        return pygame.Rect(FOOTER_RECT)

    @property
    def status_rect(self) -> pygame.Rect:
        """The ``SHOWING 1-7 OF 10`` line under the list."""
        return pygame.Rect(STATUS_RECT)

    @property
    def scrollbar_rect(self) -> pygame.Rect:
        """Track of the list scrollbar (thumb is in the gutter)."""
        return pygame.Rect(SCROLLBAR_RECT)

    @property
    def summary_rect(self) -> pygame.Rect:
        return pygame.Rect(SUMMARY_RECT)

    @property
    def focus_kind(self) -> str:
        """``"tab"``, ``"item"`` or ``"back"`` - the focus model for tests."""
        if self._focus < _TAB_COUNT:
            return "tab"
        if self._focus < _TAB_COUNT + len(self.all_items()):
            return "item"
        return "back"

    @property
    def focus_index(self) -> int:
        """Local index within the focused group (tab column / row / 0)."""
        if self._focus < _TAB_COUNT:
            return self._focus
        if self._focus < _TAB_COUNT + len(self.all_items()):
            return self._focus - _TAB_COUNT
        return 0

    def all_items(self) -> tuple[ShopItem, ...]:
        """Every item in the current category - the list's full content."""
        return items_in(self.category)

    def visible_items(self) -> tuple[ShopItem, ...]:
        """Rows currently intersecting the viewport (used for hit-testing)."""
        viewport = self._viewport()
        return tuple(item for index, item in enumerate(self.all_items())
                     if self._row_rect(index).colliderect(viewport))

    # -- scrolling ---------------------------------------------------------
    def _viewport(self) -> pygame.Rect:
        return pygame.Rect(LIST_X, LIST_TOP, LIST_W, VIEWPORT_H)

    def _row_rect(self, index: int) -> pygame.Rect:
        """Screen rect of catalogue row ``index``, offset by the scroll."""
        return pygame.Rect(LIST_X,
                           int(round(LIST_TOP + index * ROW_STEP - self._scroll)),
                           LIST_W, ROW_H)

    def _max_scroll(self) -> float:
        count = len(self.all_items())
        if count <= VIEW_ROWS:
            return 0.0
        return float((count - 1) * ROW_STEP + ROW_H - VIEWPORT_H)

    def _clamp_scroll(self) -> None:
        self._scroll = max(0.0, min(self._scroll, self._max_scroll()))

    def _ensure_visible(self, index: int) -> None:
        """Scroll the minimum amount needed to bring row ``index`` into view."""
        top = index * ROW_STEP
        bottom = top + ROW_H
        if top < self._scroll:
            self._scroll = float(top)
        elif bottom > self._scroll + VIEWPORT_H:
            self._scroll = float(bottom - VIEWPORT_H)
        self._clamp_scroll()

    def _visible_range(self) -> tuple[int, int]:
        """Inclusive catalogue-index range currently on screen."""
        count = len(self.all_items())
        if count == 0:
            return (0, -1)
        first = int(math.floor(self._scroll / ROW_STEP))
        last = int(math.ceil((self._scroll + VIEWPORT_H) / ROW_STEP)) - 1
        return (max(0, first), min(count - 1, last))

    def _sync_focus_to_scroll(self) -> None:
        """After a wheel scroll, keep the focused row on screen."""
        if self.focus_kind != "item":
            return
        first, last = self._visible_range()
        if self.focus_index < first:
            self._focus = _TAB_COUNT + first
        elif self.focus_index > last:
            self._focus = _TAB_COUNT + last

    # -- focus model ------------------------------------------------------
    def _flat_len(self) -> int:
        return _TAB_COUNT + len(self.all_items()) + 1  # + BACK

    def _clamp_focus(self) -> None:
        self._focus = max(0, min(self._focus, self._flat_len() - 1))

    def _move_focus(self, delta: int) -> None:
        length = self._flat_len()
        self._focus = (self._focus + delta) % length
        # Landing on a tab selects it - arrowing through the tab bar should
        # preview each category immediately rather than needing a confirm.
        if self._focus < _TAB_COUNT:
            self._set_category(self._focus, move_focus=False)
        self._clamp_focus()
        if self.focus_kind == "item":
            self._ensure_visible(self.focus_index)

    def _set_category(self, index: int, *, move_focus: bool = True) -> None:
        index %= _TAB_COUNT
        kind, local = self.focus_kind, self.focus_index
        self._cat_index = index
        self._scroll = 0.0
        if move_focus and kind == "tab":
            self._focus = index
        elif kind == "item":
            self._focus = _TAB_COUNT + min(
                local, max(0, len(self.all_items()) - 1))
        self._clamp_focus()

    def _hit(self, pos: tuple[int, int]) -> tuple[str, int] | None:
        # NOTE: ``pos`` is already in logical units.  Application.step_frame
        # runs every event through VideoSystem.convert_event before it reaches
        # a scene, so converting again here mapped the cursor a *second* time.
        # Whenever the window was not exactly 1280x720 the scale factor was
        # not 1.0, the second pass dragged the point toward the origin, and
        # the two big buttons at the bottom of the screen - the ones a player
        # actually reaches for - went dead unless the cursor sat below them.
        # This was invisible at the default window size, which is exactly why
        # the click tests never caught it.
        for index, rect in enumerate(self.tab_rects()):
            if _clickable(rect).collidepoint(pos):
                return ("tab", index)
        # Rows live inside a clipped viewport, so a click in the gutter above
        # or below it must not reach a row that has been scrolled out of sight.
        if _clickable(self._viewport()).collidepoint(pos):
            for index in range(len(self.all_items())):
                if _clickable(self._row_rect(index)).collidepoint(pos):
                    return ("item", index)
        if _clickable(BACK_RECT).collidepoint(pos):
            return ("back", 0)
        if _clickable(ACTION_RECT).collidepoint(pos):
            # The big action button acts on the item on show: take the current
            # row (or the first row when a tab has focus) and select it.
            if self.focus_kind == "item":
                return ("item", self.focus_index)
            return ("item", 0)
        return None

    def _focus_on(self, target: tuple[str, int]) -> None:
        kind, local = target
        if kind == "tab":
            self._set_category(local)
        elif kind == "item":
            self._focus = _TAB_COUNT + local
        else:
            self._focus = self._flat_len() - 1
        self._clamp_focus()

    def visible_rects(self) -> tuple[pygame.Rect, ...]:
        """Screen rects of the rows currently in the viewport, top to bottom."""
        viewport = self._viewport()
        return tuple(rect for rect in
                     (self._row_rect(i) for i in range(len(self.all_items())))
                     if rect.colliderect(viewport))

    # -- input ------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            key = event.key
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._leave()
            elif key in (pygame.K_UP, pygame.K_TAB) and not (event.mod & pygame.KMOD_SHIFT):
                self._move_focus(-1)
                self._sound("ui_move", 0.7)
            elif key in (pygame.K_DOWN, pygame.K_TAB):
                self._move_focus(1)
                self._sound("ui_move", 0.7)
            elif key == pygame.K_LEFT:
                self._set_category(self._cat_index - 1)
                self._sound("ui_move", 0.7)
            elif key == pygame.K_RIGHT:
                self._set_category(self._cat_index + 1)
                self._sound("ui_move", 0.7)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._activate()
            return

        if event.type == pygame.MOUSEWHEEL:
            # The wheel scrolls the *list*, which is what people expect of a
            # wheel; the focused row is then pulled back into view so the
            # highlight can never end up somewhere off screen.
            if event.y:
                self._scroll -= event.y * WHEEL_STEP
                self._clamp_scroll()
                self._sync_focus_to_scroll()
                self._sound("ui_move", 0.5)
            return

        if event.type == pygame.MOUSEMOTION:
            # ``event.pos`` is already logical - Application.step_frame ran
            # convert_event on its way here.  Converting again (the old
            # ``self._logical_mouse``) applied the window scale a second time
            # and made the shop's buttons unclickable at any window size other
            # than the default 1280x720.  See ``_hit``.
            target = self._hit(event.pos)
            if target is not None:
                self._focus_on(target)
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
            if event.button == 3:
                self._leave()
                return
            target = self._hit(event.pos)
            if target is not None:
                self._focus_on(target)
                self._activate()

    def _sound(self, name: str, volume: float = 1.0) -> None:
        self.ctx.audio.play(name, volume=volume)

    def _activate(self) -> None:
        kind = self.focus_kind
        if kind == "tab":
            # Confirming a tab steps into its item list.
            self._focus = _TAB_COUNT
            self._clamp_focus()
            self._sound("ui_select")
        elif kind == "item":
            self._activate_item(self.all_items()[self.focus_index])
        else:
            self._leave()

    def _activate_item(self, item: ShopItem) -> None:
        wallet, ctx = self.wallet, self.ctx
        if wallet is None:
            return
        if wallet.owns(item.id):
            if wallet.equipped_id(item.category) == item.id:
                self._sound("deny", 0.6)
                self._say("ALREADY EQUIPPED")
            else:
                wallet.equip(item.id)
                save_wallet(ctx, wallet)
                self._sound("ui_select")
                self._say(f"EQUIPPED {item.name}")
        elif wallet.buy(item.id):
            save_wallet(ctx, wallet)
            self._sound("win", 0.6)
            self._say(f"BOUGHT {item.name}")
        else:
            self._sound("deny")
            self._say("NOT ENOUGH COINS")

    def _say(self, text: str) -> None:
        self._toast = text
        self._toast_t = TOAST_SECONDS

    def _leave(self) -> None:
        if self.wallet is not None:
            save_wallet(self.ctx, self.wallet)
        self._sound("ui_back")
        assert self.stack is not None
        self.stack.pop(transition=Transition.FADE)

    # -- frame ------------------------------------------------------------
    def update(self, dt: float) -> None:
        self._t += dt
        if self._toast_t > 0.0:
            self._toast_t = max(0.0, self._toast_t - dt)
        if self._preview_particles is not None:
            self._impact_t += dt
            if self._impact_t >= IMPACT_PERIOD:
                self._impact_t = 0.0
                self._preview_particles.clear()
                item = self._detail_item()
                if item is not None and item.category is ShopCategory.IMPACT:
                    emit_impact(self._preview_particles, item.data,
                                PREVIEW_RECT.w * 0.5, PREVIEW_RECT.h * 0.5,
                                Color.ACCENT, scale=1.4)
            self._preview_particles.update(dt)

    def _detail_item(self) -> ShopItem | None:
        # ``focus_index`` is a *catalogue* index (the row may have been
        # scrolled out of view), so this must read the full list, not the
        # viewport slice - otherwise a scrolled shop shows the wrong card.
        items = self.all_items()
        if not items:
            return None
        if self.focus_kind == "item":
            return items[min(self.focus_index, len(items) - 1)]
        return items[0]

    # -- drawing ----------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        fonts = self.ctx.fonts
        draw_backdrop(surface, self._t, seed=99, vignette=80,
                      look=self.background)
        self._title_rect = draw_title(surface, "SHOP", fonts, y=TITLE_Y,
                                      size=TITLE_SIZE, color=Color.TEXT)
        hint = fonts.render(
            "ARROWS SELECT  ·  ENTER BUY / EQUIP  ·  WHEEL SCROLL  ·  ESC BACK",
            14, Color.TEXT_DIM, bold=True)
        surface.blit(hint, (surface.get_width() // 2 - hint.get_width() // 2, 100))

        self._draw_wallet(surface)
        self._draw_tabs(surface)
        self._draw_summary(surface)
        self._draw_list(surface)
        self._draw_detail(surface)
        self._draw_back(surface)
        self._draw_footer(surface)

    def _draw_wallet(self, surface: pygame.Surface) -> None:
        fonts = self.ctx.fonts
        rect = pygame.Rect(WALLET_RECT)
        coins = self.wallet.coins if self.wallet is not None else 0
        accent = Color.GOLD
        pygame.draw.rect(surface, Color.blend(Color.PANEL, accent, 0.16), rect,
                         border_radius=10)
        pygame.draw.rect(surface, Color.blend(Color.LINE_SOFT, accent, 0.7), rect,
                         width=1, border_radius=10)
        label = fonts.render("COINS", 13, Color.TEXT_DIM, bold=True)
        surface.blit(label, (rect.x + 14, rect.centery - label.get_height() // 2))
        pygame.draw.circle(surface, accent, (rect.x + 92, rect.centery), 7)
        pygame.draw.circle(surface, Color.blend(accent, (255, 255, 255), 0.6),
                           (rect.x + 90, rect.centery - 2), 3)
        amount = fonts.render(f"{coins:,}", 24, Color.TEXT, bold=True,
                              shadow=True)
        surface.blit(amount, (rect.right - amount.get_width() - 16,
                              rect.centery - amount.get_height() // 2))

    def _draw_tabs(self, surface: pygame.Surface) -> None:
        fonts = self.ctx.fonts
        for index, rect in enumerate(self.tab_rects()):
            category = CATEGORIES[index]
            selected = index == self._cat_index
            focused = (self.focus_kind == "tab" and index == self.focus_index)
            accent = Color.ACCENT if selected else Color.P1
            fill = Color.blend(Color.PANEL, accent, 0.30 if selected else 0.06)
            if focused:
                fill = Color.blend(fill, (255, 255, 255), 0.10)
            pygame.draw.rect(surface, fill, rect, border_radius=8)
            pygame.draw.rect(surface,
                             Color.blend(Color.LINE_SOFT, accent,
                                         0.85 if selected else (0.5 if focused else 0.15)),
                             rect, width=1, border_radius=8)
            count = len(items_in(category))
            text = fonts.render(category.title, 17,
                                Color.TEXT if selected else Color.TEXT_DIM,
                                bold=True)
            surface.blit(text, (rect.x + 14,
                                rect.centery - text.get_height() // 2))
            badge = fonts.render(str(count), 15,
                                 Color.TEXT_DIM if not selected else accent,
                                 bold=True)
            surface.blit(badge, (rect.right - badge.get_width() - 14,
                                 rect.centery - badge.get_height() // 2))

    def _draw_summary(self, surface: pygame.Surface) -> None:
        fonts = self.ctx.fonts
        wallet = self.wallet
        if wallet is None:
            return
        rect = SUMMARY_RECT
        owned = wallet.owned_count(self.category)
        total = len(items_in(self.category))
        text = fonts.render(f"{owned} / {total} OWNED", 15, Color.TEXT_DIM,
                            bold=True)
        surface.blit(text, (rect.x, rect.y))

    def _draw_list(self, surface: pygame.Surface) -> None:
        fonts = self.ctx.fonts
        wallet = self.wallet
        items = self.all_items()
        viewport = self._viewport()
        equipped = (wallet.equipped_id(self.category) if wallet is not None
                    else default_item(self.category).id)

        # Clip to the list viewport so a half-scrolled row is cut off cleanly
        # instead of painting over the summary line above it.
        previous_clip = surface.get_clip()
        surface.set_clip(viewport)
        for index, item in enumerate(items):
            rect = self._row_rect(index)
            if not rect.colliderect(viewport):
                continue
            focused = (self.focus_kind == "item" and index == self.focus_index)
            is_equipped = wallet is not None and wallet.owns(item.id) \
                and equipped == item.id
            is_owned = wallet is not None and wallet.owns(item.id)
            rarity = RARITY_COLORS[item.rarity]

            fill = Color.PANEL if not is_equipped else Color.blend(
                Color.PANEL, Color.GOLD, 0.14)
            if focused:
                fill = Color.blend(fill, (255, 255, 255), 0.18)
            pygame.draw.rect(surface, fill, rect, border_radius=8)
            if is_equipped:
                pygame.draw.rect(surface, Color.GOLD, rect, width=2,
                                 border_radius=8)
            if focused:
                # A second ring *inside* the row, so keyboard focus is
                # unmistakable without erasing the gold "equipped" cue.
                pygame.draw.rect(surface, Color.ACCENT, rect.inflate(-5, -7),
                                 width=1, border_radius=6)
            elif not is_equipped:
                pygame.draw.rect(surface,
                                 Color.blend(Color.LINE_SOFT, rarity, 0.18),
                                 rect, width=1, border_radius=8)
            pygame.draw.rect(surface, rarity,
                             (rect.x, rect.y + 6, 4, rect.h - 12),
                             border_radius=2)

            name = fonts.render(item.name, 18,
                                Color.TEXT if (focused or is_equipped)
                                else Color.blend(Color.TEXT_DIM, Color.TEXT, 0.45),
                                bold=is_equipped)
            surface.blit(name, (rect.x + 18,
                                rect.centery - name.get_height() // 2))

            if is_equipped:
                status, status_color = "EQUIPPED", Color.GOLD
            elif is_owned:
                status, status_color = "OWNED", Color.TEXT_DIM
            elif wallet is not None and not wallet.can_afford(item.price):
                status, status_color = f"{item.price:,}", Color.WARN
            else:
                status, status_color = f"{item.price:,}", Color.GOLD
            rendered = fonts.render(status, 16, status_color, bold=True)
            surface.blit(rendered, (rect.right - rendered.get_width() - 18,
                                    rect.centery - rendered.get_height() // 2))
            if not is_owned:
                pygame.draw.circle(surface, status_color,
                                   (rect.right - rendered.get_width() - 32,
                                    rect.centery), 5)

        surface.set_clip(previous_clip)
        self._draw_scrollbar(surface)
        self._draw_status(surface)

        # Toast - purchased / equipped feedback, drawn over the list gutter.
        if self._toast_t > 0.0:
            alpha = min(1.0, self._toast_t / 0.35)
            toast = fonts.render(self._toast, 17, Color.ACCENT, bold=True,
                                 shadow=True)
            y = STATUS_RECT.bottom + 26
            x = LIST_X + (LIST_W - toast.get_width()) // 2
            fade = pygame.Surface((toast.get_width() + 4,
                                   toast.get_height() + 4), pygame.SRCALPHA)
            fade.blit(toast, (2, 2))
            fade.set_alpha(int(255 * alpha))
            surface.blit(fade, (x, y))

    def _draw_status(self, surface: pygame.Surface) -> None:
        """``SHOWING 1-7 OF 10`` - the honest replacement for a page number."""
        fonts = self.ctx.fonts
        total = len(self.all_items())
        first, last = self._visible_range()
        label = (f"{total} ITEMS" if total <= VIEW_ROWS
                 else f"SHOWING {first + 1}-{last + 1} OF {total}")
        text = fonts.render(label, 14, Color.TEXT_DIM, bold=True)
        surface.blit(text, (STATUS_RECT.x, STATUS_RECT.y))

    def _draw_scrollbar(self, surface: pygame.Surface) -> None:
        """Thumb parked in the gutter; hidden when everything already fits."""
        max_scroll = self._max_scroll()
        if max_scroll <= 0.0:
            return
        track = SCROLLBAR_RECT
        # Thumb length mirrors the visible share of the list.
        thumb_h = max(28, int(track.h * VIEWPORT_H / (VIEWPORT_H + max_scroll)))
        travel = track.h - thumb_h
        thumb_y = track.y + int(round(travel * (self._scroll / max_scroll)))
        pygame.draw.rect(surface,
                         Color.blend(Color.PANEL, Color.TEXT_DIM, 0.30),
                         (track.x, track.y, track.w, track.h),
                         border_radius=2)
        pygame.draw.rect(surface,
                         Color.blend(Color.ACCENT, Color.TEXT_DIM, 0.5),
                         (track.x, thumb_y, track.w, thumb_h),
                         border_radius=2)

    def _draw_detail(self, surface: pygame.Surface) -> None:
        fonts = self.ctx.fonts
        item = self._detail_item()
        if item is None:
            return
        rarity = RARITY_COLORS[item.rarity]
        draw_panel(surface, DETAIL_RECT, accent=rarity, alpha=225)

        # Name + rarity.
        name = fonts.render(item.name, 26, Color.TEXT, bold=True, shadow=True)
        surface.blit(name, (DETAIL_RECT.x + 18, 132))
        chip_text = f"{item.rarity.value.upper()}  ·  {item.category.title}"
        chip = fonts.render(chip_text, 14, rarity, bold=True)
        surface.blit(chip, (DETAIL_RECT.x + 18, 166))

        # Price / status strip, top-right of the panel.
        wallet = self.wallet
        if wallet is not None and wallet.owns(item.id):
            status = "EQUIPPED" if wallet.equipped_id(item.category) == item.id \
                else "OWNED"
            status_color = Color.GOLD if status == "EQUIPPED" else Color.TEXT_DIM
        elif wallet is not None and not wallet.can_afford(item.price):
            status, status_color = f"{item.price:,} COINS", Color.WARN
        else:
            status, status_color = f"{item.price:,} COINS", Color.GOLD
        rendered = fonts.render(status, 18, status_color, bold=True)
        surface.blit(rendered, (DETAIL_RECT.right - rendered.get_width() - 18,
                                136))

        self._draw_preview(surface, item)

        # Description (wrapped to the panel width).
        body = _wrap(fonts, item.description, 15, DETAIL_RECT.w - 36)
        for index, line in enumerate(body[:5]):
            surface.blit(fonts.render(line, 15, Color.TEXT_DIM),
                         (DETAIL_RECT.x + 18, DETAIL_TEXT_Y + index * DETAIL_LINE))

        for index, line in enumerate(self._spec_lines(item)[:4]):
            surface.blit(fonts.render(line, 14, Color.TEXT, bold=True),
                         (DETAIL_RECT.x + 18,
                          DETAIL_STAT_Y + index * DETAIL_STAT_LINE))

        self._draw_action(surface, item)

    def _spec_lines(self, item: ShopItem) -> list[str]:
        """The spec block under the description.

        Cosmetics get the same shape as powerups so a two-line description
        does not leave a hole above the action button.
        """
        if item.category is ShopCategory.POWERUP:
            return self._stat_lines(item.data)
        return [_spec_row("CATEGORY", item.category.title),
                _spec_row("RARITY", item.rarity.value.upper()),
                _spec_row("TYPE", "VISUAL ONLY")]

    def _stat_lines(self, spec: PowerupSpec) -> list[str]:
        lines = [_spec_row("TARGET", spec.target.value.upper())]
        if spec.duration > 0.0:
            lines.append(_spec_row("DURATION", f"{spec.duration:.1f}s"))
        if spec.cooldown > 0.0:
            lines.append(_spec_row("COOLDOWN", f"{spec.cooldown:.1f}s"))
        if spec.effect is not PowerEffect.NONE:
            effect = spec.effect.value.replace("_", " ").upper()
            if spec.magnitude != 1.0:
                effect += f"  x{spec.magnitude:g}"
            if spec.coins:
                effect += f"  +{spec.coins} COINS/HIT"
            lines.append(_spec_row("EFFECT", effect))
        return lines

    def _draw_action(self, surface: pygame.Surface, item: ShopItem) -> None:
        fonts = self.ctx.fonts
        wallet = self.wallet
        focused = self.focus_kind == "item"
        if wallet is None:
            label, color, enabled = "CLOSE", Color.TEXT, True
        elif wallet.owns(item.id) and wallet.equipped_id(item.category) == item.id:
            label, color, enabled = "EQUIPPED", Color.GOLD, False
        elif wallet.owns(item.id):
            label, color, enabled = "EQUIP", Color.ACCENT, True
        elif wallet.can_afford(item.price):
            label, color, enabled = f"BUY  {item.price:,} COINS", Color.ACCENT, True
        else:
            label, color, enabled = "NOT ENOUGH COINS", Color.WARN, False

        rect = pygame.Rect(ACTION_RECT)
        fill = Color.blend(Color.PANEL_LIGHT, color, 0.30 if enabled else 0.10)
        if focused:
            fill = Color.blend(fill, (255, 255, 255), 0.10)
        pygame.draw.rect(surface, fill, rect, border_radius=8)
        pygame.draw.rect(surface, Color.blend(Color.LINE_SOFT, color,
                                              0.9 if enabled else 0.3),
                         rect, width=1, border_radius=8)
        text = fonts.render(label, 20, Color.TEXT if enabled else color,
                            bold=True)
        surface.blit(text, (rect.centerx - text.get_width() // 2,
                            rect.centery - text.get_height() // 2))

    def _draw_back(self, surface: pygame.Surface) -> None:
        fonts = self.ctx.fonts
        rect = pygame.Rect(BACK_RECT)
        focused = self.focus_kind == "back"
        fill = Color.blend(Color.PANEL_LIGHT, Color.P1, 0.12)
        if focused:
            fill = Color.blend(fill, (255, 255, 255), 0.13)
        pygame.draw.rect(surface, fill, rect, border_radius=8)
        pygame.draw.rect(surface, Color.blend(Color.LINE_SOFT, Color.P1,
                                              0.8 if focused else 0.3),
                         rect, width=1, border_radius=8)
        text = fonts.render("BACK", 20, Color.TEXT, bold=True)
        surface.blit(text, (rect.centerx - text.get_width() // 2,
                            rect.centery - text.get_height() // 2))
        key = fonts.render("ESC", 13, Color.TEXT_DIM, bold=True)
        surface.blit(key, (rect.x + 14, rect.y + 6))

    def _draw_footer(self, surface: pygame.Surface) -> None:
        fonts = self.ctx.fonts
        rendered = fonts.render(
            "UP/DOWN MOVE  ·  LEFT/RIGHT CATEGORY  ·  ENTER SELECT  ·  ESC BACK",
            14, Color.TEXT_DIM, bold=True)
        surface.blit(rendered, (FOOTER_RECT.centerx - rendered.get_width() // 2,
                                FOOTER_Y))

    # -- preview ----------------------------------------------------------
    def _draw_preview(self, surface: pygame.Surface, item: ShopItem) -> None:
        """Render the equipped look with the *real* skin code."""
        box = PREVIEW_RECT
        draw_panel(surface, box, accent=RARITY_COLORS[item.rarity], alpha=255)
        fonts = self.ctx.fonts

        if item.category is ShopCategory.BALL:
            self._preview_ball(surface, item.data)
        elif item.category is ShopCategory.PADDLE:
            self._preview_paddle(surface, item.data)
        elif item.category is ShopCategory.BACKGROUND:
            self._preview_background(surface, item.data)
        elif item.category is ShopCategory.TRAIL:
            self._preview_trail(surface, item.data)
        elif item.category is ShopCategory.IMPACT:
            if self._preview_particles is not None:
                buffer = pygame.Surface((box.w, box.h), pygame.SRCALPHA)
                self._preview_particles.draw(buffer)
                surface.blit(buffer, box.topleft)
        elif item.category is ShopCategory.POWERUP:
            spec = item.data
            glyph = fonts.render(spec.glyph, 72, spec.accent, bold=True,
                                 outline=4, outline_color=Color.BG)
            surface.blit(glyph, (box.centerx - glyph.get_width() // 2,
                                 box.y + 34))
            caption = fonts.render(item.name, 15, spec.accent, bold=True)
            surface.blit(caption, (box.centerx - caption.get_width() // 2,
                                   box.bottom - 26))

        # Border drawn last so previews never overhang the card.
        pygame.draw.rect(surface, Color.blend(Color.LINE_SOFT,
                                              RARITY_COLORS[item.rarity], 0.6),
                         box, width=1, border_radius=10)

    def _preview_ball(self, surface: pygame.Surface, look: BallLook) -> None:
        cx, cy = PREVIEW_RECT.center
        draw_ball(surface, cx, cy, 34, look,
                  glow=glow_sprite(look.fill, 76), glow_boost=1.0)

    def _preview_paddle(self, surface: pygame.Surface, look: PaddleLook) -> None:
        cx, cy = PREVIEW_RECT.center
        height = 124
        for offset, team in ((-72, Color.P1), (72, Color.P2)):
            rect = pygame.Rect(cx + offset - 13, cy - height // 2, 26, height)
            draw_paddle(surface, rect, team, look,
                        glow=glow_sprite(team, 74))

    def _preview_background(self, surface: pygame.Surface,
                            look: BackgroundLook) -> None:
        key = f"{look.style.value}:{look.court}"
        cached = self._court_cache.get(key)
        if cached is None:
            scaled = pygame.transform.smoothscale(
                _court_surface(look), (PREVIEW_W, PREVIEW_H))
            self._court_cache[key] = scaled
            cached = scaled
        surface.blit(cached, PREVIEW_RECT.topleft)

    def _preview_trail(self, surface: pygame.Surface, look: TrailLook) -> None:
        cx, cy = PREVIEW_RECT.center
        points: list[list[float]] = []
        for i in range(14):
            t = i / 13.0
            px = PREVIEW_RECT.x + 34 + t * (PREVIEW_RECT.w - 68)
            py = cy + math.sin(t * math.pi * 1.6 - 1.0) * 42.0
            points.append([px, py, 0.25 + t * 0.75])
        draw_trail(surface, points, look, 16.0)


def _court_surface(look: BackgroundLook) -> pygame.Surface:
    """Full-size themed court for the background preview (built on demand)."""
    from .common import render_court
    return render_court(default_court(), look)
