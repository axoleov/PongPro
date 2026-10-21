"""Global tuning constants and the colour palette.

Everything that both gameplay *and* rendering need to agree on lives here.
Values are expressed in *logical* pixels at the fixed 16:9 design resolution;
the video layer scales them to the real window.
"""

from __future__ import annotations

from enum import Enum

# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------
PHYSICS_HZ: int = 120
FIXED_DT: float = 1.0 / PHYSICS_HZ
#: Upper bound applied to a single measured frame time (anti spiral-of-death).
MAX_FRAME_TIME: float = 0.25
#: Hard ceiling on physics sub-steps executed inside one rendered frame.
MAX_SUBSTEPS: int = 8

# --------------------------------------------------------------------------
# Logical resolution & court geometry
# --------------------------------------------------------------------------
LOGICAL_W: int = 1280
LOGICAL_H: int = 720

COURT_PAD_X: int = 96  # distance from screen edge to the play-line
COURT_PAD_Y: int = 64  # distance from screen edge to the top/bottom walls

PADDLE_W: int = 16
PADDLE_H: int = 116
#: Distance from the play-line to each paddle's centre.
PADDLE_INSET: int = 34
#: How far below the countdown the ball is parked before serve.
SERVE_PARK_OFFSET: int = 0
PADDLE_SPEED: float = 640.0  # px/s
PADDLE_ACCEL: float = 5200.0  # px/s^2
PADDLE_FRICTION: float = 6200.0  # px/s^2 when gliding with no input

BALL_RADIUS: int = 11

# --------------------------------------------------------------------------
# Ball physics
# --------------------------------------------------------------------------
BASE_BALL_SPEED: float = 430.0
MAX_BALL_SPEED: float = 1150.0
#: Multiplicative speed-up applied to the ball after every paddle contact.
RALLY_SPEEDUP: float = 1.035
#: Maximum deflection angle (degrees) measured at the paddle edge.
MAX_DEFLECT_DEG: float = 62.0
#: Fraction of the paddle's own velocity transferred to the ball ("english").
ENGLISH_FACTOR: float = 0.30
#: Guard band above/below the paddle where a hit is still registered.
PADDLE_TOLERANCE: int = 2

# --------------------------------------------------------------------------
# Match rules
# --------------------------------------------------------------------------
DEFAULT_TARGET_SCORE: int = 5
SERVE_DELAY: float = 1.35  # seconds of "READY .. GO" before the ball launches
GOAL_PAUSE: float = 1.15  # seconds of celebration/slowdown after a point
HIT_STOP_SECONDS: float = 0.055  # freeze frames injected on goals
COUNTDOWN_TICKS: int = 3

# --------------------------------------------------------------------------
# FOCUS mode (one player drives both paddles; there is no opponent)
#
# FOCUS is the odd one out in the rules layer: nobody scores, so "First to N"
# stops meaning points and starts meaning *lives*.  Everything below exists to
# describe how a run differs from a match, and nothing else.
# --------------------------------------------------------------------------
#: Fraction of its speed the ball keeps after a life is lost.  A *partial*
#: reset rather than a full one: a fresh game after every mistake would make
#: late lives no harder than the first, while a full reset would turn life 4
#: into an unwinnable sprint at MAX_BALL_SPEED.  At 0.70 a run that reached
#: 900 px/s re-serves at 630 and has to earn its speed back.
FOCUS_SPEED_RECOVERY: float = 0.70
#: Serve countdown used *after* a life is lost - shorter than the opening
#: countdown because the player is already warm and only needs to re-seat
#: both hands.  The opening countdown still uses SERVE_DELAY like every mode.
FOCUS_SERVE_DELAY: float = 1.05
#: Seconds of live play before the first life orb appears.  The player has to
#: survive long enough for the orb to be a reward rather than a tutorial.
FOCUS_LIFE_FIRST_DELAY: float = 30.0
#: Range of live-play seconds between life orbs after the first.  Rare on
#: purpose: an orb should feel like something worth steering *towards*.
FOCUS_LIFE_GAP_MIN: float = 45.0
FOCUS_LIFE_GAP_MAX: float = 60.0
#: Coins paid when an orb is collected at full health, where it cannot grant
#: a life.  Still worth steering for, but no longer the reason to steer.
FOCUS_LIFE_BONUS: int = 25

# --------------------------------------------------------------------------
# Colour palette (dark neon, deuteranopia-friendly separation)
# --------------------------------------------------------------------------
class Color:
    """Palette constants - kept as tuples so they can be passed to pygame."""

    BG = (10, 12, 20)
    PANEL = (20, 25, 40)
    PANEL_LIGHT = (30, 38, 58)
    COURT = (16, 20, 33)
    LINE = (74, 92, 132)
    LINE_SOFT = (44, 56, 86)
    P1 = (86, 226, 255)  # cyan  - left player
    P2 = (255, 118, 196)  # pink  - right player
    BALL = (255, 240, 130)  # yellow
    TEXT = (236, 241, 255)
    TEXT_DIM = (150, 162, 190)
    ACCENT = (120, 255, 186)  # green
    WARN = (255, 122, 122)  # red
    GOLD = (255, 205, 92)
    SHADOW = (0, 0, 0)

    @classmethod
    def blend(cls, a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
        """Linearly interpolate two RGB tuples; ``t`` in [0, 1]."""
        t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
        return (int(a[0] + (b[0] - a[0]) * t),
                int(a[1] + (b[1] - a[1]) * t),
                int(a[2] + (b[2] - a[2]) * t))


class MatchPhase(str, Enum):
    """High level state of a single match."""

    COUNTDOWN = "countdown"  # pre-serve countdown / banner
    SERVE = "serve"  # ball parked, waiting for launch
    PLAYING = "playing"
    GOAL = "goal"  # point scored, short celebration
    MATCH_OVER = "match_over"


class GameMode(str, Enum):
    """Who controls each paddle."""

    SOLO = "solo"  # human left vs AI right
    TWO_PLAYER = "two_player"  # two humans
    AI_VS_AI = "ai_vs_ai"  # attract / demo mode
    #: One human drives *both* paddles against no opponent at all.  The ball
    #: must simply be kept alive: there is no scoring, lives replace points,
    #: and the shop's powerups are switched off (cosmetics still apply).
    FOCUS = "focus"


class Difficulty(str, Enum):
    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"
    ELITE = "elite"


class ParticleQuality(str, Enum):
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
