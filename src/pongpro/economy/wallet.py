"""Coins, inventory and reward maths.

The wallet lives in its own document (``shop.json``) rather than in
``stats.json`` because :func:`pongpro.storage.store._migrate_stats` drops
unknown keys on load: an older build must never be able to destroy a player's
purchases.  :mod:`pongpro.storage` owns the file I/O, this module owns the
schema and the rules, and neither imports the other's UI.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from ..core.constants import Difficulty, GameMode
from .catalog import (
    CATEGORIES,
    ITEMS_BY_ID,
    ShopCategory,
    ShopItem,
    default_item,
    get_item,
    items_in,
)

log = logging.getLogger(__name__)

WALLET_VERSION = 1

#: Coins a brand-new profile starts with - enough for a couple of early buys.
STARTING_COINS = 250

# -- reward tuning ---------------------------------------------------------
#: Paid for turning up.  Always awarded, even on a loss, so a player on a
#: losing streak can still work towards the shop.
PARTICIPATION_BONUS = 40
#: Paid for a win (see :func:`match_reward` for which modes qualify).
WIN_BONUS = 80
#: Per point scored by *either* side - rewards long, dramatic matches.
POINTS_PER_POINT = 7
#: Every RALLY_STEP of the longest rally pays RALLY_BONUS, capped at RALLY_CAP.
RALLY_STEP = 5
RALLY_CAP = 60
RALLY_BONUS = 3
#: Every HIT_STEP returns pays HIT_BONUS.
HIT_STEP = 12
HIT_BONUS = 5
#: FOCUS pays for *endurance* instead of points: every FOCUS_TIME_STEP of
#: live survival pays FOCUS_TIME_BONUS on top of the returns it produced.
#: Tuned so a two-minute run lands near a comfortable SOLO win and a serious
#: five-minute run roughly doubles it - long enough to matter, short enough
#: that the shop still moves.
FOCUS_TIME_STEP = 15
FOCUS_TIME_BONUS = 6

#: Solo play scales the award; other modes are always 1.0 because difficulty
#: is meaningless for a local versus match or a spectated AI game.
DIFFICULTY_MULTIPLIER: dict[Difficulty, float] = {
    Difficulty.EASY: 0.8,
    Difficulty.NORMAL: 1.0,
    Difficulty.HARD: 1.4,
    Difficulty.ELITE: 1.9,
}


def _counts_as_win(mode: GameMode, winner: int | None) -> bool:
    """Does this outcome earn the win bonus?

    * ``AI_VS_AI`` never does - nobody is playing, so nobody is rewarded.
    * ``TWO_PLAYER`` always does - both paddles are humans on one machine and
      a local match that reached its conclusion is a win for the profile.
    * ``FOCUS`` never does - there is no opponent to beat, so a run has no
      winner to pay one for.  Its reward comes from :func:`focus_reward`.
    * ``SOLO`` pays only when the human (index 0) took the match.
    """
    if winner is None:
        return False
    if mode in (GameMode.AI_VS_AI, GameMode.FOCUS):
        return False
    if mode is GameMode.TWO_PLAYER:
        return winner in (0, 1)
    return winner == 0


def match_reward(*, mode: GameMode, winner: int | None,
                 difficulty: Difficulty | None, score: Iterable[int],
                 longest_rally: int, total_hits: int) -> int:
    """Coins earned by finishing one match.

    Pure and total: the same inputs always produce the same award, which is
    what makes it unit-testable and what stops the HUD from disagreeing with
    the wallet.
    """
    points = sum(max(0, int(p)) for p in score)
    award = PARTICIPATION_BONUS + POINTS_PER_POINT * points
    award += (min(max(0, int(longest_rally)), RALLY_CAP) // RALLY_STEP) * RALLY_BONUS
    award += (max(0, int(total_hits)) // HIT_STEP) * HIT_BONUS
    if _counts_as_win(mode, winner):
        award += WIN_BONUS

    multiplier = 1.0
    if mode is GameMode.SOLO and difficulty is not None:
        multiplier = DIFFICULTY_MULTIPLIER.get(difficulty, 1.0)
    return max(1, int(round(award * multiplier)))


def focus_reward(*, time: float, returns: int) -> int:
    """Coins earned by finishing one FOCUS run.

    There is no score to fold in and no win to bonus, so the award is built
    from the two things a run actually produces: returns, which pay exactly
    as they do in a duel, and survival time, which is the mode's own
    definition of doing well.  ``time`` is live play, not wall-clock - the
    countdowns and "LIFE LOST" beats never tick it.
    """
    award = PARTICIPATION_BONUS
    award += (max(0, int(returns)) // HIT_STEP) * HIT_BONUS
    award += (max(0, int(time)) // FOCUS_TIME_STEP) * FOCUS_TIME_BONUS
    return max(1, int(round(award)))


# --------------------------------------------------------------------------
# Wallet
# --------------------------------------------------------------------------
class Wallet:
    """Coins plus the owned/equipped loadout for one local profile."""

    __slots__ = ("coins", "lifetime_earned", "lifetime_spent", "purchases",
                 "_owned", "_equipped")

    def __init__(self, *, coins: int = STARTING_COINS,
                 lifetime_earned: int = STARTING_COINS,
                 lifetime_spent: int = 0, purchases: int = 0,
                 owned: Iterable[str] | None = None,
                 equipped: dict[ShopCategory, str] | None = None) -> None:
        self.coins = max(0, int(coins))
        self.lifetime_earned = max(0, int(lifetime_earned))
        self.lifetime_spent = max(0, int(lifetime_spent))
        self.purchases = max(0, int(purchases))
        self._owned: set[str] = set(owned) if owned is not None else {
            item.id for item in ITEMS_BY_ID.values() if item.free
        }
        self._equipped: dict[ShopCategory, str] = dict(equipped or {})

    # -- construction -----------------------------------------------------
    @classmethod
    def default(cls) -> "Wallet":
        return cls()

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "Wallet":
        """Build a wallet from a stored document, healing anything odd.

        Unknown ids, unequipped categories and negative balances all fall back
        to a safe value instead of raising - a hand-edited save must never
        stop the game from booting.
        """
        raw = payload if isinstance(payload, dict) else {}

        owned = {item.id for item in ITEMS_BY_ID.values() if item.free}
        stored_owned = raw.get("owned")
        if isinstance(stored_owned, list):
            for entry in stored_owned:
                if isinstance(entry, str) and entry in ITEMS_BY_ID:
                    owned.add(entry)

        equipped: dict[ShopCategory, str] = {}
        stored_equipped = raw.get("equipped")
        if isinstance(stored_equipped, dict):
            for category in CATEGORIES:
                value = stored_equipped.get(category.value)
                if isinstance(value, str) and value in owned:
                    item = ITEMS_BY_ID.get(value)
                    if item is not None and item.category is category:
                        equipped[category] = value
        for category in CATEGORIES:
            equipped.setdefault(category, default_item(category).id)

        wallet = cls(
            coins=_as_int(raw.get("coins"), STARTING_COINS),
            lifetime_earned=_as_int(raw.get("lifetime_earned"), STARTING_COINS),
            lifetime_spent=_as_int(raw.get("lifetime_spent"), 0),
            purchases=_as_int(raw.get("purchases"), 0),
            owned=owned,
            equipped=equipped,
        )
        # An equipped item must always be owned; a mismatch means an old save.
        for category in CATEGORIES:
            if not wallet.owns(equipped[category]):
                equipped[category] = default_item(category).id
        return wallet

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": WALLET_VERSION,
            "coins": self.coins,
            "lifetime_earned": self.lifetime_earned,
            "lifetime_spent": self.lifetime_spent,
            "purchases": self.purchases,
            "owned": sorted(self._owned),
            "equipped": {c.value: self._equipped.get(c, default_item(c).id)
                         for c in CATEGORIES},
        }

    # -- inventory --------------------------------------------------------
    def owns(self, item_id: str) -> bool:
        return item_id in self._owned

    @property
    def owned_ids(self) -> frozenset[str]:
        return frozenset(self._owned)

    def owned_in(self, category: ShopCategory) -> tuple[ShopItem, ...]:
        from .catalog import items_in
        return tuple(item for item in items_in(category) if item.id in self._owned)

    def equipped_id(self, category: ShopCategory) -> str:
        item_id = self._equipped.get(category)
        if item_id is None or item_id not in self._owned:
            return default_item(category).id
        return item_id

    def equipped_item(self, category: ShopCategory) -> ShopItem:
        return get_item(self.equipped_id(category))

    def can_afford(self, price: int) -> bool:
        return self.coins >= max(0, int(price))

    # -- commerce ---------------------------------------------------------
    def buy(self, item_id: str) -> bool:
        """Purchase and auto-equip ``item_id``.

        Returns:
            True when the item changed hands; False when it was already owned
            or the balance was too low (no partial charges, ever).
        """
        item = ITEMS_BY_ID.get(item_id)
        if item is None or item.id in self._owned:
            return False
        if item.price > self.coins:
            return False
        self.coins -= item.price
        self.lifetime_spent += item.price
        self.purchases += 1
        self._owned.add(item.id)
        self._equipped[item.category] = item.id
        log.info("Bought %s for %d coins (%d left)", item.id, item.price,
                 self.coins)
        return True

    def equip(self, item_id: str) -> bool:
        """Equip an owned item.  Returns True when the loadout changed."""
        item = ITEMS_BY_ID.get(item_id)
        if item is None or item.id not in self._owned:
            return False
        if self._equipped.get(item.category) == item.id:
            return False
        self._equipped[item.category] = item.id
        return True

    def award(self, amount: int) -> int:
        """Credit ``amount`` coins (never negative) and return what was added."""
        credit = max(0, int(amount))
        self.coins += credit
        self.lifetime_earned += credit
        return credit

    # -- reporting --------------------------------------------------------
    def owned_count(self, category: ShopCategory) -> int:
        from .catalog import items_in
        return sum(1 for item in items_in(category) if item.id in self._owned)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"Wallet(coins={self.coins}, owned={len(self._owned)}, "
                f"purchases={self.purchases})")


def default_wallet() -> dict[str, Any]:
    """Schema of a fresh shop profile (owned defaults, starting coins)."""
    return {
        "version": WALLET_VERSION,
        "coins": STARTING_COINS,
        "lifetime_earned": STARTING_COINS,
        "lifetime_spent": 0,
        "purchases": 0,
        "owned": [item.id for item in ITEMS_BY_ID.values() if item.free],
        "equipped": {c.value: default_item(c).id for c in CATEGORIES},
    }


def _as_int(value: Any, fallback: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


# --------------------------------------------------------------------------
# Context plumbing
# --------------------------------------------------------------------------
#: Key under which the live wallet is cached on ``AppContext.extra``.
WALLET_CACHE_KEY = "wallet"


def get_wallet(ctx) -> Wallet:  # type: ignore[no-untyped-def]
    """Load (once) and cache the profile wallet on the application context.

    Scenes mutate this object directly; :func:`save_wallet` persists it.
    """
    cached = ctx.extra.get(WALLET_CACHE_KEY)
    if isinstance(cached, Wallet):
        return cached
    wallet = Wallet.from_dict(ctx.storage.load_wallet())
    ctx.extra[WALLET_CACHE_KEY] = wallet
    return wallet


def save_wallet(ctx, wallet: Wallet | None = None) -> bool:  # type: ignore[no-untyped-def]
    """Persist the cached (or given) wallet back to disk."""
    live = wallet if wallet is not None else get_wallet(ctx)
    ctx.extra[WALLET_CACHE_KEY] = live
    return ctx.storage.save_wallet(live.to_dict())


def invalidate_wallet(ctx) -> None:  # type: ignore[no-untyped-def]
    """Drop the cached wallet (used by tests and the storage hot-swap)."""
    ctx.extra.pop(WALLET_CACHE_KEY, None)


__all__ = [
    "WALLET_VERSION",
    "STARTING_COINS",
    "PARTICIPATION_BONUS",
    "WIN_BONUS",
    "POINTS_PER_POINT",
    "RALLY_STEP",
    "RALLY_CAP",
    "RALLY_BONUS",
    "HIT_STEP",
    "HIT_BONUS",
    "FOCUS_TIME_STEP",
    "FOCUS_TIME_BONUS",
    "DIFFICULTY_MULTIPLIER",
    "Wallet",
    "match_reward",
    "focus_reward",
    "WALLET_CACHE_KEY",
    "get_wallet",
    "save_wallet",
    "invalidate_wallet",
]
