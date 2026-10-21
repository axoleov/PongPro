"""Money, inventory and the shop catalog.

Three small pieces, deliberately separated:

* :mod:`~pongpro.economy.catalog` - pure data: what exists, what it costs and
  how it looks.  No SDL, no I/O, unit-testable on its own.
* :mod:`~pongpro.economy.wallet` - the rules: what a match pays, what a
  purchase costs, and the invariants of an owned/equipped loadout.
* :mod:`~pongpro.storage` - the bytes on disk (``shop.json``).

Nothing here imports a scene or a renderer, so the economy can be exercised
headless by tests and by tools.
"""

from __future__ import annotations

from .catalog import (
    CATEGORIES,
    ITEMS,
    ITEMS_BY_ID,
    RARITY_COLORS,
    BallLook,
    BackgroundLook,
    ImpactLook,
    PowerupSpec,
    PaddleLook,
    Rarity,
    ShopCategory,
    ShopItem,
    TrailLook,
    default_item,
    get_item,
    items_in,
)
from .wallet import (
    STARTING_COINS,
    WALLET_CACHE_KEY,
    WALLET_VERSION,
    Wallet,
    get_wallet,
    invalidate_wallet,
    match_reward,
    save_wallet,
)

__all__ = [
    "CATEGORIES",
    "ITEMS",
    "ITEMS_BY_ID",
    "RARITY_COLORS",
    "STARTING_COINS",
    "WALLET_CACHE_KEY",
    "WALLET_VERSION",
    "BallLook",
    "BackgroundLook",
    "ImpactLook",
    "PaddleLook",
    "PowerupSpec",
    "Rarity",
    "ShopCategory",
    "ShopItem",
    "TrailLook",
    "Wallet",
    "default_item",
    "get_item",
    "get_wallet",
    "invalidate_wallet",
    "items_in",
    "match_reward",
    "save_wallet",
]
