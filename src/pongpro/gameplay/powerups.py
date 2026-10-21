"""Runtime for powerups: cooldowns, timers, modifiers and pickups.

Design notes
------------
Every paddle holds its **own** :class:`~pongpro.economy.catalog.PowerupSpec`.
That is what lets the machine play a different powerup than the human: in
1P-vs-AI the bot draws one at random from the profile's collection, and in
AI-vs-AI both bots do, while two-player still shares the equipped spec so the
duel stays symmetric.

Each paddle can also be *granted* a powerup it does not hold, which is how the
mid-match pickup bubbles work: whoever's paddle last returned the ball inherits
the bubble's effect for that spec's own duration, without losing the powerup
it was going to fire by hand.

Because a paddle can run at most **one effect of each kind** at a time -
:meth:`PowerupSystem.grant` replaces any same-kind grant, and a grant outranks
the held powerup of the same kind - every modifier stays idempotent.  A giant
paddle is either giant or it is not, so overlapping activations can never stack
into an unbounded multiplier.  Different kinds still compose normally, so a
giant *and* fast paddle is simply both.

Effects only tick while the ball is actually in play, so a buff can never
quietly expire during a goal celebration and feel like a bug.
"""

from __future__ import annotations

from ..core.constants import Color
from ..core.rng import Rng
from ..economy.catalog import (
    PowerEffect,
    PowerTarget,
    PowerupSpec,
    ShopCategory,
    ShopItem,
    get_item,
)
from .entities import Ball, Court, Paddle

#: How hard the magnet may change the ball's vertical speed, in px/s^2.
#:
#: This is *authority*, not a free-running shove: it caps how fast the
#: steering can re-aim, while :data:`MAGNET_MAX_VY` caps where it can end up.
#: The original value was the whole acceleration budget and it was integrated
#: for the entire effect, which is what let ``vy`` run away.
MAGNET_STRENGTH = 2400.0
#: Lateral error (px) below which the magnet stops steering (avoids jitter).
MAGNET_DEADZONE = 8.0
#: Commanded vertical speed per pixel of miss.  Sets the closed-loop time
#: constant at ``1 / MAGNET_GAIN`` seconds, so 2.4 lands the ball in roughly
#: half a second instead of chasing it for the rest of the rally.
MAGNET_GAIN = 2.4
#: Ceiling on the vertical speed the magnet may command, in px/s.  Keeps the
#: curve readable (and the ball's total speed near the rally's own ceiling)
#: no matter how long the effect runs.
MAGNET_MAX_VY = 700.0
#: Seconds of AI "thinking" before a bot commits to firing its powerup.
AI_MIN_DELAY = 0.35
AI_MAX_DELAY = 1.10

#: Magnitude of the *wrong-way* gain a bot acts under while its controls are
#: inverted.  Below 1.0 on purpose: a bot never gets a clean mirror image.
#:
#: Nudged down from 0.85 so the wrong-way bursts look like a player flailing
#: at their own stick rather than a mallet welded in reverse; together with
#: :data:`AI_CONFUSE_PERSIST` this is what keeps a disoriented bot competitive
#: enough to fight over the rally instead of gifting it.
AI_CONFUSE_STRENGTH = 0.75
#: Chance that a bot's next re-read of its own controls is still the wrong one.
#:
#: This is the knob that decides how *often* it still returns a rally, and
#: measured against a real AIController at HARD it dominates everything else.
#: At the original 0.78 the bot returned 1 rally in 10 - far too few to read as
#: a player fighting their controls, so the whole exchange became a free point
#: for whoever held REVERSER.  0.62 keeps a solidly negative average gain
#: (about -0.08, so the debuff is still heavy) while lifting the return rate to
#: roughly a third: the mallet still darts the wrong way in visible bursts, and
#: still gets in front of the ball often enough that the rally looks contested.
AI_CONFUSE_PERSIST = 0.62
#: Seconds between a disoriented bot's re-reads, re-rolled every time.
#:
#: Long enough that each mis-read is a committed move rather than a per-step
#: coin flip (which would just look like vibration), short enough that the bot
#: gets several chances to recover inside a single 1.3 s exchange.
AI_CONFUSE_RETHINK = (0.28, 0.65)

#: The spec used whenever a paddle holds nothing at all.
BLANK_SPEC = PowerupSpec(
    PowerEffect.NONE, PowerTarget.SELF, 0.0, 0.0,
    glyph="··", accent=Color.TEXT_DIM)


def owned_powerups(wallet) -> tuple[ShopItem, ...]:  # type: ignore[no-untyped-def]
    """Powerups ``wallet`` has collected, minus the empty "no powerup" slot.

    The free OVERDRIVE stays in the pool, so a profile that has bought nothing
    still has something for a bot to hold or a bubble to carry - an empty pool
    would silently disable the whole mechanic for new players.
    """
    return tuple(item for item in wallet.owned_in(ShopCategory.POWERUP)
                 if item.data.effect is not PowerEffect.NONE)


def choose_powerup(wallet, rng: Rng) -> ShopItem:  # type: ignore[no-untyped-def]
    """Draw one powerup at random from ``wallet``'s collection.

    The draw is independent of what the profile has equipped, so a bot never
    simply mirrors the human's choice - the two coincide only by luck.
    """
    pool = owned_powerups(wallet)
    if not pool:  # pragma: no cover - every profile owns OVERDRIVE
        return get_item("pu.none")
    return rng.choice(pool)


class PowerupSystem:
    """Per-paddle powerup holding plus the running effect timers for one match.

    Two independent things can put an effect on a paddle:

    * the spec it **holds**, which is what its player fires by hand (or a bot
      fires on its own clock), and
    * a **grant**, which starts running the moment it is handed over and is
      how the pickup bubbles pay out.

    They are kept apart deliberately: collecting a bubble must not cost a
    player the powerup it was about to fire.
    """

    __slots__ = ("_held", "_names", "_cooldown", "_active", "_ai_timer",
                 "_fired", "_grants")

    def __init__(self, spec: PowerupSpec | None = None) -> None:
        held = spec if spec is not None else BLANK_SPEC
        self._held: list[PowerupSpec] = [held, held]
        #: Shop display name for each paddle's held powerup.
        self._names: list[str] = ["", ""]
        self._cooldown = [0.0, 0.0]
        self._active = [0.0, 0.0]
        self._ai_timer = [0.0, 0.0]
        self._fired = [False, False]
        #: Running grants per paddle, each ``[spec, seconds_left, name]``.
        self._grants: list[list[list]] = [[], []]

    # -- what each paddle holds -------------------------------------------
    def held_spec(self, player: int) -> PowerupSpec:
        """The powerup ``player`` can fire by hand."""
        return self._held[player]

    def held_name(self, player: int) -> str:
        return self._names[player]

    def set_held(self, player: int, spec: PowerupSpec | None,
                 name: str = "") -> None:
        """Give ``player`` a powerup to hold, clearing its old charge."""
        self._held[player] = spec if spec is not None else BLANK_SPEC
        self._names[player] = name
        self._cooldown[player] = 0.0
        self._active[player] = 0.0
        self._ai_timer[player] = 0.0
        self._fired[player] = False

    def grant(self, player: int, spec: PowerupSpec,
              name: str = "") -> bool:
        """Start ``spec`` running on ``player`` for its own duration.

        ``name`` is the shop label, kept only so the HUD can say what just
        landed.  Any grant already running the *same kind* of effect is
        replaced rather than stacked, which is what keeps every modifier
        idempotent.  Returns False when the spec does nothing.
        """
        if spec.effect is PowerEffect.NONE or spec.duration <= 0.0:
            return False
        own = self._grants[player]
        own[:] = [entry for entry in own if entry[0].effect is not spec.effect]
        own.append([spec, float(spec.duration), name])
        return True

    def active_grant(self, player: int) -> tuple[PowerupSpec, float, str] | None:
        """The grant running on ``player``: ``(spec, seconds_left, name)``.

        Returns None when nothing was collected, so callers can fall straight
        back to describing the powerup that paddle is holding.
        """
        for spec, left, name in self._grants[player]:
            if left > 0.0:
                return spec, left, name
        return None

    def active_grants(self, player: int) -> tuple[PowerupSpec, ...]:
        """Specs currently granted to ``player`` and still running."""
        return tuple(entry[0] for entry in self._grants[player]
                     if entry[1] > 0.0)

    def _active_spec_for(self, owner: int,
                         effect: PowerEffect) -> PowerupSpec | None:
        """The spec ``owner`` is running ``effect`` through, if any.

        A grant outranks the held powerup of the same kind, because the grant
        is the newer of the two and a player who just grabbed a bubble should
        see *that* effect, not a stale one.
        """
        for spec, left, _name in self._grants[owner]:
            if left > 0.0 and spec.effect is effect:
                return spec
        if self._active[owner] > 0.0 and self._held[owner].effect is effect:
            return self._held[owner]
        return None

    def _affects(self, player: int,
                 effect: PowerEffect) -> tuple[bool, PowerupSpec]:
        """Is ``player`` under ``effect``?  Returns (matched, the spec).

        ``SELF`` and ``GLOBAL`` powerups act on whoever is running them;
        ``OPPONENT`` powerups act on the other paddle, so the subject is the
        player *opposite* the one whose timer is running.
        """
        for owner in (player, 1 - player):
            spec = self._active_spec_for(owner, effect)
            if spec is None:
                continue
            if spec.target is PowerTarget.OPPONENT:
                if owner != player:
                    return True, spec
            elif spec.target is PowerTarget.GLOBAL:
                return True, spec
            elif owner == player:
                return True, spec
        return False, BLANK_SPEC

    # -- introspection ----------------------------------------------------
    @property
    def enabled(self) -> bool:
        """False only when every paddle holds ``pu.none`` and none is granted.

        A bubble can keep the subsystem live even in a no-powerup duel, so
        this reads the grants as well as the held specs.
        """
        if any(spec.effect is not PowerEffect.NONE for spec in self._held):
            return True
        return any(entry[1] > 0.0 for own in self._grants for entry in own)

    def ready(self, player: int) -> bool:
        return (self._held[player].effect is not PowerEffect.NONE
                and self._cooldown[player] <= 0.0
                and self._active[player] <= 0.0)

    def active_for(self, player: int) -> float:
        """Remaining seconds of ``player``'s effect (0.0 when inactive)."""
        return self._active[player]

    def cooldown_left(self, player: int) -> float:
        return self._cooldown[player]

    def is_active(self, player: int) -> bool:
        return self._active[player] > 0.0

    def just_fired(self, player: int) -> bool:
        """True for exactly one step after a successful activation."""
        value = self._fired[player]
        self._fired[player] = False
        return value

    # -- activation -------------------------------------------------------
    def trigger(self, player: int) -> bool:
        """Fire ``player``'s held powerup.  False when it was not ready."""
        if not self.ready(player):
            return False
        spec = self._held[player]
        self._active[player] = max(0.0, spec.duration)
        self._cooldown[player] = max(0.0, spec.cooldown)
        self._fired[player] = True
        return True

    def clear(self) -> None:
        """Drop every timer (called when the match ends or is rebuilt)."""
        for i in (0, 1):
            self._cooldown[i] = 0.0
            self._active[i] = 0.0
            self._ai_timer[i] = 0.0
            self._fired[i] = False
            self._grants[i].clear()

    # -- stepping ---------------------------------------------------------
    def tick(self, dt: float) -> None:
        """Advance cooldowns, effect timers and grants by one fixed step."""
        for i in (0, 1):
            if self._cooldown[i] > 0.0:
                self._cooldown[i] = max(0.0, self._cooldown[i] - dt)
            if self._active[i] > 0.0:
                self._active[i] = max(0.0, self._active[i] - dt)
            own = self._grants[i]
            if own:
                for entry in own:
                    entry[1] = max(0.0, entry[1] - dt)
                own[:] = [entry for entry in own if entry[1] > 0.0]

    def ai_should_fire(self, player: int, dt: float, *, incoming: bool,
                       rng: Rng) -> bool:
        """Bots consider firing on their own clock, then commit tactically.

        Returns True once per activation.  The delay mirrors the AI's reaction
        time so a bot never fires a frame after the ball leaves the opponent's
        paddle, which would look scripted.
        """
        if not self.ready(player):
            return False
        if self._ai_timer[player] > 0.0:
            self._ai_timer[player] -= dt
            return False
        # Re-arm with a fresh delay whenever the powerup comes back.
        self._ai_timer[player] = AI_MIN_DELAY + rng.uniform(
            0.0, AI_MAX_DELAY - AI_MIN_DELAY)
        return bool(incoming)

    # -- derived modifiers ------------------------------------------------
    def _scale(self, player: int, effect: PowerEffect) -> float:
        """Magnitude of ``effect`` as it applies to ``player`` (1.0 if none)."""
        matched, spec = self._affects(player, effect)
        return spec.magnitude if matched else 1.0

    def height_scale(self, player: int) -> float:
        """Multiplier for ``player``'s paddle height (1.0 when unmodified)."""
        return self._scale(player, PowerEffect.HEIGHT)

    def speed_scale(self, player: int) -> float:
        """Multiplier for ``player``'s paddle speed (1.0 when unmodified)."""
        return self._scale(player, PowerEffect.SPEED)

    def controls_inverted(self, player: int) -> bool:
        return self._affects(player, PowerEffect.INVERT)[0]

    def shielded(self, player: int) -> bool:
        """True while ``player``'s goal line is sealed."""
        return self._affects(player, PowerEffect.SHIELD)[0]

    def return_speed_scale(self, player: int) -> float:
        return self._scale(player, PowerEffect.RETURN_SPEED)

    def coins_per_hit(self, player: int) -> int:
        matched, spec = self._affects(player, PowerEffect.COINS)
        return spec.coins if matched else 0

    def slow_ball(self) -> bool:
        """Global ball-speed effects are active."""
        return any(self._active_spec_for(owner, PowerEffect.SLOW_BALL)
                   is not None for owner in (0, 1))

    def ball_speed_scale(self) -> float:
        for owner in (0, 1):
            spec = self._active_spec_for(owner, PowerEffect.SLOW_BALL)
            if spec is not None:
                return spec.magnitude
        return 1.0

    def active_spec(self, player: int) -> PowerupSpec:
        """What ``player``'s HUD pill should describe.

        A running grant is the more interesting news, so it takes the slot;
        otherwise the pill reports what that paddle is holding.
        """
        grant = self.active_grant(player)
        return grant[0] if grant is not None else self._held[player]

    def magnet_target(self, player: int, ball: Ball, court: Court,
                      paddle: Paddle) -> float | None:
        """Y the ball is steered toward, or None when magnet is not running."""
        if self._active_spec_for(player, PowerEffect.MAGNET) is None:
            return None
        # Only bend the ball while it is travelling toward the owner, so the
        # effect reads as "the puck finds your mallet" rather than as a shove.
        toward_owner = (paddle.is_left and ball.vx < 0.0) or (
            (not paddle.is_left) and ball.vx > 0.0)
        if not toward_owner or not ball.active:
            return None
        half = paddle.h * 0.5
        return max(court.top + half, min(court.bottom - half, paddle.y))


class Disoriented:
    """How a bot's aim degrades while REVERSER is on it.

    A human keeps full, perfectly negated control - that *is* the punishment:
    they have to re-map their own hands under pressure.  A bot gets no such
    clean answer.  Negating its output outright would send it marching away
    from the ball for the whole duration and it would never miss by luck, so
    the paddle would become a guaranteed free point and the powerup would
    read as a cheat rather than as a debuff.

    Instead the bot keeps computing the correct intercept and *mis-reads its
    own inputs* while it acts on them.  Most re-reads land wrong, a few land
    right, and it re-decides in bursts rather than every step - so the paddle
    overshoots, oscillates and half-recovers the way a disoriented player
    does.  The hit rate collapses; it just does not go to zero.
    """

    __slots__ = ("_rng", "_gain", "_hold", "_shocked")

    def __init__(self, rng: Rng) -> None:
        self._rng = rng
        #: Gain currently applied to the raw axis.  1.0 == reading correctly.
        self._gain = 1.0
        #: Seconds left before the next re-read.
        self._hold = 0.0
        #: True until the guaranteed opening mis-read, so the flip always
        #: lands as a shock rather than sometimes slipping past unnoticed.
        self._shocked = True

    @property
    def gain(self) -> float:
        """The multiplier this step's axis is actually acting under."""
        return self._gain

    def step(self, dt: float, active: bool) -> float:
        """Advance one fixed step and return the gain to apply now.

        Pass ``active=False`` while inversion is off; the bot snaps back to a
        clean read immediately and the next flip shocks it afresh.
        """
        if not active:
            self._gain = 1.0
            self._hold = 0.0
            self._shocked = True
            return 1.0

        self._hold -= dt
        if self._shocked or self._hold <= 0.0:
            # The shock is not a roll: controls that invert must feel like they
            # inverted on the *next* input, every time, or a unlucky first
            # re-read leaves the bot reading cleanly for the opening beat and
            # the flip simply does not register.  Every re-read after that one
            # goes back to being a chance.
            if self._shocked:
                self._shocked = False
                self._gain = -AI_CONFUSE_STRENGTH
            else:
                self._gain = (-AI_CONFUSE_STRENGTH
                              if self._rng.chance(AI_CONFUSE_PERSIST)
                              else 1.0)
            self._hold = self._rng.uniform(*AI_CONFUSE_RETHINK)
        return self._gain


def apply_magnet(ball: Ball, target_y: float, dt: float, *,
                 target_vy: float = 0.0) -> None:
    """Drive ``ball`` vertically onto the line ``target_y``.

    This is a *commanded velocity*, not an integrated shove.  The old version
    added a constant force for as long as the effect lasted, which on a double
    integrator is bang-bang control: the ball overshot the line, reversed, and
    overshot again a little wider each time, until five seconds of magnet had
    wound ``vy`` into the thousands and the puck was smearing between the
    walls rather than flying.  Inside the deadzone it did nothing at all, so a
    ball that arrived on target simply kept the vertical speed it had and
    sailed straight past the mallet it was meant to find.

    What runs instead is a proportional servo - how far off we still are, in
    ``MAGNET_GAIN`` seconds of closing - approached at ``MAGNET_STRENGTH``
    px/s^2 so the correction stays smooth instead of snapping.  The command
    decays to ``target_vy`` exactly as the ball lines up, which is what
    removes the overshoot, and :data:`MAGNET_MAX_VY` bounds it outright.

    ``target_vy`` is the owning paddle's own speed, so a mallet that is
    already sliding is *tracked* rather than chased.  Nothing here touches
    ``vx``: forward travel and the rally's pacing stay the physics module's
    business, and speed clamping stays with :mod:`pongpro.gameplay.physics`.
    """
    if not ball.active:
        return
    error = target_y - ball.y
    if abs(error) < MAGNET_DEADZONE:
        # On the line already: hold the paddle's speed, do not oscillate
        # around a sign flip in an error that is essentially noise.
        error = 0.0
    desired = target_vy + error * MAGNET_GAIN
    if desired > MAGNET_MAX_VY:
        desired = MAGNET_MAX_VY
    elif desired < -MAGNET_MAX_VY:
        desired = -MAGNET_MAX_VY

    # How much authority this one fixed step gets.
    step = MAGNET_STRENGTH * dt
    delta = desired - ball.vy
    if delta > step:
        ball.vy += step
    elif delta < -step:
        ball.vy -= step
    else:
        ball.vy = desired


__all__ = [
    "PowerupSystem",
    "Disoriented",
    "apply_magnet",
    "choose_powerup",
    "owned_powerups",
    "BLANK_SPEC",
    "MAGNET_STRENGTH",
    "MAGNET_DEADZONE",
    "MAGNET_GAIN",
    "MAGNET_MAX_VY",
    "AI_CONFUSE_STRENGTH",
    "AI_CONFUSE_PERSIST",
    "AI_CONFUSE_RETHINK",
]
