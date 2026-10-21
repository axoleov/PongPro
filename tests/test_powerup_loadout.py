"""Loadout selection and bubble grants: the two new powerup mechanisms.

Two things are pinned down here.

**Selection** - :func:`pongpro.gameplay.powerups.choose_powerup` is what a bot
uses in 1P-vs-AI and what *both* bots use in AI-vs-AI.  It draws from the
profile's own collection, it never hands out the empty ``pu.none`` slot, and
it is deliberately independent of what the profile has equipped so the machine
does not simply mirror the human.

**Grants** - :meth:`pongpro.gameplay.powerups.PowerupSystem.grant` is how a
mid-match bubble pays out.  A grant starts running immediately for its own
duration but must never disturb the powerup that paddle is holding, or
grabbing a pickup would cost a player their special move.  It also must not
stack: one effect of a given kind per paddle, so every scale stays bounded.

The tests step time in the game's own 120 Hz fixed step and allow a little
slack on expiries - subtracting ``1/120`` repeatedly cannot land on exactly
zero in IEEE-754, so demanding an exact ``0.0`` would be testing floating
point rather than the game.
"""

from __future__ import annotations

import unittest

from pongpro.core.rng import Rng
from pongpro.economy.catalog import PowerEffect, PowerTarget, ShopCategory, get_item
from pongpro.economy.wallet import Wallet
from pongpro.gameplay.powerups import (
    AI_CONFUSE_STRENGTH,
    BLANK_SPEC,
    Disoriented,
    PowerupSystem,
    choose_powerup,
    owned_powerups,
)

STEP = 1.0 / 120.0
BOUGHT = ("pu.giant", "pu.magnet", "pu.fireball")


def _wallet(with_purchases: bool = True) -> Wallet:
    wallet = Wallet(coins=100_000)
    if with_purchases:
        for item_id in BOUGHT:
            assert wallet.buy(item_id), item_id
    return wallet


def _system(held: str = "pu.fireball") -> PowerupSystem:
    spec = get_item(held).data
    system = PowerupSystem(spec)
    system.set_held(0, spec, get_item(held).name)
    system.set_held(1, spec, get_item(held).name)
    return system


class _BrokeWallet:
    """A profile with nothing at all - the degenerate empty-pool case."""

    def owned_in(self, category: ShopCategory) -> tuple:
        return ()


# ---------------------------------------------------------------------------
# pool construction
# ---------------------------------------------------------------------------
class PoolTests(unittest.TestCase):
    """Which powerups are eligible for a bot or a bubble."""

    def test_no_powerup_is_never_in_the_pool(self) -> None:
        self.assertNotIn("pu.none", {i.id for i in owned_powerups(Wallet())})

    def test_the_free_default_always_keeps_the_pool_alive(self) -> None:
        """A brand-new profile must still have something to play."""
        pool = {i.id for i in owned_powerups(Wallet())}
        self.assertIn("pu.overdrive", pool)
        self.assertTrue(pool)

    def test_purchases_enlarge_the_pool(self) -> None:
        before = {i.id for i in owned_powerups(Wallet())}
        after = {i.id for i in owned_powerups(_wallet())}
        self.assertLess(before, after)
        for item_id in BOUGHT:
            self.assertIn(item_id, after)

    def test_only_powerup_items_are_returned(self) -> None:
        for item in owned_powerups(_wallet()):
            self.assertEqual(item.category, ShopCategory.POWERUP)
            self.assertIsNot(item.data.effect, PowerEffect.NONE)

    def test_equipping_no_powerup_does_not_reintroduce_it(self) -> None:
        wallet = Wallet()
        self.assertTrue(wallet.equip("pu.none"))
        self.assertEqual(wallet.equipped_id(ShopCategory.POWERUP), "pu.none")
        self.assertNotIn("pu.none", {i.id for i in owned_powerups(wallet)})


# ---------------------------------------------------------------------------
# random selection
# ---------------------------------------------------------------------------
class ChoosePowerupTests(unittest.TestCase):
    """The bot's draw: random, owned, and not a copy of the human's."""

    def test_never_returns_no_powerup(self) -> None:
        rng = Rng(1)
        for _ in range(60):
            drawn = choose_powerup(_wallet(), rng)
            self.assertNotEqual(drawn.id, "pu.none")
            self.assertIsNot(drawn.data.effect, PowerEffect.NONE)

    def test_returns_only_owned_powerups(self) -> None:
        owned = {i.id for i in owned_powerups(_wallet())}
        rng = Rng(7)
        for _ in range(60):
            self.assertIn(choose_powerup(_wallet(), rng).id, owned)

    def test_the_draw_is_actually_random(self) -> None:
        """A pool of four that always yields the same item is not a draw."""
        rng = Rng(11)
        picks = {choose_powerup(_wallet(), rng).id for _ in range(80)}
        self.assertGreater(len(picks), 1)

    def test_is_not_tied_to_the_equipped_powerup(self) -> None:
        """The whole point: the bot should not just echo the player."""
        wallet = _wallet()  # buy() auto-equips, and fireball was bought last
        self.assertEqual(wallet.equipped_id(ShopCategory.POWERUP),
                         "pu.fireball")
        rng = Rng(23)
        picks = {choose_powerup(wallet, rng).id for _ in range(80)}
        self.assertNotEqual(picks, {"pu.fireball"})
        self.assertGreater(len(picks), 1)

    def test_it_can_still_coincide_with_the_player(self) -> None:
        """Randomness, not a rule: the equipped item stays in the pool."""
        wallet = _wallet()
        rng = Rng(5)
        self.assertIn("pu.fireball", {choose_powerup(wallet, rng).id
                                      for _ in range(80)})

    def test_is_reproducible_for_a_seed(self) -> None:
        a, b = Rng(42), Rng(42)
        self.assertEqual([choose_powerup(_wallet(), a).id for _ in range(20)],
                         [choose_powerup(_wallet(), b).id for _ in range(20)])

    def test_new_profiles_get_a_usable_powerup(self) -> None:
        rng = Rng(3)
        for _ in range(30):
            drawn = choose_powerup(Wallet(), rng)
            self.assertNotEqual(drawn.id, "pu.none")
            self.assertIn(drawn.data.effect,
                          {PowerEffect.SPEED, PowerEffect.HEIGHT,
                           PowerEffect.MAGNET, PowerEffect.RETURN_SPEED,
                           PowerEffect.SHIELD, PowerEffect.COINS,
                           PowerEffect.INVERT, PowerEffect.SLOW_BALL})

    def test_an_empty_pool_falls_back_to_no_powerup(self) -> None:
        """The guard only fires if a profile somehow owns nothing."""
        self.assertEqual(choose_powerup(_BrokeWallet(), Rng(1)).id,
                         "pu.none")


# ---------------------------------------------------------------------------
# per-paddle holding
# ---------------------------------------------------------------------------
class PerPaddleHeldTests(unittest.TestCase):
    """The change that makes bot-vs-player loadouts possible at all."""

    def test_each_paddle_can_hold_a_different_powerup(self) -> None:
        system = PowerupSystem()
        system.set_held(0, get_item("pu.giant").data, "GIANT PADDLE")
        system.set_held(1, get_item("pu.freezeray").data, "FREEZE RAY")

        self.assertEqual(system.held_spec(0).effect, PowerEffect.HEIGHT)
        self.assertEqual(system.held_spec(1).effect, PowerEffect.SPEED)
        self.assertEqual(system.held_name(0), "GIANT PADDLE")
        self.assertEqual(system.held_name(1), "FREEZE RAY")

    def test_modifiers_only_touch_their_own_paddle(self) -> None:
        system = PowerupSystem()
        system.set_held(0, get_item("pu.giant").data, "GIANT PADDLE")
        system.set_held(1, get_item("pu.freezeray").data, "FREEZE RAY")
        self.assertTrue(system.trigger(0))
        self.assertTrue(system.trigger(1))

        self.assertEqual(system.height_scale(0), 1.55)
        self.assertEqual(system.height_scale(1), 1.0)
        # FREEZE RAY is opponent-targeted: it reaches the *other* paddle.
        self.assertEqual(system.speed_scale(0), 0.5)
        self.assertEqual(system.speed_scale(1), 1.0)

    def test_cooldowns_are_independent(self) -> None:
        system = PowerupSystem()
        system.set_held(0, get_item("pu.giant").data, "GIANT PADDLE")
        system.set_held(1, get_item("pu.giant").data, "GIANT PADDLE")
        self.assertTrue(system.trigger(0))
        self.assertFalse(system.ready(0))
        self.assertTrue(system.ready(1))

    def test_reholding_a_powerup_recharges_it(self) -> None:
        system = _system()
        self.assertTrue(system.trigger(0))
        self.assertFalse(system.ready(0))
        system.set_held(0, get_item("pu.magnet").data, "MAGNET")
        self.assertTrue(system.ready(0))
        self.assertEqual(system.cooldown_left(0), 0.0)
        self.assertEqual(system.held_spec(0).effect, PowerEffect.MAGNET)

    def test_a_blank_paddle_cannot_fire(self) -> None:
        system = PowerupSystem(get_item("pu.none").data)
        self.assertFalse(system.ready(0))
        self.assertFalse(system.trigger(0))
        self.assertFalse(system.enabled)


# ---------------------------------------------------------------------------
# grants (how a bubble pays out)
# ---------------------------------------------------------------------------
class GrantTests(unittest.TestCase):
    """A grant runs on its own, without borrowing the held powerup."""

    def test_grant_rejects_a_spec_that_does_nothing(self) -> None:
        system = _system()
        self.assertFalse(system.grant(0, get_item("pu.none").data, "NO POWERUP"))
        self.assertEqual(system.active_grants(0), ())

    def test_grant_reports_spec_remaining_and_name(self) -> None:
        system = _system()
        self.assertTrue(system.grant(0, get_item("pu.giant").data, "GIANT PADDLE"))
        spec, left, name = system.active_grant(0)  # type: ignore[misc]
        self.assertIs(spec, get_item("pu.giant").data)
        self.assertEqual(name, "GIANT PADDLE")
        self.assertAlmostEqual(left, spec.duration, places=3)

    def test_grant_expires_on_its_own_duration(self) -> None:
        system = _system()
        spec = get_item("pu.giant").data
        self.assertTrue(system.grant(0, spec, "GIANT PADDLE"))
        for _ in range(int(spec.duration / STEP)):
            system.tick(STEP)
        # Float residue: one more heartbeat settles it.
        system.tick(STEP * 4)
        self.assertEqual(system.active_grants(0), ())
        self.assertIsNone(system.active_grant(0))
        self.assertEqual(system.height_scale(0), 1.0)

    def test_grant_leaves_the_held_powerup_untouched(self) -> None:
        system = _system("pu.fireball")
        held = system.held_spec(0)
        self.assertTrue(system.grant(0, get_item("pu.giant").data, "GIANT PADDLE"))

        self.assertIs(system.held_spec(0), held)
        self.assertEqual(system.held_name(0), "FIRE BALL")
        self.assertTrue(system.ready(0))
        self.assertEqual(system.cooldown_left(0), 0.0)

    def test_the_held_powerup_still_fires_while_a_grant_runs(self) -> None:
        system = _system("pu.fireball")
        self.assertTrue(system.grant(0, get_item("pu.giant").data, "GIANT PADDLE"))
        self.assertTrue(system.trigger(0))
        self.assertEqual(system.active_for(0),
                         get_item("pu.fireball").data.duration)
        # Both are live at once - they are different kinds, so they compose.
        self.assertEqual(system.height_scale(0), 1.55)
        self.assertEqual(system.return_speed_scale(0), 1.45)

    def test_the_held_powerup_comes_back_when_the_grant_ends(self) -> None:
        system = _system("pu.fireball")
        self.assertTrue(system.grant(0, get_item("pu.giant").data, "GIANT PADDLE"))
        spec = get_item("pu.giant").data
        for _ in range(int(spec.duration / STEP) + 8):
            system.tick(STEP)
        self.assertEqual(system.active_spec(0), get_item("pu.fireball").data)

    def test_grant_replaces_a_grant_of_the_same_kind(self) -> None:
        """Two GIANT PADDLEs must not multiply into 2.4x."""
        system = _system()
        self.assertTrue(system.grant(0, get_item("pu.giant").data, "GIANT PADDLE"))
        self.assertTrue(system.grant(0, get_item("pu.shrinkray").data, "SHRINK RAY"))
        self.assertEqual(len(system.active_grants(0)), 1)
        # The newer one wins: SHRINK RAY strikes the opponent, not the holder.
        self.assertEqual(system.height_scale(0), 1.0)
        self.assertEqual(system.height_scale(1), 0.6)

    def test_regranting_the_same_spec_does_not_stack(self) -> None:
        system = _system()
        spec = get_item("pu.giant").data
        self.assertTrue(system.grant(0, spec, "GIANT PADDLE"))
        self.assertTrue(system.grant(0, spec, "GIANT PADDLE"))
        self.assertEqual(len(system.active_grants(0)), 1)
        self.assertEqual(system.height_scale(0), 1.55)
        self.assertLessEqual(system.active_spec(0).duration, spec.duration)

    def test_grants_of_different_kinds_coexist(self) -> None:
        system = _system()
        self.assertTrue(system.grant(0, get_item("pu.giant").data, "GIANT PADDLE"))
        self.assertTrue(system.grant(0, get_item("pu.shield").data, "SHIELD"))
        self.assertEqual(len(system.active_grants(0)), 2)
        self.assertEqual(system.height_scale(0), 1.55)
        self.assertTrue(system.shielded(0))
        self.assertFalse(system.shielded(1))

    def test_a_grant_outranks_the_held_powerup_of_the_same_kind(self) -> None:
        system = PowerupSystem(get_item("pu.overdrive").data)  # SPEED, SELF
        system.set_held(0, get_item("pu.overdrive").data, "OVERDRIVE")
        system.set_held(1, get_item("pu.overdrive").data, "OVERDRIVE")
        self.assertTrue(system.grant(0, get_item("pu.freezeray").data, "FREEZE RAY"))

        # FREEZE RAY is the newer of the two SPEED effects, so it is what the
        # opponent feels - not the holder's own OVERDRIVE.
        self.assertEqual(system.speed_scale(1), 0.5)
        self.assertEqual(system.speed_scale(0), 1.0)

    def test_grant_is_scoped_to_one_paddle(self) -> None:
        system = PowerupSystem(get_item("pu.none").data)
        self.assertTrue(system.grant(1, get_item("pu.giant").data, "GIANT PADDLE"))
        self.assertEqual(system.height_scale(0), 1.0)
        self.assertEqual(system.height_scale(1), 1.55)
        self.assertEqual(system.active_grants(0), ())

    def test_global_effects_reach_the_whole_court(self) -> None:
        system = PowerupSystem(get_item("pu.none").data)
        self.assertFalse(system.slow_ball())
        self.assertEqual(system.ball_speed_scale(), 1.0)

        self.assertTrue(system.grant(1, get_item("pu.slowball").data, "SLOW FIELD"))
        self.assertTrue(system.slow_ball())
        self.assertEqual(system.ball_speed_scale(), 0.65)

    def test_a_grant_can_wake_up_an_otherwise_disabled_system(self) -> None:
        system = PowerupSystem(get_item("pu.none").data)
        self.assertFalse(system.enabled)
        self.assertTrue(system.grant(0, get_item("pu.goldrush").data, "GOLD RUSH"))
        self.assertTrue(system.enabled)
        # ... but it still cannot be *fired*: nothing is held.
        self.assertFalse(system.ready(0))
        self.assertEqual(system.coins_per_hit(0), 4)
        self.assertEqual(system.coins_per_hit(1), 0)

    def test_clear_drops_every_grant(self) -> None:
        system = _system("pu.giant")
        self.assertTrue(system.trigger(0))
        self.assertTrue(system.grant(0, get_item("pu.shield").data, "SHIELD"))
        system.clear()
        self.assertEqual(system.active_grants(0), ())
        self.assertFalse(system.is_active(0))
        self.assertEqual(system.cooldown_left(0), 0.0)

    def test_hud_shows_the_running_grant_then_the_held_powerup(self) -> None:
        system = _system("pu.fireball")
        self.assertEqual(system.active_spec(0), get_item("pu.fireball").data)
        self.assertTrue(system.grant(0, get_item("pu.giant").data, "GIANT PADDLE"))
        self.assertEqual(system.active_spec(0), get_item("pu.giant").data)
        for _ in range(int(get_item("pu.giant").data.duration / STEP) + 8):
            system.tick(STEP)
        self.assertEqual(system.active_spec(0), get_item("pu.fireball").data)

    def test_blank_spec_is_never_grantable_or_actually_blank(self) -> None:
        """The sentinel must stay inert or it could leak into a modifier."""
        self.assertIs(BLANK_SPEC.effect, PowerEffect.NONE)
        self.assertIs(BLANK_SPEC.target, PowerTarget.SELF)
        system = PowerupSystem()
        self.assertFalse(system.grant(0, BLANK_SPEC))
        self.assertEqual(system.active_spec(0), BLANK_SPEC)


# ---------------------------------------------------------------------------
# scene-level assignment
# ---------------------------------------------------------------------------
class _StubAudio:
    def __init__(self) -> None:
        self.played: list[str] = []

    def play(self, name: str, volume: float = 1.0, **_kw) -> None:  # type: ignore[no-untyped-def]
        self.played.append(name)


class _StubCtx:
    def __init__(self) -> None:
        self.audio = _StubAudio()


#: Stands in for a real AIController; these tests only care whether a side is
#: bot-driven, never how it predicts.
_FAKE_AI = object()


def _scene(mode, seed: int = 7, wallet: Wallet | None = None,  # type: ignore[no-untyped-def]
           ai: tuple[bool, bool] = (False, False)):
    """Build a GameplayScene without entering it, then assign a loadout.

    ``on_enter`` would touch the real profile on disk, and these tests exist
    precisely to avoid doing that; ``_assign_powerups`` only needs the wallet,
    the mode and the seeded RNG, all of which the constructor provides.

    ``ai`` fakes which sides are bot-driven.  It has to be faked because
    ``on_enter`` is what normally creates the controllers, and several
    behaviours (powerup key hints, REVERSER disorientation) branch on who is
    actually holding the paddle.
    """
    from pongpro.core.constants import Difficulty
    from pongpro.scenes.gameplay import GameplayScene

    scene = GameplayScene(mode=mode, difficulty=Difficulty.NORMAL,
                          target_score=5, seed=seed)
    scene.wallet = wallet if wallet is not None else _wallet()
    scene.ctx = _StubCtx()
    if ai[0]:
        scene.ai_left = _FAKE_AI
    if ai[1]:
        scene.ai_right = _FAKE_AI
    scene._assign_powerups()
    return scene


class ModeLoadoutTests(unittest.TestCase):
    """Which powerup each paddle holds depends on who is actually driving it."""

    def test_solo_gives_the_human_the_equipped_powerup(self) -> None:
        from pongpro.core.constants import GameMode
        scene = _scene(GameMode.SOLO)
        equipped = scene.wallet.equipped_item(ShopCategory.POWERUP)
        self.assertIs(scene.powerups.held_spec(0), equipped.data)
        self.assertEqual(scene.powerup_names[0], equipped.name)

    def test_solo_gives_the_bot_a_random_owned_powerup(self) -> None:
        from pongpro.core.constants import GameMode
        scene = _scene(GameMode.SOLO)
        pool = {i.id for i in owned_powerups(scene.wallet)}
        self.assertIn(scene.powerups.held_spec(1),  # type: ignore[arg-type]
                      {i.data for i in owned_powerups(scene.wallet)})
        self.assertIn(scene.powerup_names[1],
                      {i.name for i in owned_powerups(scene.wallet)})
        self.assertGreater(len(pool), 1)

    def test_solo_does_not_just_copy_the_player(self) -> None:
        """The bot must draw, not mirror - only coincidence may match."""
        from pongpro.core.constants import GameMode
        seen: set[str] = set()
        for seed in range(30):
            scene = _scene(GameMode.SOLO, seed=seed)
            seen.add(scene.powerup_names[1])
        self.assertGreater(len(seen), 1)

    def test_solo_human_loadout_is_stable_across_seeds(self) -> None:
        from pongpro.core.constants import GameMode
        equipped = _wallet().equipped_item(ShopCategory.POWERUP)
        for seed in range(10):
            scene = _scene(GameMode.SOLO, seed=seed)
            self.assertIs(scene.powerups.held_spec(0), equipped.data)

    def test_ai_vs_ai_gives_both_bots_a_random_draw(self) -> None:
        from pongpro.core.constants import GameMode
        pairs = set()
        for seed in range(30):
            scene = _scene(GameMode.AI_VS_AI, seed=seed)
            pairs.add((scene.powerup_names[0], scene.powerup_names[1]))
        self.assertGreater(len(pairs), 1)
        self.assertGreater(len({p[0] for p in pairs}), 1)
        self.assertGreater(len({p[1] for p in pairs}), 1)

    def test_ai_vs_ai_draws_come_only_from_the_owned_pool(self) -> None:
        from pongpro.core.constants import GameMode
        pool = {i.data for i in owned_powerups(_wallet())}
        names = {i.name for i in owned_powerups(_wallet())}
        for seed in range(20):
            scene = _scene(GameMode.AI_VS_AI, seed=seed)
            for player in (0, 1):
                self.assertIn(scene.powerups.held_spec(player), pool)
                self.assertIn(scene.powerup_names[player], names)
                self.assertNotEqual(scene.powerup_names[player], "NO POWERUP")

    def test_two_player_keeps_the_shared_equipped_duel(self) -> None:
        from pongpro.core.constants import GameMode
        scene = _scene(GameMode.TWO_PLAYER, seed=99)
        equipped = scene.wallet.equipped_item(ShopCategory.POWERUP)
        self.assertIs(scene.powerups.held_spec(0), equipped.data)
        self.assertIs(scene.powerups.held_spec(1), equipped.data)
        self.assertEqual(scene.powerup_names, [equipped.name, equipped.name])

    def test_a_new_profile_still_gets_a_fireable_powerup(self) -> None:
        """Every duel mode hands a fresh profile something it can fire.

        FOCUS is excluded because it has no powerups at all: a timed modifier
        is a decision about which *player* it helps, and there is only one
        player.  ``test_focus_holds_no_powerup_at_all`` covers it instead.
        """
        from pongpro.core.constants import GameMode
        for mode in GameMode:
            if mode is GameMode.FOCUS:
                continue
            with self.subTest(mode=mode):
                scene = _scene(mode, seed=3, wallet=Wallet())
                for player in (0, 1):
                    self.assertIsNot(scene.powerups.held_spec(player).effect,
                                     PowerEffect.NONE)

    def test_the_selection_is_reproducible_for_a_seed(self) -> None:
        from pongpro.core.constants import GameMode
        for mode in GameMode:
            with self.subTest(mode=mode):
                a = _scene(mode, seed=41)
                b = _scene(mode, seed=41)
                self.assertEqual(a.powerup_names, b.powerup_names)

    def test_bubbles_are_seeded_from_the_same_collection(self) -> None:
        from pongpro.core.constants import GameMode
        scene = _scene(GameMode.SOLO)
        self.assertIsNotNone(scene.bubbles)
        assert scene.bubbles is not None
        self.assertTrue(scene.bubbles.armed)
        self.assertIsNone(scene.bubbles.bubble)

        from pongpro.gameplay.bubbles import FIRST_SPAWN_DELAY
        scene.bubbles.update(FIRST_SPAWN_DELAY + 1.0 / 60.0, playing=True)
        self.assertIsNotNone(scene.bubbles.bubble)
        assert scene.bubbles.bubble is not None
        pool = {i.data for i in owned_powerups(scene.wallet)}
        self.assertIn(scene.bubbles.bubble.item.data, pool)


class BubbleHandoffTests(unittest.TestCase):
    """The scene turns a ball/bubble overlap into a grant on the right side."""

    def _live_bubble(self, scene):  # type: ignore[no-untyped-def]
        from pongpro.gameplay.bubbles import FIRST_SPAWN_DELAY
        assert scene.bubbles is not None
        scene.bubbles.update(FIRST_SPAWN_DELAY + 1.0 / 60.0, playing=True)
        bubble = scene.bubbles.bubble
        assert bubble is not None
        scene.ball.active = True
        scene.ball.x, scene.ball.y = bubble.x, bubble.y
        return bubble

    def test_the_returning_side_collects(self) -> None:
        from pongpro.core.constants import GameMode
        scene = _scene(GameMode.SOLO, seed=5)
        bubble = self._live_bubble(scene)
        scene._last_paddle = 1
        scene._collect_bubble()

        self.assertIsNone(scene.bubbles.bubble)  # type: ignore[union-attr]
        grant = scene.powerups.active_grant(1)
        self.assertIsNotNone(grant)
        assert grant is not None
        self.assertIs(grant[0], bubble.item.data)
        self.assertEqual(grant[2], bubble.item.name)
        # The other side gets nothing.
        self.assertIsNone(scene.powerups.active_grant(0))
        # And the collector keeps the move it was holding.
        self.assertEqual(scene.powerup_names[1],
                         scene.powerups.held_name(1))
        self.assertIn("go", scene.ctx.audio.played)

    def test_a_ball_that_was_never_returned_collects_nothing(self) -> None:
        from pongpro.core.constants import GameMode
        scene = _scene(GameMode.SOLO, seed=6)
        self._live_bubble(scene)
        scene._last_paddle = None
        scene._collect_bubble()
        self.assertIsNotNone(scene.bubbles.bubble)  # type: ignore[union-attr]
        self.assertIsNone(scene.powerups.active_grant(0))
        self.assertIsNone(scene.powerups.active_grant(1))

    def test_a_serve_cannot_claim_a_pickup(self) -> None:
        from pongpro.core.constants import GameMode
        scene = _scene(GameMode.SOLO, seed=8)
        self._live_bubble(scene)
        scene._last_paddle = 1
        scene._launch_ball()
        self.assertIsNone(scene._last_paddle)
        scene._collect_bubble()
        self.assertIsNotNone(scene.bubbles.bubble)  # type: ignore[union-attr]
        self.assertIsNone(scene.powerups.active_grant(1))

    def test_a_grant_does_not_displace_the_held_powerup(self) -> None:
        from pongpro.core.constants import GameMode
        scene = _scene(GameMode.SOLO, seed=12)
        held_before = scene.powerups.held_spec(1)
        held_name_before = scene.powerups.held_name(1)
        self._live_bubble(scene)
        scene._last_paddle = 1
        scene._collect_bubble()

        self.assertIs(scene.powerups.held_spec(1), held_before)
        self.assertEqual(scene.powerups.held_name(1), held_name_before)
        self.assertTrue(scene.powerups.ready(1))

    def test_the_bubble_becomes_actionable_immediately(self) -> None:
        from pongpro.core.constants import GameMode
        scene = _scene(GameMode.SOLO, seed=15)
        self._live_bubble(scene)
        scene._last_paddle = 0
        scene._collect_bubble()
        grant = scene.powerups.active_grant(0)
        self.assertIsNotNone(grant)
        assert grant is not None
        self.assertAlmostEqual(grant[1], grant[0].duration, places=3)
        # The effect is already reaching the paddle modifiers.
        if grant[0].effect is PowerEffect.HEIGHT:
            self.assertNotEqual(scene.powerups.height_scale(0), 1.0)
        elif grant[0].effect is PowerEffect.SPEED:
            self.assertNotEqual(scene.powerups.speed_scale(0), 1.0)


# ---------------------------------------------------------------------------
# REVERSER disorientation
# ---------------------------------------------------------------------------
class DisorientationTests(unittest.TestCase):
    """A bot mis-reads its controls; it is never simply mirror-flipped."""

    def _run(self, seed: int, seconds: float, active: bool = True) -> list[float]:
        disoriented = Disoriented(Rng(seed))
        return [disoriented.step(STEP, active)
                for _ in range(int(round(seconds / STEP)))]

    def test_it_is_neutral_while_the_effect_is_off(self) -> None:
        disoriented = Disoriented(Rng(3))
        for _ in range(200):
            self.assertEqual(disoriented.step(STEP, False), 1.0)
            self.assertEqual(disoriented.gain, 1.0)

    def test_the_very_first_step_is_the_shock(self) -> None:
        """Controls flip: the bot is disoriented on the very next step."""
        disoriented = Disoriented(Rng(5))
        self.assertEqual(disoriented.step(STEP, True), -AI_CONFUSE_STRENGTH)
        self.assertEqual(disoriented.gain, -AI_CONFUSE_STRENGTH)

    def test_it_is_never_a_perfect_mirror(self) -> None:
        """A full negation would make the paddle a guaranteed free point."""
        gains = self._run(7, 120.0)
        self.assertNotIn(-1.0, gains)
        for gain in gains:
            self.assertGreaterEqual(gain, -AI_CONFUSE_STRENGTH)
            self.assertLessEqual(gain, 1.0)

    def test_it_holds_each_reading_between_re_reads(self) -> None:
        """Disorientation comes in bursts, not as a per-step coin flip."""
        gains = self._run(4, 2.0)
        changes = sum(1 for a, b in zip(gains, gains[1:]) if a != b)
        # At most one re-read every 0.28 s, so at most ~8 in a 2 s window.
        self.assertLessEqual(changes, 10)

    def test_it_is_not_one_constant_reading(self) -> None:
        gains = self._run(4, 60.0)
        self.assertIn(-AI_CONFUSE_STRENGTH, gains)
        self.assertIn(1.0, gains)

    def test_mostly_wrong_but_not_always(self) -> None:
        """The hit rate should collapse - not vanish outright."""
        gains = self._run(11, 60.0)
        mean = sum(gains) / len(gains)
        self.assertLess(mean, 0.0)                    # net drift is wrong-way
        self.assertGreater(mean, -AI_CONFUSE_STRENGTH)  # and never total
        self.assertGreater(sum(1 for g in gains if g > 0.0), 0)

    def test_it_snaps_back_when_the_effect_ends(self) -> None:
        disoriented = Disoriented(Rng(9))
        disoriented.step(STEP, True)
        self.assertEqual(disoriented.step(STEP * 60, False), 1.0)
        self.assertEqual(disoriented.gain, 1.0)
        # The next flip shocks it again, rather than resuming the old state.
        self.assertEqual(disoriented.step(STEP, True), -AI_CONFUSE_STRENGTH)

    def test_deterministic_for_a_seed(self) -> None:
        self.assertEqual(self._run(21, 4.0), self._run(21, 4.0))


class ReverserSceneTests(unittest.TestCase):
    """The scene routes REVERSER differently for humans and for bots."""

    def _scene_with_reverser(self, mode, *, ai: tuple[bool, bool] = (False, True),
                             seed: int = 17):  # type: ignore[no-untyped-def]
        scene = _scene(mode, seed=seed, ai=ai)
        scene.powerups.set_held(0, get_item("pu.reverser").data, "REVERSER")
        self.assertTrue(scene.powerups.trigger(0))
        self.assertTrue(scene.powerups.controls_inverted(1))
        return scene

    def test_a_human_still_gets_the_full_negation(self) -> None:
        from pongpro.core.constants import GameMode
        scene = self._scene_with_reverser(GameMode.SOLO, ai=(False, False))
        self.assertAlmostEqual(scene._apply_inversion(1, 0.8, STEP), -0.8)
        # And the firer's own controls are untouched.
        self.assertAlmostEqual(scene._apply_inversion(0, 0.8, STEP), 0.8)

    def test_a_bot_is_never_fully_negated(self) -> None:
        from pongpro.core.constants import GameMode
        scene = self._scene_with_reverser(GameMode.SOLO, ai=(False, True))
        first = scene._apply_inversion(1, 0.8, STEP)
        self.assertNotAlmostEqual(first, -0.8)
        self.assertAlmostEqual(first, -0.8 * AI_CONFUSE_STRENGTH)

    def test_a_disoriented_bot_actually_misfires(self) -> None:
        from pongpro.core.constants import GameMode
        scene = self._scene_with_reverser(GameMode.SOLO, ai=(False, True))
        applied = [scene._apply_inversion(1, 0.8, STEP)
                   for _ in range(int(round(30.0 / STEP)))]
        mean = sum(applied) / len(applied)
        self.assertLess(mean, 0.0)     # it is still mostly going the wrong way
        self.assertGreater(sum(1 for a in applied if a > 0.0), 0)
        for value in applied:
            self.assertGreaterEqual(value, -0.8 * AI_CONFUSE_STRENGTH)
            self.assertLessEqual(value, 0.8)

    def test_ai_vs_ai_disorients_both_sides(self) -> None:
        from pongpro.core.constants import GameMode
        scene = _scene(GameMode.AI_VS_AI, seed=4, ai=(True, True))
        reverser = get_item("pu.reverser").data
        scene.powerups.set_held(0, reverser, "REVERSER")
        scene.powerups.set_held(1, reverser, "REVERSER")
        self.assertTrue(scene.powerups.trigger(0))  # side 0 blinds side 1
        self.assertTrue(scene.powerups.trigger(1))  # and vice versa

        for player in (0, 1):
            with self.subTest(player=player):
                self.assertNotAlmostEqual(
                    scene._apply_inversion(player, 0.8, STEP),
                    -0.8)

    def test_it_recovers_once_the_effect_expires(self) -> None:
        from pongpro.core.constants import GameMode
        scene = self._scene_with_reverser(GameMode.SOLO, ai=(False, True))
        self.assertNotAlmostEqual(scene._apply_inversion(1, 0.8, STEP), -0.8)
        scene.powerups.clear()
        self.assertAlmostEqual(scene._apply_inversion(1, 0.8, STEP), 0.8)
        self.assertAlmostEqual(scene._apply_inversion(1, -0.5, STEP), -0.5)

    def test_two_player_remains_a_pure_negation_for_both(self) -> None:
        from pongpro.core.constants import GameMode
        scene = self._scene_with_reverser(GameMode.TWO_PLAYER, ai=(False, False))
        for value in (0.8, -0.35, 1.0):
            self.assertAlmostEqual(scene._apply_inversion(1, value, STEP),
                                   -value)


class ReverserEffectivenessTests(unittest.TestCase):
    """What REVERSER actually costs a bot, measured rather than assumed.

    The arithmetic in :class:`DisorientationTests` proves the gain is never a
    clean mirror.  This drives a *real* AIController against a *real* ball and
    counts how often the paddle still gets in front of it, which is the thing
    the change was actually meant to move.
    """

    RALLIES = 60
    #: Seconds to give one rally before conceding that it never arrived.
    RALLY_CAP = 8.0

    def _intercept_rate(self, mode: str, seed: int) -> float:
        import math

        from pongpro.core.constants import BASE_BALL_SPEED, Difficulty
        from pongpro.gameplay.ai import PRESETS, AIController
        from pongpro.gameplay.entities import Ball, Paddle, default_court
        from pongpro.gameplay.physics import resolve_walls

        court = default_court()
        ai = AIController(Paddle(True, court), PRESETS[Difficulty.HARD],
                          Rng(seed))
        # Separate streams: rally geometry must not shift when the AI's own
        # reaction roll changes.
        rally_rng = Rng(seed + 1000)
        disoriented = Disoriented(Rng(seed + 2000))
        ball = Ball(court)

        caught = 0
        for _ in range(self.RALLIES):
            paddle = ai.paddle
            paddle.y = court.center_y
            ball.park(court, court.center_x, court.center_y)
            ball.active = True
            angle = rally_rng.uniform(0.08, 0.34)
            ball.vx = -BASE_BALL_SPEED * math.cos(angle)
            ball.vy = BASE_BALL_SPEED * math.sin(angle) * rally_rng.sign()

            for _ in range(int(self.RALLY_CAP / STEP)):
                axis = ai.update(STEP, ball, court)
                if mode == "mirrored":
                    axis = -axis
                elif mode == "disoriented":
                    axis *= disoriented.step(STEP, True)
                paddle.update(axis, STEP, court)
                ball.begin_step()
                ball.integrate(STEP)
                resolve_walls(ball, court)
                if ball.x - ball.r < court.left:
                    if abs(paddle.y - ball.y) <= paddle.h * 0.5:
                        caught += 1
                    break
        return caught / self.RALLIES

    def test_a_reverser_makes_a_bot_miss_far_more_often(self) -> None:
        clean = self._intercept_rate("clean", 3)
        mirrored = self._intercept_rate("mirrored", 3)
        disoriented = self._intercept_rate("disoriented", 3)
        detail = (f"clean={clean:.2f} mirrored={mirrored:.2f} "
                  f"disoriented={disoriented:.2f}")

        # Baseline: an untouched bot at HARD difficulty reads the rally.
        self.assertGreaterEqual(clean, 0.80, detail)
        # The whole point: a heavy drop, not a nudge.
        self.assertLess(disoriented, clean - 0.30, detail)
        self.assertLessEqual(disoriented, 0.45, detail)
        # ... but not so heavy that the powerup plays the rally for you.  A
        # measured 0.10 was reported as "the AI is still missing the ball too
        # much": the bot was so disoriented it never contested anything, which
        # reads as a broken opponent rather than a disoriented one.  0.18 is
        # well clear of that 0.10 while still failing any attempt to hand the
        # bot back a clean read (measured: 0.27 on this seed).
        self.assertGreaterEqual(disoriented, 0.18, detail)
        # ... and never worse than the old hard negation, which turned the
        # paddle into a guaranteed free point.
        self.assertGreaterEqual(disoriented, mirrored, detail)
        # And never a *guaranteed* miss either: a disoriented bot still
        # converts the odd rally, the way a real player half-recovers.
        self.assertGreater(disoriented, 0.0, detail)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

