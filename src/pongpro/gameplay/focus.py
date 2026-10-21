"""FOCUS mode: one player, two paddles, no opponent.

FOCUS is a coordination exercise rather than a duel.  A single player drives
the left paddle with **W / S** and the right one with **I / K** (or the arrow
keys), and the only objective is to keep the ball off both goal lines for as
long as possible.  There is no opponent, so there is no score either: the
"First to N" rule stops meaning points and starts meaning *lives*.

Three consequences fall out of that, and they shape everything in this module:

* **Powerups are off.**  A timed modifier is a decision about *which* player
  it helps, and there is only one player here.  The shop's powerups are
  therefore never held, never fired and never carried by a pickup.
* **The only pickup is a life.**  :data:`LIFE_ORB` grants one life on contact
  and is capped at the run's starting count, so an orb is a *repair* rather
  than an extra credit - the player is always playing against the same budget
  they chose in the menu.
* **Ball speed is a shared ladder.**  It still climbs per return, so pressure
  builds the way it does in a duel; a lost life only partly resets it (see
  :meth:`FocusRun.recovered_speed`), which keeps late lives harder than the
  first without making them hopeless.

The policy lives here; the phase machine stays in
:mod:`pongpro.gameplay.match`, which owns countdown, banners and the
match-over transition for every mode including this one.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.constants import (
    BASE_BALL_SPEED,
    Color,
    FOCUS_LIFE_FIRST_DELAY,
    FOCUS_LIFE_GAP_MAX,
    FOCUS_LIFE_GAP_MIN,
    FOCUS_SPEED_RECOVERY,
)
from ..core.rng import Rng
from ..economy.catalog import (
    PowerEffect,
    PowerTarget,
    PowerupSpec,
    Rarity,
    ShopCategory,
    ShopItem,
)
from .bubbles import BubbleField
from .entities import Court


@dataclass(slots=True)
class FocusRun:
    """Life budget and live counters for one FOCUS run.

    Deliberately dumb: the scene and the match both reach into it, so it
    keeps no timers and makes no decisions about phases.  Everything that
    needs a *rule* ("does this end the run?") returns a bool and leaves the
    caller to act on it.
    """

    lives: int
    max_lives: int
    #: Concessions so far.  ``MatchStats.total_goals`` counts the same thing,
    #: but the HUD wants it live without reaching through the match.
    lost: int = 0

    def __post_init__(self) -> None:
        # A run always starts with at least one life and can never have a cap
        # below what it currently holds, however odd the inputs were.
        self.lives = max(1, int(self.lives))
        self.max_lives = max(self.lives, int(self.max_lives))

    # -- lives ------------------------------------------------------------
    @property
    def last_life(self) -> bool:
        """True when the next concession ends the run."""
        return self.lives == 1

    @property
    def full(self) -> bool:
        """True when no more lives can be banked this run."""
        return self.lives >= self.max_lives

    def concede(self) -> bool:
        """Spend one life.  Returns True when the run has just ended."""
        self.lives = max(0, self.lives - 1)
        self.lost += 1
        return self.lives <= 0

    def restore(self) -> bool:
        """Bank a life from an orb.  False when already at the cap.

        The cap is the run's own starting count, so "First to 5" always means
        exactly five lives no matter how many orbs are collected.  The caller
        turns a ``False`` into the bonus-coin payout instead.

        A finished run (``lives == 0``) also refuses: the match is already
        over, so letting an orb revive it would describe a state the phase
        machine has left behind.
        """
        if self.lives <= 0 or self.full:
            return False
        self.lives = min(self.max_lives, self.lives + 1)
        return True

    # -- ball speed -------------------------------------------------------
    def recovered_speed(self, speed: float) -> float:
        """Speed the ball re-serves at after conceding.

        A *partial* reset: the ball keeps :data:`FOCUS_SPEED_RECOVERY` of the
        speed that beat the player and climbs again from there, so a life
        costs momentum without handing back a brand-new game.  Floored at the
        base serve speed, because conceding three seconds into a run must not
        make the next life *easier* than the run's own opening serve.
        """
        return max(BASE_BALL_SPEED, float(speed) * FOCUS_SPEED_RECOVERY)


#: The one and only pickup that appears in FOCUS.
#:
#: Built as a plain value rather than registered in the shop catalog on
#: purpose.  The catalog is documented as "every buyable item", and this is
#: explicitly not buyable: keeping it out of ``ITEMS_BY_ID`` means no profile
#: can ever own it, :func:`pongpro.gameplay.powerups.owned_powerups` can never
#: put it in a duel's bubble pool, and the shop has nothing to filter out.
#: The only catalog change FOCUS needs is the ``PowerEffect.LIFE`` member.
LIFE_ORB = ShopItem(
    id="pu.life",
    category=ShopCategory.POWERUP,
    name="LIFE",
    price=0,
    rarity=Rarity.LEGENDARY,
    description="Restore one life. FOCUS mode only - never sold, never owned.",
    data=PowerupSpec(
        PowerEffect.LIFE, PowerTarget.SELF, 0.0, 0.0,
        magnitude=1.0, glyph="+1", accent=Color.GOLD,
    ),
)


def life_orb_field(court: Court, rng: Rng) -> BubbleField:
    """The FOCUS pickup field: one orb kind, on a rare and long cadence.

    The cadence is live-play seconds, so time spent in a countdown or a
    "LIFE LOST" beat never brings the next orb closer - an orb is a reward
    for *surviving*, not for the clock simply running.
    """
    return BubbleField(
        (LIFE_ORB,), court, rng,
        first_delay=FOCUS_LIFE_FIRST_DELAY,
        gap=(FOCUS_LIFE_GAP_MIN, FOCUS_LIFE_GAP_MAX),
    )


__all__ = [
    "FOCUS_LIFE_FIRST_DELAY",
    "FOCUS_LIFE_GAP_MAX",
    "FOCUS_LIFE_GAP_MIN",
    "FOCUS_SPEED_RECOVERY",
    "FocusRun",
    "LIFE_ORB",
    "life_orb_field",
]
