"""Random mid-match powerup pickups.

One bubble is live at a time.  It appears a few seconds into play, hangs around
long enough to be worth contesting, and is replaced by a fresh random powerup
if nobody takes it - so the pickup is an invitation to fight over the middle of
the court rather than a free buff.

Who collects it is decided by the *ball*, not by proximity: a bubble only pays
out when the ball reaches it **after** bouncing off a paddle, and it goes to
that paddle's side.  A ball that has not been returned yet (straight off a
serve) drifts straight through, because a serve is not a rally.

Nothing here knows how to draw itself; the scene owns the presentation so this
module stays free of fonts and surfaces.
"""

from __future__ import annotations

from ..core.rng import Rng
from ..economy.catalog import ShopItem
from .entities import Ball, Court

#: Seconds of play before the first bubble appears, so it lands mid-game.
FIRST_SPAWN_DELAY = 6.0
#: How long a bubble waits to be collected before it despawns.
#:
#: Raised from the original 8 s in two steps (then 16 s, now 30 s) because the
#: window kept proving too short to matter.  A pickup is only contested if
#: both players can *see* it, plan a rally around it and still be there when
#: the ball arrives; at 8 s it was a hazard you occasionally clipped, and at
#: 16 s it was a bonus the leader collected by accident.  At 30 s the bubble
#: is up for long enough to become an objective in its own right - the middle
#: of the court is worth fighting over even when nobody needs the buff - and
#: the 3-7 s respawn gap still keeps at most one bubble live at a time, so the
#: court never fills up with them.
LIFETIME = 30.0
#: Gap before the next bubble, re-rolled every time.
RESPAWN_GAP_MIN = 3.0
RESPAWN_GAP_MAX = 7.0
#: Visual and collision radius of a bubble, in logical pixels.
RADIUS = 26.0
#: Bubbles stay clear of the ends so both sides can reasonably contest them.
X_MARGIN = 190.0
Y_MARGIN = 48.0


class PowerupBubble:
    """One collectible powerup, floating at a fixed court position."""

    __slots__ = ("item", "x", "y", "radius", "life", "max_life", "pulse")

    def __init__(self, item: ShopItem, x: float, y: float,
                 life: float = LIFETIME) -> None:
        self.item = item
        self.x = x
        self.y = y
        self.radius = RADIUS
        self.life = life
        self.max_life = life
        #: Seconds since spawn, used to animate the ring.
        self.pulse = 0.0

    @property
    def expired(self) -> bool:
        return self.life <= 0.0

    @property
    def fraction_left(self) -> float:
        """1.0 when fresh, 0.0 when about to despawn."""
        if self.max_life <= 0.0:
            return 0.0
        return max(0.0, min(1.0, self.life / self.max_life))

    def contains(self, ball: Ball) -> bool:
        """Circle/circle test between the ball and this bubble."""
        dx = ball.x - self.x
        dy = ball.y - self.y
        reach = self.radius + ball.r
        return dx * dx + dy * dy <= reach * reach


class BubbleField:
    """Spawns, times out and hands over the single live powerup bubble."""

    __slots__ = ("_pool", "_court", "_rng", "_bubble", "_timer",
                 "_first_delay", "_gap_min", "_gap_span")

    def __init__(self, pool: tuple[ShopItem, ...] | list[ShopItem],
                 court: Court, rng: Rng, *,
                 first_delay: float = FIRST_SPAWN_DELAY,
                 gap: tuple[float, float] = (RESPAWN_GAP_MIN,
                                             RESPAWN_GAP_MAX)) -> None:
        self._pool = tuple(pool)
        self._court = court
        self._rng = rng
        self._bubble: PowerupBubble | None = None
        # Overridable so a mode with its own rhythm can reuse the field
        # instead of growing a second pickup system.  FOCUS hands it a rare
        # 45-60 s cadence; a duel keeps the 3-7 s one above.
        self._first_delay = max(0.0, float(first_delay))
        lo, hi = float(gap[0]), float(gap[1])
        self._gap_min = max(0.0, min(lo, hi))
        self._gap_span = max(0.0, abs(hi - lo))
        self._timer = self._first_delay

    # -- state ------------------------------------------------------------
    @property
    def bubble(self) -> PowerupBubble | None:
        """The live bubble, or None while nothing is on the court."""
        return self._bubble

    @property
    def armed(self) -> bool:
        """False when there is nothing to collect and nothing ever coming."""
        return bool(self._pool)

    # -- simulation -------------------------------------------------------
    def update(self, dt: float, *, playing: bool) -> None:
        """Advance spawn and expiry; only live play counts as elapsed time."""
        if not playing or not self._pool:
            return
        bubble = self._bubble
        if bubble is not None:
            bubble.life -= dt
            bubble.pulse += dt
            if bubble.life <= 0.0:
                self._bubble = None
                self._start_gap()
            return
        self._timer -= dt
        if self._timer <= 0.0:
            self._spawn()

    def collect(self, ball: Ball, collector: int | None) -> PowerupBubble | None:
        """Consume the live bubble when the ball touches it.

        ``collector`` is the side whose paddle last returned the ball.  A ball
        that has not been returned (``None``) cannot collect anything, so a
        serve never hands out a powerup.
        """
        bubble = self._bubble
        if bubble is None or collector is None:
            return None
        if not bubble.contains(ball):
            return None
        self._bubble = None
        self._start_gap()
        return bubble

    def reset(self) -> None:
        """Forget the live bubble and restart the opening delay."""
        self._bubble = None
        self._timer = self._first_delay

    # -- internals --------------------------------------------------------
    def _start_gap(self) -> None:
        self._timer = self._gap_min + self._rng.uniform(0.0, self._gap_span)

    def _spawn(self) -> None:
        item = self._rng.choice(self._pool)
        court = self._court
        left, right = court.left + X_MARGIN, court.right - X_MARGIN
        top, bottom = court.top + Y_MARGIN, court.bottom - Y_MARGIN
        if right <= left:  # pragma: no cover - only a tiny court would do this
            left = right = court.center_x
        if bottom <= top:  # pragma: no cover
            top = bottom = court.center_y
        self._bubble = PowerupBubble(
            item,
            self._rng.uniform(left, right),
            self._rng.uniform(top, bottom),
        )


__all__ = [
    "BubbleField",
    "PowerupBubble",
    "FIRST_SPAWN_DELAY",
    "LIFETIME",
    "RESPAWN_GAP_MIN",
    "RESPAWN_GAP_MAX",
    "RADIUS",
]
