"""Shop catalog invariants.

The catalog is a pure-data module, so it can be checked exhaustively without
booting the game.  These tests are the guard rails for the two ways a catalog
goes wrong at 3am: someone adds an item whose id does not match its category
(the scene then renders a *ball* look in the *powerup* slot and crashes deep
inside :mod:`pongpro.rendering.skins`), and someone deletes or duplicates the
free starter item that every fresh profile equips.
"""

from __future__ import annotations

import unittest

from pongpro.economy.catalog import (
    CATALOG_TOTAL,
    CATEGORIES,
    ITEMS,
    ITEMS_BY_ID,
    RARITY_COLORS,
    BallLook,
    BackgroundLook,
    ImpactLook,
    PaddleLook,
    PowerEffect,
    PowerTarget,
    PowerupSpec,
    Rarity,
    ShopCategory,
    ShopItem,
    TrailLook,
    default_item,
    get_item,
    items_in,
)
from pongpro.economy.wallet import STARTING_COINS

#: Category -> the look/spec type that ``item.data`` must have.  A mismatch
#: here is exactly the crash the shop scene would otherwise hit at draw time.
_DATA_TYPES: dict[ShopCategory, type] = {
    ShopCategory.BALL: BallLook,
    ShopCategory.PADDLE: PaddleLook,
    ShopCategory.BACKGROUND: BackgroundLook,
    ShopCategory.TRAIL: TrailLook,
    ShopCategory.IMPACT: ImpactLook,
    ShopCategory.POWERUP: PowerupSpec,
}

#: Id prefix that belongs to each category (see ``catalog._category_prefixes``).
_PREFIXES: dict[ShopCategory, str] = {
    ShopCategory.BALL: "ball.",
    ShopCategory.PADDLE: "paddle.",
    ShopCategory.BACKGROUND: "bg.",
    ShopCategory.TRAIL: "trail.",
    ShopCategory.IMPACT: "impact.",
    ShopCategory.POWERUP: "pu.",
}


class CatalogShapeTests(unittest.TestCase):
    def test_catalog_is_the_expected_size(self) -> None:
        self.assertEqual(len(ITEMS), len(ITEMS_BY_ID))
        self.assertGreaterEqual(len(ITEMS), 50,
                                "the shop needs a meaningful selection")

    def test_catalog_total_is_the_sum_of_the_prices(self) -> None:
        """``CATALOG_TOTAL`` is the coin cost of buying everything."""
        self.assertEqual(CATALOG_TOTAL, sum(item.price for item in ITEMS))
        self.assertGreater(CATALOG_TOTAL, STARTING_COINS)

    def test_every_category_is_represented(self) -> None:
        for category in CATEGORIES:
            with self.subTest(category=category.value):
                self.assertGreater(len(items_in(category)), 0)

    def test_ids_are_unique(self) -> None:
        self.assertEqual(len(set(ITEMS_BY_ID)), len(ITEMS))
        seen: set[str] = set()
        for item in ITEMS:
            self.assertNotIn(item.id, seen, f"duplicate id {item.id}")
            seen.add(item.id)

    def test_id_prefix_matches_category(self) -> None:
        """A ``ball.*`` id must never be filed under POWERUP, and vice versa."""
        for item in ITEMS:
            with self.subTest(item=item.id):
                self.assertTrue(
                    item.id.startswith(_PREFIXES[item.category]),
                    f"{item.id} is filed under {item.category.value}")

    def test_every_id_is_reachable_through_its_category(self) -> None:
        """``items_in`` must partition the catalog with no gaps or overlap."""
        listed = [item.id for category in CATEGORIES for item in items_in(category)]
        self.assertEqual(sorted(listed), sorted(ITEMS_BY_ID))
        self.assertEqual(len(listed), len(set(listed)),
                          "an item appeared in two categories")

    def test_data_payload_matches_the_category(self) -> None:
        for item in ITEMS:
            with self.subTest(item=item.id):
                self.assertIsInstance(item.data, _DATA_TYPES[item.category])

    def test_items_are_well_formed(self) -> None:
        for item in ITEMS:
            with self.subTest(item=item.id):
                self.assertGreaterEqual(item.price, 0)
                self.assertTrue(item.name.strip(), "blank name")
                self.assertTrue(item.description.strip(), "blank description")
                self.assertIn(item.rarity, RARITY_COLORS,
                              "rarity has no palette entry")

    def test_negative_price_is_rejected_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            ShopItem("x.y", ShopCategory.BALL, "X", -1, Rarity.FREE, "d",
                     BallLook())

    def test_rarity_palette_covers_every_tier(self) -> None:
        self.assertEqual(set(RARITY_COLORS), set(Rarity))
        for rarity, colour in RARITY_COLORS.items():
            with self.subTest(rarity=rarity.value):
                self.assertEqual(len(colour), 3)


class CatalogOrderingTests(unittest.TestCase):
    def test_items_in_is_sorted_by_price(self) -> None:
        """The shop scene renders the page in this order; keep it honest."""
        for category in CATEGORIES:
            with self.subTest(category=category.value):
                prices = [item.price for item in items_in(category)]
                self.assertEqual(prices, sorted(prices),
                                 f"{category.value} rows are not cheapest-first")

    def test_the_free_starter_is_the_first_row(self) -> None:
        for category in CATEGORIES:
            with self.subTest(category=category.value):
                self.assertEqual(items_in(category)[0].price, 0)

    def test_items_in_is_stable(self) -> None:
        first = items_in(ShopCategory.POWERUP)
        second = items_in(ShopCategory.POWERUP)
        self.assertEqual([i.id for i in first], [i.id for i in second])


class DefaultItemTests(unittest.TestCase):
    def test_every_category_has_a_free_default(self) -> None:
        for category in CATEGORIES:
            with self.subTest(category=category.value):
                item = default_item(category)
                self.assertIs(item.category, category)
                self.assertEqual(item.price, 0,
                                 "the starter item must always be affordable")

    def test_default_powerup_is_overdrive_not_the_opt_out(self) -> None:
        """``pu.none`` is free, so a "first free wins" rule would ship a
        profile with the powerup system switched off by default."""
        self.assertEqual(default_item(ShopCategory.POWERUP).id, "pu.overdrive")
        self.assertEqual(get_item("pu.overdrive").data.effect, PowerEffect.SPEED)
        self.assertEqual(get_item("pu.none").data.effect, PowerEffect.NONE)

    def test_default_cosmetics_are_the_classic_skins(self) -> None:
        self.assertEqual(default_item(ShopCategory.BALL).id, "ball.classic")
        self.assertEqual(default_item(ShopCategory.PADDLE).id, "paddle.classic")
        self.assertEqual(default_item(ShopCategory.BACKGROUND).id, "bg.classic")
        self.assertEqual(default_item(ShopCategory.TRAIL).id, "trail.classic")
        self.assertEqual(default_item(ShopCategory.IMPACT).id, "impact.classic")

    def test_the_opt_out_powerup_still_exists_and_is_free(self) -> None:
        item = get_item("pu.none")
        self.assertEqual(item.price, 0)
        self.assertTrue(item.free)


class LookupTests(unittest.TestCase):
    def test_get_item_returns_the_catalog_entry(self) -> None:
        item = get_item("ball.ember")
        self.assertIs(item, ITEMS_BY_ID["ball.ember"])
        self.assertIs(item.category, ShopCategory.BALL)

    def test_get_item_raises_for_unknown_ids(self) -> None:
        with self.assertRaises(KeyError):
            get_item("ball.legendary")
        with self.assertRaises(KeyError):
            get_item("")

    def test_spec_accessor_typed(self) -> None:
        spec = get_item("pu.goldrush").spec
        self.assertEqual(spec.effect, PowerEffect.COINS)
        self.assertEqual(spec.target, PowerTarget.SELF)
        with self.assertRaises(TypeError):
            _ = get_item("ball.classic").spec


class PowerupSpecTests(unittest.TestCase):
    """Every powerup must be safe to run in a match, not just to draw."""

    def test_specs_are_sane(self) -> None:
        for item in items_in(ShopCategory.POWERUP):
            spec = item.spec
            with self.subTest(item=item.id):
                self.assertIn(spec.effect, PowerEffect)
                self.assertIn(spec.target, PowerTarget)
                self.assertGreaterEqual(spec.duration, 0.0)
                self.assertGreaterEqual(spec.cooldown, 0.0)
                self.assertGreaterEqual(spec.coins, 0)
                self.assertTrue(spec.glyph.strip(), "blank HUD glyph")
                self.assertEqual(len(spec.glyph), 2,
                                 f"{item.id}: the HUD pill reserves two glyphs")

    def test_paid_powerups_are_never_free(self) -> None:
        """Only the two starter powerups cost nothing; everything else must be
        a real purchase or the economy has nothing to sell."""
        free = [item.id for item in items_in(ShopCategory.POWERUP)
                if item.price == 0]
        self.assertEqual(sorted(free), ["pu.none", "pu.overdrive"])

    def test_every_effect_kind_is_actually_sold(self) -> None:
        """A PowerEffect with no product behind it is dead code in
        :mod:`pongpro.gameplay.powerups`.

        LIFE is the single deliberate exception: it is FOCUS mode's only
        pickup and is constructed in :mod:`pongpro.gameplay.focus` rather
        than registered here, so that no profile can ever buy, own or equip
        one.  It still needs the enum member because the effect has to be
        recognised when the orb is collected.
        """
        sold = {item.spec.effect for item in items_in(ShopCategory.POWERUP)}
        sold.discard(PowerEffect.NONE)
        unsold = {PowerEffect.LIFE}
        self.assertEqual(sold, {effect for effect in PowerEffect
                                if effect is not PowerEffect.NONE
                                and effect not in unsold})

    def test_every_target_kind_is_actually_sold(self) -> None:
        sold = {item.spec.target for item in items_in(ShopCategory.POWERUP)}
        self.assertEqual(sold, {PowerTarget.SELF, PowerTarget.OPPONENT,
                                PowerTarget.GLOBAL})

    def test_magnitudes_move_the_needle(self) -> None:
        """Every *scaled* powerup must actually scale something.

        Three effects are legitimately on/off rather than proportional:
        SHIELD seals a goal line, MAGNET steers, INVERT flips a control, and
        GOLD RUSH carries its payload in ``coins`` instead of ``magnitude``.
        """
        off_or_scaled_elsewhere = {
            PowerEffect.NONE, PowerEffect.SHIELD, PowerEffect.MAGNET,
            PowerEffect.INVERT, PowerEffect.COINS,
        }
        for item in items_in(ShopCategory.POWERUP):
            spec = item.spec
            if spec.effect in off_or_scaled_elsewhere:
                continue
            with self.subTest(item=item.id):
                self.assertNotEqual(spec.magnitude, 1.0,
                                    f"{item.id} changes nothing when fired")

    def test_coins_powerup_pays_something(self) -> None:
        for item in items_in(ShopCategory.POWERUP):
            if item.spec.effect is PowerEffect.COINS:
                with self.subTest(item=item.id):
                    self.assertGreater(item.spec.coins, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
