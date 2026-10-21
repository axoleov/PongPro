"""Deterministic seeded random helpers.

Gameplay randomness (AI aim error, particle jitter, replay) must be
reproducible: a match started with seed *S* replays identically, which is what
makes offline replay validation and bug reproduction possible.
"""

from __future__ import annotations

import random
from typing import Sequence, TypeVar

T = TypeVar("T")


class Rng:
    """Thin wrapper over :class:`random.Random` with game-friendly helpers."""

    __slots__ = ("_seed", "_rng")

    def __init__(self, seed: int | None = None) -> None:
        self._seed = seed if seed is not None else random.randrange(2**31)
        self._rng = random.Random(self._seed)

    @property
    def seed(self) -> int:
        return self._seed

    def reseed(self, seed: int | None = None) -> int:
        self._seed = seed if seed is not None else random.randrange(2**31)
        self._rng.seed(self._seed)
        return self._seed

    def fork(self) -> "Rng":
        """Child stream derived from the parent without perturbing it."""
        return Rng(self._rng.randrange(2**31))

    # -- primitives -------------------------------------------------------
    def uniform(self, lo: float, hi: float) -> float:
        return self._rng.uniform(lo, hi)

    def gauss(self, mean: float, sigma: float) -> float:
        if sigma <= 0.0:
            return mean
        return self._rng.gauss(mean, sigma)

    def chance(self, probability: float) -> bool:
        return self._rng.random() < probability

    def choice(self, seq: Sequence[T]) -> T:
        return self._rng.choice(list(seq))

    def randint(self, lo: int, hi: int) -> int:
        return self._rng.randint(lo, hi)

    def sign(self) -> float:
        return 1.0 if self._rng.random() < 0.5 else -1.0
