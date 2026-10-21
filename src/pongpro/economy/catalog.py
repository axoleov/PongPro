"""The shop catalog: every buyable item, its price and its *look* / *spec*.

The catalog is pure data plus tiny value objects.  It deliberately imports
nothing from :mod:`pongpro.scenes`, :mod:`pongpro.storage` or
:mod:`pongpro.rendering` so it can be unit tested (and reasoned about) with no
SDL subsystems involved.

Two families of item exist:

* **Cosmetics** carry a *look* dataclass describing how to draw something.
  :mod:`pongpro.rendering.skins` is the only module that interprets them.
* **Powerups** carry a :class:`PowerupSpec` describing a timed gameplay
  modifier, interpreted by :mod:`pongpro.gameplay.powerups`.

Every category has exactly one free "classic" item at index 0 which is owned
and equipped out of the box, so a fresh profile never renders a missing look.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..core.constants import Color

#: Convenience alias - every colour in the catalog is a plain RGB triple.
RGB = tuple[int, int, int]


class ShopCategory(str, Enum):
    """The six item buckets shown as tabs in the shop."""

    BALL = "ball"
    PADDLE = "paddle"
    BACKGROUND = "background"
    TRAIL = "trail"
    IMPACT = "impact"
    POWERUP = "powerup"

    @property
    def title(self) -> str:
        return _CATEGORY_TITLES[self]


_CATEGORY_TITLES: dict[ShopCategory, str] = {
    ShopCategory.BALL: "BALLS",
    ShopCategory.PADDLE: "PADDLES",
    ShopCategory.BACKGROUND: "BACKGROUNDS",
    ShopCategory.TRAIL: "BALL TRAILS",
    ShopCategory.IMPACT: "HIT EFFECTS",
    ShopCategory.POWERUP: "POWERUPS",
}

#: Tab order used by the shop scene and by the layout tests.
CATEGORIES: tuple[ShopCategory, ...] = tuple(ShopCategory)


class Rarity(str, Enum):
    """Cosmetic tier; drives the accent colour on shop cards."""

    FREE = "free"
    COMMON = "common"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


#: Rarity -> display colour.  Kept next to the enum so the shop scene, the
#: results screen and the tests can never disagree on the palette.
RARITY_COLORS: dict[Rarity, RGB] = {
    Rarity.FREE: Color.TEXT_DIM,
    Rarity.COMMON: Color.TEXT,
    Rarity.RARE: Color.P1,
    Rarity.EPIC: Color.P2,
    Rarity.LEGENDARY: Color.GOLD,
}


# --------------------------------------------------------------------------
# Cosmetic looks
# --------------------------------------------------------------------------
class BallPattern(str, Enum):
    SOLID = "solid"
    DOT = "dot"
    RING = "ring"
    STRIPES = "stripes"
    ORB = "orb"
    NOVA = "nova"


@dataclass(frozen=True, slots=True)
class BallLook:
    """How the ball is drawn.  The ball is shared, so it never uses team hues."""

    pattern: BallPattern = BallPattern.SOLID
    fill: RGB = Color.BALL
    core: RGB = (255, 255, 255)
    accent: RGB = (255, 255, 255)
    glow: float = 1.0


class PaddlePattern(str, Enum):
    SOLID = "solid"
    STRIPES = "stripes"
    NEON = "neon"
    SPLIT = "split"
    TECH = "tech"


@dataclass(frozen=True, slots=True)
class PaddleLook:
    """How both paddles are drawn.

    ``tint`` blends the *team* colour towards ``body`` so the default skin is
    pure cyan/pink while legendary skins fully override it.  The outline always
    mixes body and team colour, and the glow keeps the team hue, so the two
    sides stay distinguishable no matter which skin is equipped.
    """

    pattern: PaddlePattern = PaddlePattern.SOLID
    body: RGB = (255, 255, 255)
    accent: RGB = (255, 255, 255)
    tint: float = 0.0
    glow: float = 1.0


class BackdropStyle(str, Enum):
    CLASSIC = "classic"
    GRID = "grid"
    AURORA = "aurora"
    SUNSET = "sunset"
    CANDY = "candy"
    VOID = "void"
    ARCADE = "arcade"
    NOIR = "noir"


@dataclass(frozen=True, slots=True)
class BackgroundLook:
    """Whole-scene theme: page colour, court palette and backdrop decoration."""

    style: BackdropStyle = BackdropStyle.CLASSIC
    bg: RGB = Color.BG
    court: RGB = Color.COURT
    line: RGB = Color.LINE
    line_soft: RGB = Color.LINE_SOFT
    accent: RGB = Color.ACCENT
    vignette: int = 70
    starfield: bool = True
    grid: bool = False


class TrailStyle(str, Enum):
    SOLID = "solid"
    COMET = "comet"
    RIBBON = "ribbon"
    SPARK = "spark"
    NEON = "neon"


@dataclass(frozen=True, slots=True)
class TrailLook:
    """How the fading ball trail is drawn."""

    style: TrailStyle = TrailStyle.SOLID
    color: RGB = Color.BALL
    color2: RGB = Color.BALL
    width_scale: float = 1.0
    glow: float = 1.0


class ImpactStyle(str, Enum):
    SPARK = "spark"
    RING = "ring"
    SHARDS = "shards"
    PULSE = "pulse"
    STARS = "stars"
    RAINBOW = "rainbow"


@dataclass(frozen=True, slots=True)
class ImpactLook:
    """How paddle / wall / goal contacts are dressed up."""

    style: ImpactStyle = ImpactStyle.SPARK
    colors: tuple[RGB, ...] = (Color.BALL,)
    count_scale: float = 1.0
    speed_scale: float = 1.0
    glow: float = 1.0


# --------------------------------------------------------------------------
# Powerups
# --------------------------------------------------------------------------
class PowerEffect(str, Enum):
    """Which modifier a powerup toggles while it is active."""

    NONE = "none"
    #: Paddle vertical speed multiplier.
    SPEED = "speed"
    #: Paddle height multiplier.
    HEIGHT = "height"
    #: Ball is gently steered toward the owner's paddle.
    MAGNET = "magnet"
    #: Multiplier applied to the ball speed after this paddle returns it.
    RETURN_SPEED = "return_speed"
    #: The owner's goal line is sealed against the ball.
    SHIELD = "shield"
    #: Every return made by the owner pays coins.
    COINS = "coins"
    #: Opponent's controls are inverted.
    INVERT = "invert"
    #: Global ball-speed multiplier.
    SLOW_BALL = "slow_ball"
    #: Instantly restores one life.  FOCUS mode only: it has no duration and
    #: no cooldown because there is nothing to *run*, and it is deliberately
    #: absent from the shop - :mod:`pongpro.gameplay.focus` owns the only
    #: instance of it, so no profile can ever buy, own or equip one.
    LIFE = "life"


class PowerTarget(str, Enum):
    """Who a powerup's effect applies to."""

    SELF = "self"
    OPPONENT = "opponent"
    GLOBAL = "global"


@dataclass(frozen=True, slots=True)
class PowerupSpec:
    """A timed gameplay modifier shared by both paddles in a match."""

    effect: PowerEffect
    target: PowerTarget
    duration: float
    cooldown: float
    magnitude: float = 1.0
    coins: int = 0
    #: Two-character glyph used by the shop preview and the HUD pill.
    glyph: str = "··"
    accent: RGB = Color.ACCENT


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ShopItem:
    """One catalog entry.  ``data`` is a look *or* a powerup spec."""

    id: str
    category: ShopCategory
    name: str
    price: int
    rarity: Rarity
    description: str
    data: Any

    def __post_init__(self) -> None:
        if self.price < 0:
            raise ValueError(f"{self.id}: price must be >= 0")

    @property
    def free(self) -> bool:
        return self.price == 0

    @property
    def spec(self) -> PowerupSpec:
        """Typed accessor for powerup items."""
        if self.category is not ShopCategory.POWERUP:
            raise TypeError(f"{self.id} is not a powerup")
        return self.data


def _items() -> tuple[ShopItem, ...]:
    """Build the catalog once at import time."""
    out: list[ShopItem] = []

    def add(item_id: str, name: str, price: int, rarity: Rarity,
            description: str, data: Any) -> None:
        out.append(ShopItem(item_id, _CATEGORY_OF[item_id], name, price,
                            rarity, description, data))

    # -- balls -----------------------------------------------------------
    add("ball.classic", "CLASSIC", 0, Rarity.FREE,
        "The original arcade ball. Bright, honest, slightly smug.",
        BallLook(BallPattern.SOLID, Color.BALL, (255, 255, 255),
                 (255, 255, 255), 1.0))
    add("ball.crimson", "CRIMSON CORE", 220, Rarity.COMMON,
        "A hard red core with a pale centre dot.",
        BallLook(BallPattern.DOT, (214, 68, 68), (255, 206, 206),
                 (255, 120, 120), 1.0))
    add("ball.mint", "MINT CHIP", 260, Rarity.COMMON,
        "Cool green with a dark ring. Easy on the eyes at 1150 px/s.",
        BallLook(BallPattern.RING, (120, 236, 190), (232, 255, 246),
                 (38, 118, 94), 1.05))
    add("ball.ember", "EMBER", 480, Rarity.RARE,
        "Half-and-half orange that strobes as it tumbles.",
        BallLook(BallPattern.STRIPES, (255, 140, 50), (255, 226, 176),
                 (255, 60, 0), 1.1))
    add("ball.frost", "FROST", 540, Rarity.RARE,
        "An icy shell with a glowing rim.",
        BallLook(BallPattern.ORB, (140, 200, 255), (240, 250, 255),
                 (58, 132, 226), 1.25))
    add("ball.rose", "ROSE QUARTZ", 820, Rarity.RARE,
        "Soft pink with a candy dot. Deceptively pretty.",
        BallLook(BallPattern.DOT, (255, 150, 215), (255, 232, 246),
                 (255, 90, 180), 1.15))
    add("ball.violet", "VOID ORB", 1250, Rarity.EPIC,
        "A dark core wrapped in violet light.",
        BallLook(BallPattern.ORB, (140, 90, 255), (28, 10, 58),
                 (206, 158, 255), 1.4))
    add("ball.solar", "SOLAR FLARE", 1600, Rarity.EPIC,
        "Boiling plasma. The halo grows with its speed.",
        BallLook(BallPattern.NOVA, (255, 196, 60), (255, 255, 224),
                 (255, 92, 0), 1.55))
    add("ball.obsidian", "OBSIDIAN", 2450, Rarity.LEGENDARY,
        "Lightless stone with a single white ring. Brutal contrast.",
        BallLook(BallPattern.RING, (26, 26, 34), (10, 10, 14),
                 (236, 242, 255), 1.3))
    add("ball.arcane", "ARCANE", 3300, Rarity.LEGENDARY,
        "Three colours that should not work together, somehow working.",
        BallLook(BallPattern.NOVA, (96, 255, 200), (255, 128, 224),
                 (255, 242, 122), 1.8))

    # -- paddles ---------------------------------------------------------
    add("paddle.classic", "CLASSIC", 0, Rarity.FREE,
        "Factory colours. Cyan left, pink right, no questions asked.",
        PaddleLook(PaddlePattern.SOLID, (255, 255, 255), (255, 255, 255),
                   0.0, 1.0))
    add("paddle.carbon", "CARBON FIBER", 320, Rarity.COMMON,
        "Woven dark composite with a cool grey highlight.",
        PaddleLook(PaddlePattern.TECH, (44, 50, 62), (152, 168, 196),
                   0.45, 1.0))
    add("paddle.sunset", "SUNSET", 460, Rarity.COMMON,
        "A warm two-tone blade that keeps a hint of team colour.",
        PaddleLook(PaddlePattern.SPLIT, (255, 132, 64), (255, 208, 122),
                   0.62, 1.1))
    add("paddle.jade", "JADE STRIPE", 720, Rarity.RARE,
        "Horizontal jade banding with a pale core stripe.",
        PaddleLook(PaddlePattern.STRIPES, (86, 226, 160), (212, 255, 232),
                   0.55, 1.1))
    add("paddle.royal", "ROYAL", 1080, Rarity.RARE,
        "Violet lacquer with a split highlight.",
        PaddleLook(PaddlePattern.SPLIT, (150, 110, 255), (226, 206, 255),
                   0.72, 1.2))
    add("paddle.gold", "GILDED", 1850, Rarity.EPIC,
        "Twenty-four carat plating. The outline still shows your team colour.",
        PaddleLook(PaddlePattern.TECH, (255, 205, 92), (255, 250, 212),
                   1.0, 1.45))
    add("paddle.neon", "NEON RIG", 2600, Rarity.LEGENDARY,
        "Pure light rails. Maximum halo, maximum confidence.",
        PaddleLook(PaddlePattern.NEON, (120, 255, 255), (255, 255, 255),
                   1.0, 2.0))
    add("paddle.glitch", "GLITCH", 3100, Rarity.LEGENDARY,
        "Magenta body, cyan rails, and a suspicious number of scanlines.",
        PaddleLook(PaddlePattern.NEON, (255, 90, 220), (120, 255, 240),
                   0.9, 1.8))

    # -- backgrounds -----------------------------------------------------
    add("bg.classic", "CLASSIC ARENA", 0, Rarity.FREE,
        "The stock arena: deep navy, soft grid-free court.",
        BackgroundLook(BackdropStyle.CLASSIC, Color.BG, Color.COURT,
                       Color.LINE, Color.LINE_SOFT, Color.ACCENT, 70, True))
    add("bg.grid", "NEON GRID", 420, Rarity.COMMON,
        "An endless floor grid marching under the court.",
        BackgroundLook(BackdropStyle.GRID, (8, 10, 22), (12, 18, 34),
                       (70, 120, 200), (40, 66, 118), (110, 240, 255),
                       64, True, True))
    add("bg.aurora", "AURORA", 760, Rarity.RARE,
        "Green and violet curtains drifting behind the play area.",
        BackgroundLook(BackdropStyle.AURORA, (6, 12, 20), (10, 24, 30),
                       (110, 230, 190), (46, 96, 104), (150, 255, 210),
                       80, True))
    add("bg.sunset", "SUNSET DRIVE", 950, Rarity.RARE,
        "Warm horizon bands and a burnt-orange court.",
        BackgroundLook(BackdropStyle.SUNSET, (30, 12, 26), (40, 18, 32),
                       (255, 150, 92), (120, 58, 62), (255, 196, 120),
                       76, False))
    add("bg.candy", "CANDY POP", 1300, Rarity.EPIC,
        "Bubblegum palette for players who refuse to take this seriously.",
        BackgroundLook(BackdropStyle.CANDY, (28, 10, 32), (40, 16, 48),
                       (255, 168, 226), (110, 52, 122), (255, 214, 130),
                       62, True))
    add("bg.void", "DEEP VOID", 1500, Rarity.EPIC,
        "Near-black space. The court is the only thing that exists.",
        BackgroundLook(BackdropStyle.VOID, (2, 3, 8), (6, 8, 16),
                       (120, 140, 210), (34, 42, 72), (170, 190, 255),
                       96, True))
    add("bg.arcade", "ARCADE CRT", 2100, Rarity.EPIC,
        "Phosphor green, scanlines and a slightly curved vignette.",
        BackgroundLook(BackdropStyle.ARCADE, (4, 12, 8), (6, 18, 12),
                       (120, 255, 170), (36, 84, 60), (170, 255, 200),
                       92, False))
    add("bg.noir", "NOIR", 2900, Rarity.LEGENDARY,
        "Monochrome. The only colour left on screen is the ball.",
        BackgroundLook(BackdropStyle.NOIR, (8, 8, 10), (14, 14, 16),
                       (190, 190, 200), (70, 70, 78), (235, 235, 242),
                       88, False))

    # -- trails ----------------------------------------------------------
    add("trail.classic", "CLASSIC", 0, Rarity.FREE,
        "Softly fading dots in the ball's own colour.",
        TrailLook(TrailStyle.SOLID, Color.BALL, Color.BALL, 1.0, 1.0))
    add("trail.comet", "COMET", 360, Rarity.COMMON,
        "A tapered tail that runs from gold to deep orange.",
        TrailLook(TrailStyle.COMET, (255, 128, 40), (255, 222, 152),
                   1.15, 1.2))
    add("trail.ember", "EMBER WAKE", 620, Rarity.RARE,
        "Loose sparks scattering off the ball's path.",
        TrailLook(TrailStyle.SPARK, (255, 140, 40), (255, 58, 0),
                   1.0, 1.3))
    add("trail.ice", "ICE SHARD", 740, Rarity.RARE,
        "A hard neon line that lingers like frost.",
        TrailLook(TrailStyle.NEON, (150, 215, 255), (60, 140, 235),
                   0.9, 1.5))
    add("trail.ribbon", "RIBBON", 1150, Rarity.EPIC,
        "A continuous tapering ribbon instead of discrete dots.",
        TrailLook(TrailStyle.RIBBON, (120, 255, 190), (86, 226, 255),
                   1.25, 1.2))
    add("trail.spark", "STATIC SPARK", 1450, Rarity.EPIC,
        "Bright white crackle, like a faulty CRT.",
        TrailLook(TrailStyle.SPARK, (232, 242, 255), (255, 255, 255),
                   0.85, 1.6))
    add("trail.aurora", "AURORA WAKE", 2500, Rarity.LEGENDARY,
        "A wide ribbon that fades from mint into violet.",
        TrailLook(TrailStyle.RIBBON, (120, 255, 200), (200, 120, 255),
                   1.6, 1.5))
    add("trail.plasma", "PLASMA", 3000, Rarity.LEGENDARY,
        "Magenta core, cyan halo, no regard for subtlety.",
        TrailLook(TrailStyle.NEON, (255, 120, 235), (120, 255, 255),
                   1.4, 1.9))

    # -- hit effects -----------------------------------------------------
    add("impact.classic", "CLASSIC SPARK", 0, Rarity.FREE,
        "The stock spark burst used on every contact.",
        ImpactLook(ImpactStyle.SPARK, (Color.BALL,), 1.0, 1.0, 1.0))
    add("impact.ring", "PULSE RING", 380, Rarity.COMMON,
        "An expanding hollow ring on every touch.",
        ImpactLook(ImpactStyle.RING, (Color.P1, Color.P2), 0.7, 1.1, 1.2))
    add("impact.shards", "SHATTER", 680, Rarity.RARE,
        "Angular chunks thrown from the contact point.",
        ImpactLook(ImpactStyle.SHARDS, ((190, 210, 255), (120, 150, 210)),
                   1.1, 1.3, 0.9))
    add("impact.confetti", "CONFETTI POP", 940, Rarity.RARE,
        "Five-colour confetti with a little gravity.",
        ImpactLook(ImpactStyle.RAINBOW, (Color.P1, Color.P2, Color.BALL,
                                         Color.ACCENT, Color.GOLD),
                   1.3, 1.1, 0.8))
    add("impact.ink", "INK BLOT", 1250, Rarity.EPIC,
        "Heavy dark droplets that splatter and sink.",
        ImpactLook(ImpactStyle.SHARDS, ((60, 40, 90), (30, 20, 44)),
                   1.4, 0.8, 0.5))
    add("impact.stars", "STAR STRIKE", 1550, Rarity.EPIC,
        "Twinkling star points that hang in the air.",
        ImpactLook(ImpactStyle.STARS, (Color.GOLD, (255, 240, 180)),
                   1.2, 0.9, 1.5))
    add("impact.aurora", "AURORA BURST", 2400, Rarity.LEGENDARY,
        "A huge slow ring wrapped in mint sparks.",
        ImpactLook(ImpactStyle.RING, ((120, 255, 200), (86, 226, 255)),
                   1.6, 0.9, 1.6))
    add("impact.prism", "PRISM", 3050, Rarity.LEGENDARY,
        "Every colour, every time, no apologies.",
        ImpactLook(ImpactStyle.RAINBOW, (Color.P1, Color.P2, Color.BALL,
                                         Color.ACCENT, Color.GOLD, Color.WARN),
                   1.7, 1.4, 1.3))

    # -- powerups --------------------------------------------------------
    add("pu.none", "NO POWERUP", 0, Rarity.FREE,
        "Play it straight. No special move, no cooldown, no excuses.",
        PowerupSpec(PowerEffect.NONE, PowerTarget.SELF, 0.0, 0.0,
                    glyph="··", accent=Color.TEXT_DIM))
    add("pu.overdrive", "OVERDRIVE", 0, Rarity.FREE,
        "Your paddle surges to 1.55x speed for 6 seconds.",
        PowerupSpec(PowerEffect.SPEED, PowerTarget.SELF, 6.0, 14.0,
                    magnitude=1.55, glyph="OV", accent=Color.ACCENT))
    add("pu.giant", "GIANT PADDLE", 450, Rarity.COMMON,
        "Grow to 1.55x height for 6 seconds. The wall-to-wall special.",
        PowerupSpec(PowerEffect.HEIGHT, PowerTarget.SELF, 6.0, 16.0,
                    magnitude=1.55, glyph="GT", accent=Color.P1))
    add("pu.magnet", "MAGNET", 800, Rarity.RARE,
        "For 5 seconds the ball is gently pulled toward your paddle.",
        PowerupSpec(PowerEffect.MAGNET, PowerTarget.SELF, 5.0, 18.0,
                    magnitude=1.0, glyph="MG", accent=Color.P1))
    add("pu.fireball", "FIRE BALL", 1000, Rarity.RARE,
        "Your returns launch at 1.45x speed for 6 seconds.",
        PowerupSpec(PowerEffect.RETURN_SPEED, PowerTarget.SELF, 6.0, 16.0,
                    magnitude=1.45, glyph="FB", accent=Color.WARN))
    add("pu.shield", "SHIELD", 1400, Rarity.EPIC,
        "Seal your own goal line for 4 seconds. The ball bounces off.",
        PowerupSpec(PowerEffect.SHIELD, PowerTarget.SELF, 4.0, 22.0,
                    glyph="SH", accent=Color.P1))
    add("pu.goldrush", "GOLD RUSH", 1600, Rarity.EPIC,
        "For 8 seconds every return you make pays 4 coins.",
        PowerupSpec(PowerEffect.COINS, PowerTarget.SELF, 8.0, 24.0,
                    coins=4, glyph="GR", accent=Color.GOLD))
    add("pu.freezeray", "FREEZE RAY", 900, Rarity.RARE,
        "Halve your opponent's paddle speed for 5 seconds.",
        PowerupSpec(PowerEffect.SPEED, PowerTarget.OPPONENT, 5.0, 20.0,
                    magnitude=0.5, glyph="FZ", accent=Color.P1))
    add("pu.shrinkray", "SHRINK RAY", 1300, Rarity.EPIC,
        "Cut your opponent's paddle to 0.6x height for 6 seconds.",
        PowerupSpec(PowerEffect.HEIGHT, PowerTarget.OPPONENT, 6.0, 22.0,
                    magnitude=0.6, glyph="SR", accent=Color.P2))
    add("pu.reverser", "REVERSER", 2000, Rarity.EPIC,
        "Invert your opponent's controls for 5 seconds.",
        PowerupSpec(PowerEffect.INVERT, PowerTarget.OPPONENT, 5.0, 26.0,
                    glyph="RV", accent=Color.P2))
    add("pu.slowball", "SLOW FIELD", 1200, Rarity.RARE,
        "Drop the whole ball to 0.65x speed for 6 seconds.",
        PowerupSpec(PowerEffect.SLOW_BALL, PowerTarget.GLOBAL, 6.0, 20.0,
                    magnitude=0.65, glyph="SL", accent=Color.GOLD))

    return tuple(out)


#: Which category each id belongs to (used while building the catalog).
_CATEGORY_OF: dict[str, ShopCategory] = {}


def _category_prefixes() -> tuple[tuple[str, ShopCategory], ...]:
    return (
        ("ball.", ShopCategory.BALL),
        ("paddle.", ShopCategory.PADDLE),
        ("bg.", ShopCategory.BACKGROUND),
        ("trail.", ShopCategory.TRAIL),
        ("impact.", ShopCategory.IMPACT),
        ("pu.", ShopCategory.POWERUP),
    )


for _item_id in (
    "ball.classic", "ball.crimson", "ball.mint", "ball.ember", "ball.frost",
    "ball.rose", "ball.violet", "ball.solar", "ball.obsidian", "ball.arcane",
    "paddle.classic", "paddle.carbon", "paddle.sunset", "paddle.jade",
    "paddle.royal", "paddle.gold", "paddle.neon", "paddle.glitch",
    "bg.classic", "bg.grid", "bg.aurora", "bg.sunset", "bg.candy", "bg.void",
    "bg.arcade", "bg.noir",
    "trail.classic", "trail.comet", "trail.ember", "trail.ice",
    "trail.ribbon", "trail.spark", "trail.aurora", "trail.plasma",
    "impact.classic", "impact.ring", "impact.shards", "impact.confetti",
    "impact.ink", "impact.stars", "impact.aurora", "impact.prism",
    "pu.none", "pu.overdrive", "pu.giant", "pu.magnet", "pu.fireball",
    "pu.shield", "pu.goldrush", "pu.freezeray", "pu.shrinkray",
    "pu.reverser", "pu.slowball",
):
    for _prefix, _category in _category_prefixes():
        if _item_id.startswith(_prefix):
            _CATEGORY_OF[_item_id] = _category
            break
    else:  # pragma: no cover - guards the catalog against typos
        raise AssertionError(f"no category prefix matched {_item_id!r}")


#: Every item, in catalog order (category-major).
ITEMS: tuple[ShopItem, ...] = _items()

#: Fast id lookup built alongside the tuple.
ITEMS_BY_ID: dict[str, ShopItem] = {item.id: item for item in ITEMS}

if len(ITEMS_BY_ID) != len(ITEMS):  # pragma: no cover - catalog typo guard
    raise AssertionError("duplicate item id in the shop catalog")

#: The item each category ships with: always free, always owned, equipped on a
#: fresh profile.  Listed explicitly rather than derived from catalog order so
#: reordering (or adding) entries cannot silently change the starter loadout.
_DEFAULT_IDS: dict[ShopCategory, str] = {
    ShopCategory.BALL: "ball.classic",
    ShopCategory.PADDLE: "paddle.classic",
    ShopCategory.BACKGROUND: "bg.classic",
    ShopCategory.TRAIL: "trail.classic",
    ShopCategory.IMPACT: "impact.classic",
    ShopCategory.POWERUP: "pu.overdrive",
}

for _category, _default_id in _DEFAULT_IDS.items():  # pragma: no cover guard
    _default = ITEMS_BY_ID.get(_default_id)
    if _default is None or not _default.free or _default.category is not _category:
        raise AssertionError(
            f"default item {_default_id!r} must exist, be free, be a {_category}")


def items_in(category: ShopCategory) -> tuple[ShopItem, ...]:
    """All items belonging to ``category``, cheapest-first.

    ``sorted`` is stable, so equal prices keep catalog order - a free
    starter item is therefore always the first row a player sees.
    """
    return tuple(sorted((item for item in ITEMS if item.category is category),
                        key=lambda item: item.price))


def default_item(category: ShopCategory) -> ShopItem:
    """The designated starter item for ``category``."""
    try:
        item_id = _DEFAULT_IDS[category]
    except KeyError:  # pragma: no cover - guarded by the import-time check
        raise AssertionError(f"no default item for {category}") from None
    item = ITEMS_BY_ID.get(item_id)
    if item is None or not item.free or item.category is not category:
        raise AssertionError(f"bad default item {item_id!r}")  # pragma: no cover
    return item


def get_item(item_id: str) -> ShopItem:
    """Look up an item by id.

    Raises:
        KeyError: the id is not in the catalog (e.g. a stale save file).
    """
    return ITEMS_BY_ID[item_id]


def has(item_id: str) -> bool:
    return item_id in ITEMS_BY_ID


#: Total price of buying the entire catalog - a long-term goal for the wallet.
CATALOG_TOTAL: int = sum(item.price for item in ITEMS)


__all__ = [
    "RGB",
    "ShopCategory",
    "CATEGORIES",
    "Rarity",
    "RARITY_COLORS",
    "BallPattern",
    "BallLook",
    "PaddlePattern",
    "PaddleLook",
    "BackdropStyle",
    "BackgroundLook",
    "TrailStyle",
    "TrailLook",
    "ImpactStyle",
    "ImpactLook",
    "PowerEffect",
    "PowerTarget",
    "PowerupSpec",
    "ShopItem",
    "ITEMS",
    "ITEMS_BY_ID",
    "CATALOG_TOTAL",
    "items_in",
    "get_item",
    "default_item",
    "has",
]
