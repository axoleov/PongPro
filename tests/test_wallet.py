"""Wallet rules: no partial charges, healing saves, deterministic rewards.

The wallet is the one place where a bug costs the player something real, so
these tests are written as promises rather than as a spec dump:

* a purchase either happens completely or not at all,
* a hand-edited save file can never stop the game booting, and
* the coin award shown on the results screen is the same integer the wallet
  banks, for every mode and difficulty.
"""

from __future__ import annotations

import unittest

from pongpro.core.constants import Difficulty, GameMode
from pongpro.economy.catalog import (
    CATEGORIES,
    ITEMS,
    ShopCategory,
    default_item,
    get_item,
)
from pongpro.economy.wallet import (
    DIFFICULTY_MULTIPLIER,
    HIT_BONUS,
    HIT_STEP,
    PARTICIPATION_BONUS,
    RALLY_BONUS,
    RALLY_CAP,
    RALLY_STEP,
    STARTING_COINS,
    WALLET_CACHE_KEY,
    WALLET_VERSION,
    POINTS_PER_POINT,
    WIN_BONUS,
    Wallet,
    default_wallet,
    get_wallet,
    invalidate_wallet,
    match_reward,
    save_wallet,
)


def _reward(mode: GameMode, winner, difficulty, score, rally=0, hits=0):
    return match_reward(mode=mode, winner=winner, difficulty=difficulty,
                        score=score, longest_rally=rally, total_hits=hits)


class _FakeStorage:
    """Just enough of ``pongpro.storage.Store`` for the ctx helpers."""

    def __init__(self) -> None:
        self.payload: dict | None = None

    def load_wallet(self):  # type: ignore[no-untyped-def]
        return self.payload

    def save_wallet(self, payload):  # type: ignore[no-untyped-def]
        self.payload = payload
        return True


class _FakeCtx:
    def __init__(self) -> None:
        self.storage = _FakeStorage()
        self.extra: dict = {}


class FreshProfileTests(unittest.TestCase):
    def test_starts_with_the_documented_balance(self) -> None:
        wallet = Wallet()
        self.assertEqual(wallet.coins, STARTING_COINS)
        self.assertEqual(wallet.lifetime_earned, STARTING_COINS)
        self.assertEqual(wallet.lifetime_spent, 0)
        self.assertEqual(wallet.purchases, 0)

    def test_owns_every_free_item(self) -> None:
        wallet = Wallet()
        for item in ITEMS:
            if item.free:
                with self.subTest(item=item.id):
                    self.assertTrue(wallet.owns(item.id))
        for item in ITEMS:
            if not item.free:
                with self.subTest(item=item.id):
                    self.assertFalse(wallet.owns(item.id))

    def test_every_category_starts_equipped(self) -> None:
        wallet = Wallet()
        for category in CATEGORIES:
            with self.subTest(category=category.value):
                self.assertEqual(wallet.equipped_id(category),
                                 default_item(category).id)
                self.assertIs(wallet.equipped_item(category).category, category)

    def test_default_wallet_document_matches(self) -> None:
        payload = default_wallet()
        self.assertEqual(payload["version"], WALLET_VERSION)
        self.assertEqual(payload["coins"], STARTING_COINS)
        self.assertEqual(payload["purchases"], 0)
        self.assertEqual(sorted(payload["owned"]),
                         sorted(i.id for i in ITEMS if i.free))
        self.assertEqual(payload["equipped"][ShopCategory.POWERUP.value],
                         "pu.overdrive")
        self.assertEqual(payload["equipped"][ShopCategory.BALL.value],
                         "ball.classic")

    def test_default_document_loads_into_the_same_wallet(self) -> None:
        self.assertEqual(Wallet.from_dict(default_wallet()).to_dict(),
                         Wallet().to_dict())


class HealingTests(unittest.TestCase):
    """A corrupt or hand-edited save must degrade, never raise."""

    def test_non_dict_payloads_become_a_fresh_profile(self) -> None:
        for payload in (None, [], "nope", 42, {"coins": []}):
            with self.subTest(payload=repr(payload)):
                wallet = Wallet.from_dict(payload)  # type: ignore[arg-type]
                self.assertEqual(wallet.coins, STARTING_COINS)
                self.assertTrue(wallet.owns(default_item(
                    ShopCategory.BALL).id))

    def test_missing_fields_fall_back(self) -> None:
        wallet = Wallet.from_dict({})
        self.assertEqual(wallet.coins, STARTING_COINS)
        self.assertEqual(wallet.purchases, 0)
        self.assertEqual(wallet.lifetime_spent, 0)

    def test_unreadable_numbers_fall_back(self) -> None:
        self.assertEqual(Wallet.from_dict({"coins": "lots"}).coins,
                         STARTING_COINS)
        self.assertEqual(Wallet.from_dict({"coins": None}).coins,
                         STARTING_COINS)
        self.assertEqual(Wallet.from_dict({"coins": []}).coins, STARTING_COINS)

    def test_readable_numbers_are_accepted(self) -> None:
        self.assertEqual(Wallet.from_dict({"coins": "250"}).coins, 250)

    def test_negative_balance_is_clamped_to_zero_not_stolen(self) -> None:
        wallet = Wallet.from_dict({"coins": -500})
        self.assertEqual(wallet.coins, 0)
        self.assertFalse(wallet.can_afford(1))

    def test_unknown_owned_ids_are_dropped(self) -> None:
        wallet = Wallet.from_dict({
            "owned": ["ball.crimson", "ball.no_such_thing", 123, None, ""],
        })
        self.assertTrue(wallet.owns("ball.crimson"))
        self.assertFalse(wallet.owns("ball.no_such_thing"))
        self.assertNotIn("", wallet.owned_ids)

    def test_equipped_item_that_is_not_owned_falls_back(self) -> None:
        wallet = Wallet.from_dict({
            "owned": ["ball.crimson"],
            "equipped": {"ball": "ball.ember"},
        })
        self.assertEqual(wallet.equipped_id(ShopCategory.BALL),
                         default_item(ShopCategory.BALL).id)

    def test_equipped_item_from_the_wrong_category_is_rejected(self) -> None:
        wallet = Wallet.from_dict({
            "owned": ["ball.ember"],
            "equipped": {"ball": "ball.ember", "paddle": "ball.ember"},
        })
        self.assertEqual(wallet.equipped_id(ShopCategory.BALL), "ball.ember")
        self.assertEqual(wallet.equipped_id(ShopCategory.PADDLE),
                         default_item(ShopCategory.PADDLE).id)

    def test_equipped_not_a_mapping_falls_back(self) -> None:
        wallet = Wallet.from_dict({"equipped": "ball.ember"})
        for category in CATEGORIES:
            with self.subTest(category=category.value):
                self.assertEqual(wallet.equipped_id(category),
                                 default_item(category).id)

    def test_owned_not_a_list_falls_back_to_the_free_set(self) -> None:
        wallet = Wallet.from_dict({"owned": {"ball.ember": 1}})
        self.assertFalse(wallet.owns("ball.ember"))
        self.assertTrue(wallet.owns("ball.classic"))

    def test_round_trip_preserves_everything(self) -> None:
        wallet = Wallet()
        wallet.award(5000)                    # a rich profile, then spend it
        self.assertTrue(wallet.buy("ball.crimson"))
        self.assertTrue(wallet.buy("pu.magnet"))
        wallet.award(1234)
        restored = Wallet.from_dict(wallet.to_dict())
        self.assertEqual(restored.to_dict(), wallet.to_dict())
        self.assertEqual(restored.coins, wallet.coins)
        self.assertEqual(restored.purchases, 2)
        self.assertTrue(restored.owns("pu.magnet"))


class PurchaseTests(unittest.TestCase):
    def test_buy_debits_and_auto_equips(self) -> None:
        wallet = Wallet()
        item = get_item("ball.crimson")
        self.assertTrue(wallet.buy(item.id))
        self.assertEqual(wallet.coins, STARTING_COINS - item.price)
        self.assertEqual(wallet.lifetime_spent, item.price)
        self.assertEqual(wallet.purchases, 1)
        self.assertTrue(wallet.owns(item.id))
        self.assertEqual(wallet.equipped_id(ShopCategory.BALL), item.id)

    def test_buy_never_partially_charges(self) -> None:
        wallet = Wallet(coins=100)
        before = wallet.coins
        self.assertFalse(wallet.buy("ball.crimson"))  # costs 220
        self.assertEqual(wallet.coins, before)
        self.assertEqual(wallet.purchases, 0)
        self.assertEqual(wallet.lifetime_spent, 0)
        self.assertFalse(wallet.owns("ball.crimson"))
        self.assertEqual(wallet.equipped_id(ShopCategory.BALL),
                         default_item(ShopCategory.BALL).id)

    def test_buying_with_an_exact_balance_is_allowed(self) -> None:
        wallet = Wallet(coins=220)
        self.assertTrue(wallet.buy("ball.crimson"))
        self.assertEqual(wallet.coins, 0)
        self.assertFalse(wallet.can_afford(1))

    def test_buying_an_owned_item_is_a_no_op(self) -> None:
        wallet = Wallet()
        self.assertFalse(wallet.buy("ball.classic"))
        self.assertEqual(wallet.coins, STARTING_COINS)
        self.assertEqual(wallet.purchases, 0)

    def test_buying_an_unknown_item_is_a_no_op(self) -> None:
        wallet = Wallet()
        self.assertFalse(wallet.buy("ball.no_such_thing"))
        self.assertFalse(wallet.buy(""))
        self.assertEqual(wallet.coins, STARTING_COINS)

    def test_free_items_are_owned_not_purchased(self) -> None:
        wallet = Wallet()
        self.assertFalse(wallet.buy("pu.none"))
        self.assertEqual(wallet.purchases, 0)

    def test_equipping_is_separate_from_buying(self) -> None:
        wallet = Wallet()
        wallet.award(1000)
        self.assertFalse(wallet.equip("ball.mint"))     # not owned yet
        self.assertTrue(wallet.buy("ball.mint"))
        self.assertEqual(wallet.equipped_id(ShopCategory.BALL), "ball.mint")
        self.assertTrue(wallet.equip("ball.classic"))   # owned, not equipped
        self.assertEqual(wallet.equipped_id(ShopCategory.BALL), "ball.classic")
        self.assertFalse(wallet.equip("ball.classic"))  # already equipped
        self.assertEqual(wallet.purchases, 1, "equipping must not cost money")
        self.assertEqual(wallet.lifetime_spent, get_item("ball.mint").price)

    def test_award_clamps_negative_amounts(self) -> None:
        wallet = Wallet(coins=100)
        self.assertEqual(wallet.award(50), 50)
        self.assertEqual(wallet.coins, 150)
        self.assertEqual(wallet.lifetime_earned, STARTING_COINS + 50)
        self.assertEqual(wallet.award(-999), 0)
        self.assertEqual(wallet.award(0), 0)
        self.assertEqual(wallet.coins, 150)

    def test_can_afford_boundary(self) -> None:
        wallet = Wallet(coins=220)
        self.assertTrue(wallet.can_afford(220))
        self.assertFalse(wallet.can_afford(221))
        self.assertTrue(wallet.can_afford(0))


class RewardTests(unittest.TestCase):
    def test_pays_for_showing_up(self) -> None:
        self.assertEqual(_reward(GameMode.SOLO, winner=None,
                                 difficulty=Difficulty.NORMAL, score=(0, 0)),
                         PARTICIPATION_BONUS)

    def test_win_bonus_by_mode(self) -> None:
        args = dict(difficulty=None, score=(0, 0))
        paid = PARTICIPATION_BONUS + WIN_BONUS
        # Solo only pays the human; a loss pays nothing extra.
        self.assertEqual(_reward(GameMode.SOLO, 0, **args), paid)
        self.assertEqual(_reward(GameMode.SOLO, 1, **args),
                         PARTICIPATION_BONUS)
        # Local versus always pays: someone on this machine won.
        self.assertEqual(_reward(GameMode.TWO_PLAYER, 0, **args), paid)
        self.assertEqual(_reward(GameMode.TWO_PLAYER, 1, **args), paid)
        # Nobody is playing an AI mirror, so nobody is rewarded.
        self.assertEqual(_reward(GameMode.AI_VS_AI, 0, **args),
                         PARTICIPATION_BONUS)
        self.assertEqual(_reward(GameMode.AI_VS_AI, 1, **args),
                         PARTICIPATION_BONUS)

    def test_no_winner_pays_nothing_extra(self) -> None:
        for mode in GameMode:
            with self.subTest(mode=mode.value):
                self.assertEqual(_reward(mode, None, None, (0, 0)),
                                 PARTICIPATION_BONUS)

    def test_pays_per_point_and_ignores_negative_scores(self) -> None:
        args = dict(mode=GameMode.SOLO, winner=None, difficulty=None)
        self.assertEqual(_reward(score=(7, 0), **args),
                         PARTICIPATION_BONUS + POINTS_PER_POINT * 7)
        self.assertEqual(_reward(score=(3, 4), **args),
                         PARTICIPATION_BONUS + POINTS_PER_POINT * 7)
        self.assertEqual(_reward(score=(-5, 2), **args),
                         PARTICIPATION_BONUS + POINTS_PER_POINT * 2)

    def test_pays_for_rallies_and_caps_them(self) -> None:
        args = dict(mode=GameMode.SOLO, winner=None, difficulty=None,
                    score=(0, 0))
        self.assertEqual(_reward(rally=0, hits=0, **args),
                         PARTICIPATION_BONUS)
        self.assertEqual(_reward(rally=RALLY_STEP, hits=0, **args),
                         PARTICIPATION_BONUS + RALLY_BONUS)
        self.assertEqual(_reward(rally=RALLY_STEP - 1, hits=0, **args),
                         PARTICIPATION_BONUS)
        capped = _reward(rally=RALLY_CAP, hits=0, **args)
        self.assertEqual(capped, PARTICIPATION_BONUS
                         + (RALLY_CAP // RALLY_STEP) * RALLY_BONUS)
        self.assertEqual(_reward(rally=10_000, hits=0, **args), capped)

    def test_pays_for_returns(self) -> None:
        args = dict(mode=GameMode.SOLO, winner=None, difficulty=None,
                    score=(0, 0), rally=0)
        self.assertEqual(_reward(hits=HIT_STEP - 1, **args),
                         PARTICIPATION_BONUS)
        self.assertEqual(_reward(hits=HIT_STEP * 3, **args),
                         PARTICIPATION_BONUS + HIT_BONUS * 3)

    def test_solo_difficulty_scales_the_whole_award(self) -> None:
        common = dict(mode=GameMode.SOLO, winner=0, score=(0, 0))
        normal = _reward(difficulty=Difficulty.NORMAL, **common)
        self.assertEqual(normal, PARTICIPATION_BONUS + WIN_BONUS)
        self.assertEqual(_reward(difficulty=Difficulty.EASY, **common),
                         round(normal * DIFFICULTY_MULTIPLIER[Difficulty.EASY]))
        self.assertEqual(_reward(difficulty=Difficulty.HARD, **common),
                         round(normal * DIFFICULTY_MULTIPLIER[Difficulty.HARD]))
        elite = _reward(difficulty=Difficulty.ELITE, **common)
        self.assertGreater(elite, _reward(difficulty=Difficulty.HARD, **common))

    def test_other_modes_ignore_difficulty(self) -> None:
        """Difficulty is meaningless for a local versus or a spectated game."""
        for mode in (GameMode.TWO_PLAYER, GameMode.AI_VS_AI):
            with self.subTest(mode=mode.value):
                values = {_reward(mode, 0, d, (0, 0))
                          for d in (*Difficulty, None)}
                self.assertEqual(len(values), 1, "difficulty leaked into mode")

    def test_composite_case(self) -> None:
        """One end-to-end figure, arithmetically spelled out."""
        award = (PARTICIPATION_BONUS + POINTS_PER_POINT * 8
                 + (10 // RALLY_STEP) * RALLY_BONUS
                 + (24 // HIT_STEP) * HIT_BONUS
                 + WIN_BONUS)
        self.assertEqual(
            _reward(GameMode.SOLO, 0, Difficulty.HARD, (5, 3),
                    rally=10, hits=24),
            round(award * DIFFICULTY_MULTIPLIER[Difficulty.HARD]))

    def test_reward_is_pure(self) -> None:
        kwargs = dict(mode=GameMode.SOLO, winner=0, difficulty=Difficulty.ELITE,
                      score=(9, 7), rally=42, hits=77)
        self.assertEqual(_reward(**kwargs), _reward(**kwargs))

    def test_reward_is_always_at_least_one_coin(self) -> None:
        for mode in GameMode:
            for difficulty in (*Difficulty, None):
                with self.subTest(mode=mode.value, difficulty=difficulty):
                    self.assertGreaterEqual(
                        _reward(mode, None, difficulty, (0, 0)), 1)


class ContextTests(unittest.TestCase):
    """The scene-facing helpers: one wallet object per application, always."""

    def test_get_wallet_caches_on_the_context(self) -> None:
        ctx = _FakeCtx()
        first = get_wallet(ctx)
        self.assertIs(get_wallet(ctx), first)
        self.assertIs(ctx.extra[WALLET_CACHE_KEY], first)
        invalidate_wallet(ctx)
        self.assertNotIn(WALLET_CACHE_KEY, ctx.extra)
        self.assertIsNot(get_wallet(ctx), first)

    def test_save_wallet_persists_and_reloads(self) -> None:
        ctx = _FakeCtx()
        wallet = get_wallet(ctx)
        self.assertTrue(wallet.buy("ball.crimson"))
        self.assertTrue(save_wallet(ctx))
        self.assertIsNotNone(ctx.storage.payload)
        self.assertEqual(ctx.storage.payload["coins"], wallet.coins)
        self.assertIn("ball.crimson", ctx.storage.payload["owned"])

        invalidate_wallet(ctx)
        reloaded = get_wallet(ctx)
        self.assertEqual(reloaded.coins, wallet.coins)
        self.assertTrue(reloaded.owns("ball.crimson"))

    def test_save_wallet_accepts_an_explicit_wallet(self) -> None:
        ctx = _FakeCtx()
        other = Wallet(coins=7)
        self.assertTrue(save_wallet(ctx, other))
        self.assertIs(ctx.extra[WALLET_CACHE_KEY], other)
        self.assertEqual(get_wallet(ctx).coins, 7)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
