"""Mid-match powerup pickups: timing, ownership and the serve exclusion.

The contract under test is the one written down in
:mod:`pongpro.gameplay.bubbles`:

* nothing appears at the start of a match - the first bubble waits
  ``FIRST_SPAWN_DELAY`` seconds of *live* play, so it lands mid-game;
* a bubble pays out only to a side whose paddle has actually returned the
  ball, so a serve drifts straight through it;
* an unclaimed bubble vanishes after ``LIFETIME`` and a fresh random one
  follows after a short gap;
* what it carries always comes from the profile's collection and never from
  the empty "no powerup" slot.

Nothing here renders, so the whole file runs headless with no surfaces.
"""

from __future__ import annotations

import unittest

from pongpro.core.rng import Rng
from pongpro.economy.catalog import PowerEffect, ShopCategory, get_item
from pongpro.economy.wallet import Wallet
from pongpro.gameplay.bubbles import (
    FIRST_SPAWN_DELAY,
    LIFETIME,
    RESPAWN_GAP_MAX,
    RESPAWN_GAP_MIN,
    RADIUS,
    X_MARGIN,
    Y_MARGIN,
    BubbleField,
)
from pongpro.gameplay.entities import Ball, default_court

STEP = 1.0 / 120.0  # the game's fixed physics step


def _pool() -> tuple:
    """A collection rich enough that a draw is not trivially forced."""
    wallet = Wallet(coins=100_000)
    for item_id in ("pu.giant", "pu.magnet", "pu.fireball"):
        wallet.buy(item_id)
    from pongpro.gameplay.powerups import owned_powerups
    return owned_powerups(wallet)


def _field(pool=None) -> BubbleField:
    return BubbleField(pool if pool is not None else _pool(),
                       default_court(), Rng(1234))


def _run(field: BubbleField, seconds: float, *, playing: bool = True) -> None:
    """Step ``field`` in fixed increments for ``seconds`` of game time."""
    steps = int(round(seconds / STEP))
    for _ in range(steps):
        field.update(STEP, playing=playing)


class SpawnTimingTests(unittest.TestCase):
    """The bubble must appear mid-game, not on the opening serve."""

    def test_nothing_before_the_first_delay(self) -> None:
        field = _field()
        _run(field, FIRST_SPAWN_DELAY - 0.25)
        self.assertIsNone(field.bubble)

    def test_first_bubble_appears_after_the_delay(self) -> None:
        field = _field()
        _run(field, FIRST_SPAWN_DELAY + STEP * 3)
        self.assertIsNotNone(field.bubble)

    def test_live_play_is_the_only_clock(self) -> None:
        """Countdowns, celebrations and replays must not age a bubble."""
        field = _field()
        _run(field, FIRST_SPAWN_DELAY * 4, playing=False)
        self.assertIsNone(field.bubble)

    def test_an_empty_pool_never_spawns(self) -> None:
        field = BubbleField([], default_court(), Rng(1))
        _run(field, FIRST_SPAWN_DELAY * 4)
        self.assertIsNone(field.bubble)
        self.assertFalse(field.armed)

    def test_reset_restarts_the_opening_delay(self) -> None:
        field = _field()
        _run(field, FIRST_SPAWN_DELAY * 2)
        self.assertIsNotNone(field.bubble)
        field.reset()
        self.assertIsNone(field.bubble)
        _run(field, FIRST_SPAWN_DELAY - 0.25)
        self.assertIsNone(field.bubble)

    def test_spawn_stays_inside_the_court_margins(self) -> None:
        """A bubble pinned to a goal line would be uncontestable."""
        court = default_court()
        for seed in range(12):
            field = BubbleField(_pool(), court, Rng(seed))
            _run(field, FIRST_SPAWN_DELAY + STEP)
            bubble = field.bubble
            assert bubble is not None
            self.assertGreaterEqual(bubble.x, court.left + X_MARGIN)
            self.assertLessEqual(bubble.x, court.right - X_MARGIN)
            self.assertGreaterEqual(bubble.y, court.top + Y_MARGIN)
            self.assertLessEqual(bubble.y, court.bottom - Y_MARGIN)


class ExpiryTests(unittest.TestCase):
    """A bubble nobody takes must vanish and be replaced by a new one."""

    def test_lifetime_is_respected(self) -> None:
        field = _field()
        _run(field, FIRST_SPAWN_DELAY + STEP)
        first = field.bubble
        assert first is not None
        # One second short of the deadline it is still there ...
        _run(field, LIFETIME - 1.0)
        self.assertIsNotNone(field.bubble)
        # ... and past it, it is gone.
        _run(field, 1.0 + STEP * 4)
        self.assertIsNone(field.bubble)

    def test_a_new_bubble_follows_after_the_gap(self) -> None:
        field = _field()
        _run(field, FIRST_SPAWN_DELAY + STEP)
        _run(field, LIFETIME + STEP * 4)
        self.assertIsNone(field.bubble)
        _run(field, RESPAWN_GAP_MAX + STEP * 4)
        self.assertIsNotNone(field.bubble)

    def test_the_gap_is_never_shorter_than_the_minimum(self) -> None:
        field = _field()
        _run(field, FIRST_SPAWN_DELAY + STEP)
        _run(field, LIFETIME + STEP * 4)
        # Just under the shortest possible gap: still nothing.
        _run(field, RESPAWN_GAP_MIN - 0.05)
        self.assertIsNone(field.bubble)

    def test_lifetime_counts_down_and_hands_back_a_fraction(self) -> None:
        field = _field()
        _run(field, FIRST_SPAWN_DELAY + STEP)
        bubble = field.bubble
        assert bubble is not None
        self.assertFalse(bubble.expired)
        self.assertGreater(bubble.fraction_left, 0.99)
        self.assertLessEqual(bubble.fraction_left, 1.0)
        elapsed = 2.0
        _run(field, elapsed)
        assert field.bubble is not None
        # Expressed against LIFETIME rather than an absolute number, so the
        # window can be retuned without the test silently testing nothing.
        self.assertAlmostEqual(field.bubble.fraction_left,
                               1.0 - elapsed / LIFETIME, delta=0.02)


class CollectionTests(unittest.TestCase):
    """Ownership follows the last paddle to touch the ball."""

    def test_ball_is_taken_only_when_it_overlaps(self) -> None:
        field = _field()
        _run(field, FIRST_SPAWN_DELAY + STEP)
        bubble = field.bubble
        assert bubble is not None
        ball = Ball(default_court())
        ball.x, ball.y = bubble.x + 5000.0, bubble.y + 5000.0
        self.assertIsNone(field.collect(ball, 0))
        self.assertIsNotNone(field.bubble)

    def test_a_rallied_ball_collects_and_clears_the_bubble(self) -> None:
        field = _field()
        _run(field, FIRST_SPAWN_DELAY + STEP)
        bubble = field.bubble
        assert bubble is not None
        ball = Ball(default_court())
        ball.x, ball.y = bubble.x, bubble.y
        taken = field.collect(ball, 1)
        self.assertIsNotNone(taken)
        self.assertIsNone(field.bubble)
        self.assertEqual(taken.item.id, bubble.item.id)

    def test_a_serve_cannot_collect(self) -> None:
        """No paddle has returned it yet, so nobody has earned the pickup."""
        field = _field()
        _run(field, FIRST_SPAWN_DELAY + STEP)
        bubble = field.bubble
        assert bubble is not None
        ball = Ball(default_court())
        ball.x, ball.y = bubble.x, bubble.y
        self.assertIsNone(field.collect(ball, None))
        self.assertIsNotNone(field.bubble)

    def test_collect_starts_the_respawn_gap(self) -> None:
        field = _field()
        _run(field, FIRST_SPAWN_DELAY + STEP)
        ball = Ball(default_court())
        bubble = field.bubble
        assert bubble is not None
        ball.x, ball.y = bubble.x, bubble.y
        field.collect(ball, 0)
        _run(field, RESPAWN_GAP_MIN - 0.05)
        self.assertIsNone(field.bubble)
        _run(field, RESPAWN_GAP_MAX)
        self.assertIsNotNone(field.bubble)

    def test_each_side_is_a_valid_collector(self) -> None:
        for collector in (0, 1):
            with self.subTest(collector=collector):
                field = _field()
                _run(field, FIRST_SPAWN_DELAY + STEP)
                bubble = field.bubble
                assert bubble is not None
                ball = Ball(default_court())
                ball.x, ball.y = bubble.x, bubble.y
                self.assertIsNotNone(field.collect(ball, collector))


class GeometryTests(unittest.TestCase):
    """`contains` is a plain circle/circle overlap on the ball's radius."""

    def test_ball_centred_on_the_bubble(self) -> None:
        bubble_field = _field()
        _run(bubble_field, FIRST_SPAWN_DELAY + STEP)
        bubble = bubble_field.bubble
        assert bubble is not None
        ball = Ball(default_court())
        ball.x, ball.y = bubble.x, bubble.y
        self.assertTrue(bubble.contains(ball))

    def test_just_inside_and_just_outside_the_reach(self) -> None:
        bubble_field = _field()
        _run(bubble_field, FIRST_SPAWN_DELAY + STEP)
        bubble = bubble_field.bubble
        assert bubble is not None
        ball = Ball(default_court())
        reach = RADIUS + ball.r

        ball.x, ball.y = bubble.x + reach - 1.0, bubble.y
        self.assertTrue(bubble.contains(ball))

        ball.x, ball.y = bubble.x + reach + 1.0, bubble.y
        self.assertFalse(bubble.contains(ball))

        # Purely vertical contact resolves the same way.
        ball.x, ball.y = bubble.x, bubble.y + reach + 1.0
        self.assertFalse(bubble.contains(ball))

    def test_radius_matches_the_module_constant(self) -> None:
        bubble_field = _field()
        _run(bubble_field, FIRST_SPAWN_DELAY + STEP)
        bubble = bubble_field.bubble
        assert bubble is not None
        self.assertEqual(bubble.radius, RADIUS)


class LifetimeBudgetTests(unittest.TestCase):
    """The pickup has to be long enough to be worth contesting over."""

    def test_the_lifetime_was_raised_again(self) -> None:
        self.assertEqual(LIFETIME, 30.0)

    def test_a_bubble_outlives_the_gap_that_follows_it(self) -> None:
        self.assertGreater(LIFETIME, RESPAWN_GAP_MAX * 2)

    def test_ten_untouched_seconds_do_not_lose_it(self) -> None:
        """A slow, cautious rally must still have time to grab the pickup."""
        field = _field()
        _run(field, FIRST_SPAWN_DELAY + STEP)
        _run(field, 10.0)
        bubble = field.bubble
        self.assertIsNotNone(bubble)
        assert bubble is not None
        self.assertFalse(bubble.expired)
        self.assertGreater(bubble.fraction_left, 0.3)

    def test_it_does_survive_long_enough_to_expire(self) -> None:
        """The longer window must not have quietly removed the deadline."""
        field = _field()
        _run(field, FIRST_SPAWN_DELAY + STEP + LIFETIME + STEP * 4)
        self.assertIsNone(field.bubble)


class PickupContentTests(unittest.TestCase):
    """What the bubble carries comes from the profile's own collection."""

    def test_never_carries_the_empty_powerup(self) -> None:
        court = default_court()
        for seed in range(20):
            field = BubbleField(_pool(), court, Rng(seed))
            _run(field, FIRST_SPAWN_DELAY + STEP)
            bubble = field.bubble
            assert bubble is not None
            self.assertIsNot(bubble.item.data.effect, PowerEffect.NONE)
            self.assertNotEqual(bubble.item.id, "pu.none")

    def test_carries_only_powerups_from_the_pool(self) -> None:
        pool = _pool()
        ids = {item.id for item in pool}
        court = default_court()
        for seed in range(20):
            field = BubbleField(pool, court, Rng(seed))
            _run(field, FIRST_SPAWN_DELAY + STEP)
            bubble = field.bubble
            assert bubble is not None
            self.assertIn(bubble.item.id, ids)

    def test_varies_across_seeds(self) -> None:
        """A 'random powerup' that is always the same is not random."""
        court = default_court()
        picks = set()
        for seed in range(24):
            field = BubbleField(_pool(), court, Rng(seed))
            _run(field, FIRST_SPAWN_DELAY + STEP)
            assert field.bubble is not None
            picks.add(field.bubble.item.id)
        self.assertGreater(len(picks), 1)

    def test_a_bought_powerup_reaches_the_bubble_pool(self) -> None:
        from pongpro.gameplay.powerups import owned_powerups
        wallet = Wallet(coins=100_000)
        owned = {item.id for item in owned_powerups(wallet)}
        self.assertTrue(wallet.buy("pu.shield"))
        self.assertNotEqual({item.id for item in owned_powerups(wallet)},
                            owned)
        self.assertIn("pu.shield",
                      {item.id for item in owned_powerups(wallet)})


class FreeDefaultTests(unittest.TestCase):
    """A profile that has bought nothing still has a usable pool."""

    def test_default_wallet_pool_is_usable(self) -> None:
        from pongpro.gameplay.powerups import owned_powerups
        wallet = Wallet()
        pool = owned_powerups(wallet)
        self.assertTrue(pool)
        for item in pool:
            self.assertIn("pu.", item.id)
            self.assertIsNot(item.data.effect, PowerEffect.NONE)

    def test_no_powerup_is_excluded_from_the_pool(self) -> None:
        from pongpro.gameplay.powerups import owned_powerups
        wallet = Wallet()
        wallet.equip("pu.none")  # equipping it must not put it back in
        self.assertNotIn("pu.none",
                         {item.id for item in owned_powerups(wallet)})
        self.assertEqual(get_item("pu.none").category, ShopCategory.POWERUP)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
