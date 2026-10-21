"""Match rules: scoring, serving, countdown, deuce, hit-stop, win detection.

:class:`Match` is a pure state machine.  It never touches rendering; it simply
tells the rest of the game *what phase we are in* and returns the events that
occurred during a step so the audio/presentation layer can react via the bus.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.constants import (
    GOAL_PAUSE,
    HIT_STOP_SECONDS,
    SERVE_DELAY,
    Difficulty,
    FOCUS_SERVE_DELAY,
    GameMode,
    MatchPhase,
)
from ..core.events import EventBus, EventType, GameEvent
from .focus import FocusRun

#: Absolute ceiling so a pathological deuce cannot run forever.
SUDDEN_DEATH_SCORE = 30


@dataclass(slots=True)
class MatchConfig:
    mode: GameMode = GameMode.SOLO
    target_score: int = 5
    difficulty: Difficulty = Difficulty.NORMAL
    rally_speedup: bool = True
    english: bool = True
    serve_delay: float = SERVE_DELAY
    goal_pause: float = GOAL_PAUSE
    random_first_server: bool = True
    #: Countdown used after a FOCUS concession.  Unused by every other mode.
    focus_serve_delay: float = FOCUS_SERVE_DELAY


@dataclass(slots=True)
class MatchStats:
    """Post-match summary used by the results screen and the profile."""

    longest_rally: int = 0
    total_hits: int = 0
    total_goals: int = 0
    fastest_ball: float = 0.0
    duration: float = 0.0
    hits_by_player: tuple[int, int] = (0, 0)
    goals_by_player: tuple[int, int] = (0, 0)
    #: FOCUS only: lives still in hand when the run ended.  Zero in a duel,
    #: where lives are not a concept.
    lives_left: int = 0


class Match:
    """Owns score, phase timers and win conditions for one game."""

    def __init__(self, config: MatchConfig, bus: EventBus) -> None:
        self.config = config
        self.bus = bus
        self.phase = MatchPhase.COUNTDOWN
        self.score = [0, 0]
        self.rally = 0  # hits in the current point
        self.server = 0  # 0 = left, 1 = right
        self.timer = 0.0
        self.hit_stop = 0.0
        self.winner: int | None = None
        self.stats = MatchStats()
        self.last_scorer: int | None = None
        self.match_over = False
        self._last_count_label: str | None = None
        self._match_point_announced = False
        self._banner = "READY"
        self._banner_timer = 0.0
        self._goal_presentation: tuple[int, str] | None = None
        #: Length of the countdown currently running, so ``countdown_label``
        #: divides by the *actual* slice length once a FOCUS concession swaps
        #: in its shorter one.
        self._serve_total = config.serve_delay

        # FOCUS spends lives instead of points; every other mode never has a
        # life budget at all and leaves this None.
        if config.mode is GameMode.FOCUS:
            self.focus: FocusRun | None = FocusRun(
                lives=config.target_score, max_lives=config.target_score)
            self.stats.lives_left = config.target_score
        else:
            self.focus = None

        if config.random_first_server:
            # Deterministic callers (replay) set this after construction.
            self.server = 0
        self.begin_countdown()

    # -- phase control ----------------------------------------------------
    def begin_countdown(self, server: int | None = None, *,
                        serve_delay: float | None = None) -> None:
        """Park everything for a serve.  ``serve_delay`` overrides the length.

        A FOCUS concession asks for the shorter delay: the player is already
        warm and only needs a beat to re-seat both hands, where the opening
        countdown also teaches which keys do what.
        """
        if server is not None:
            self.server = server
        self.phase = MatchPhase.COUNTDOWN
        self._serve_total = (self.config.serve_delay if serve_delay is None
                             else max(0.0, float(serve_delay)))
        self.timer = self._serve_total
        self.rally = 0
        self._last_count_label = None
        self._match_point_announced = False
        self._set_banner("READY", self._serve_total)
        self.bus.emit(EventType.PHASE_CHANGED, {"phase": self.phase.value})

    def countdown_label(self) -> str | None:
        """``'3' | '2' | '1' | None`` for the big serve countdown."""
        if self.phase is not MatchPhase.COUNTDOWN:
            return None
        slice_len = max(1e-3, self._serve_total / 3.0)
        index = int(self.timer / slice_len) + 1
        index = max(1, min(3, index))
        return str(index)

    @property
    def banner(self) -> str | None:
        if self._banner_timer > 0.0:
            return self._banner
        if self.phase is MatchPhase.MATCH_OVER:
            if self.winner is not None:
                return "PLAYER {} WINS".format(self.winner + 1)
            # FOCUS ends with no winner at all, so the closing banner has to
            # come from the run itself - otherwise the last seconds before the
            # results screen would go blank.
            if self.focus is not None:
                return "RUN OVER"
        return None

    def _set_banner(self, text: str, duration: float) -> None:
        self._banner = text
        self._banner_timer = duration

    # -- scoring ----------------------------------------------------------
    @property
    def match_point_for(self) -> int | None:
        """Player index that would win by scoring the next point, else None."""
        for i, mine in enumerate(self.score):
            if self._wins_with(mine + 1, self.score[1 - i]):
                return i
        return None

    def _wins_with(self, mine: int, other: int) -> bool:
        """Would ``mine``-``other`` end the match?

        Reaches the target outright unless the opponent is already in the
        deuce zone (``target - 1`` or more), in which case a 2-point lead is
        required.  The sudden-death ceiling stops pathological deuces.
        """
        target = self.config.target_score
        if mine < target:
            return False
        if target <= 1 or mine >= SUDDEN_DEATH_SCORE:
            return True
        if other < target - 1:
            return True
        return (mine - other) >= 2

    def _is_win(self, player: int) -> bool:
        return self._wins_with(self.score[player], self.score[1 - player])

    def is_deuce(self) -> bool:
        target = self.config.target_score
        if target < 2:
            return False
        return self.score[0] >= target - 1 and self.score[1] >= target - 1

    def on_goal(self, scorer: int, ball_speed: float) -> list[GameEvent]:
        """Award a point. Returns the events to publish for this step."""
        if self.match_over or scorer not in (0, 1):
            return []
        events: list[GameEvent] = []
        self.score[scorer] += 1
        self.last_scorer = scorer
        self.stats.total_goals += 1
        # ``total_hits`` is tallied per contact in ``on_paddle_hit``; adding
        # the rally here again counted every return twice (and inflated the
        # coin bonus, which is scaled off this figure).
        goals = list(self.stats.goals_by_player)
        goals[scorer] += 1
        self.stats.goals_by_player = (goals[0], goals[1])

        events.append(GameEvent(EventType.GOAL, {
            "scorer": scorer, "rally": self.rally,
            "score": tuple(self.score), "speed": ball_speed,
        }))
        self._set_banner("GOAL!", self.config.goal_pause)
        self.hit_stop = HIT_STOP_SECONDS

        if self._is_win(scorer):
            self.winner = scorer
            self.match_over = True
            self.phase = MatchPhase.MATCH_OVER
            self.timer = 0.0
            events.append(GameEvent(EventType.MATCH_END, {
                "winner": scorer, "score": tuple(self.score),
                "stats": self.stats,
            }))
            self.bus.emit(EventType.PHASE_CHANGED, {"phase": self.phase.value})
            return events

        # Next server: the player who conceded serves (classic alternation).
        self.server = 1 - scorer
        self.phase = MatchPhase.GOAL
        self.timer = self.config.goal_pause
        self.rally = 0
        self._goal_presentation = (scorer, "point")
        self.bus.emit(EventType.PHASE_CHANGED, {"phase": self.phase.value})

        if self.match_point_for is not None:
            events.append(GameEvent(EventType.MATCH_POINT, {
                "player": self.match_point_for,
                "score": tuple(self.score),
            }))
        return events

    def on_concede(self, side: int, ball_speed: float,
                   serve_side: int) -> list[GameEvent]:
        """FOCUS only: one of the player's own paddles was beaten.

        The mirror image of :meth:`on_goal` with everything that only makes
        sense between two opponents stripped out.  Nobody scores, so the ball
        exiting either end simply spends a life; ``side`` records *which hand
        failed* purely so the presentation can tell the player what to fix.

        ``serve_side`` is the side the re-serve travels toward.  The scene
        picks it at random rather than defaulting to the side that conceded,
        because a run should not systematically punish the same hand twice.

        Returns:
            The events to publish.  Empty outside FOCUS (or once the run is
            already over), so a stray call can never double-spend a life.
        """
        if self.match_over or self.focus is None or side not in (0, 1):
            return []
        focus = self.focus
        events: list[GameEvent] = []

        self.last_scorer = side
        self.stats.total_goals += 1
        # Returns are tallied per contact in ``on_paddle_hit``; the rally is
        # *not* added again here (see ``on_goal`` - doing so counted every
        # return twice and inflated the coin bonus scaled off this figure).
        goals = list(self.stats.goals_by_player)
        goals[side] += 1
        self.stats.goals_by_player = (goals[0], goals[1])

        self.hit_stop = HIT_STOP_SECONDS
        ended = focus.concede()
        self.stats.lives_left = focus.lives
        self.rally = 0

        events.append(GameEvent(EventType.GOAL, {
            "side": side, "scorer": side, "rally": 0,
            "score": tuple(self.score), "speed": ball_speed,
            "lives": focus.lives, "ended": ended,
        }))

        if ended:
            # No winner to announce: the run simply stopped.  ``winner`` stays
            # None, which is what tells the results screen to headline it as
            # a run rather than a victory or a defeat.
            self.winner = None
            self.match_over = True
            self.phase = MatchPhase.MATCH_OVER
            self.timer = 0.0
            self._set_banner("RUN OVER", self.config.goal_pause)
            events.append(GameEvent(EventType.MATCH_END, {
                "winner": None, "score": tuple(self.score), "stats": self.stats,
            }))
            self.bus.emit(EventType.PHASE_CHANGED, {"phase": self.phase.value})
            return events

        self._set_banner("LAST LIFE" if focus.last_life else "LIFE LOST",
                         self.config.goal_pause)
        self.server = serve_side
        self.phase = MatchPhase.GOAL
        self.timer = self.config.goal_pause
        self._goal_presentation = (side, "life")
        self.bus.emit(EventType.PHASE_CHANGED, {"phase": self.phase.value})
        return events

    def on_paddle_hit(self, player: int, new_speed: float) -> list[GameEvent]:
        """Record a successful return; emits MATCH_POINT when appropriate."""
        if self.match_over:
            return []
        self.rally += 1
        self.stats.total_hits += 1
        self.stats.longest_rally = max(self.stats.longest_rally, self.rally)
        self.stats.fastest_ball = max(self.stats.fastest_ball, new_speed)
        hits = list(self.stats.hits_by_player)
        hits[player] += 1
        self.stats.hits_by_player = (hits[0], hits[1])

        events = [GameEvent(EventType.BALL_HIT_PADDLE, {
            "player": player, "rally": self.rally, "speed": new_speed,
        })]
        match_point = self.match_point_for
        if match_point is not None and not self._match_point_announced:
            self._match_point_announced = True
            events.append(GameEvent(EventType.MATCH_POINT, {
                "player": match_point, "score": tuple(self.score),
            }))
        return events

    def on_wall_hit(self, speed: float) -> list[GameEvent]:
        return [GameEvent(EventType.BALL_HIT_WALL, {"speed": speed})]

    # -- stepping ---------------------------------------------------------
    def update(self, dt: float) -> list[GameEvent]:
        """Advance phase timers by one fixed step."""
        events: list[GameEvent] = []
        self.stats.duration += dt if self.phase is MatchPhase.PLAYING else 0.0
        if self._banner_timer > 0.0:
            self._banner_timer = max(0.0, self._banner_timer - dt)
        if self.hit_stop > 0.0:
            self.hit_stop = max(0.0, self.hit_stop - dt)

        if self.phase is MatchPhase.COUNTDOWN:
            self.timer -= dt
            label = self.countdown_label()
            if label != self._last_count_label:
                self._last_count_label = label
                events.append(GameEvent(EventType.SERVE, {
                    "countdown": label, "server": self.server,
                }))
            if self.timer <= 0.0:
                self.phase = MatchPhase.PLAYING
                self.timer = 0.0
                self._set_banner("GO!", 0.35)
                self.bus.emit(EventType.PHASE_CHANGED, {"phase": self.phase.value})
                events.append(GameEvent(EventType.SERVE, {"launch": True,
                                                          "server": self.server}))
        elif self.phase is MatchPhase.GOAL:
            self.timer -= dt
            if self.timer <= 0.0:
                # FOCUS re-serves on a shorter beat: the player is already at
                # the keyboard and only needs a moment to reset both hands.
                self.begin_countdown(
                    serve_delay=(self.config.focus_serve_delay
                                 if self.focus is not None else None))
        elif self.phase is MatchPhase.MATCH_OVER:
            self.timer += dt
        return events

    # -- helpers ----------------------------------------------------------
    @property
    def is_playing(self) -> bool:
        """True when the ball should actually be simulated."""
        return self.phase is MatchPhase.PLAYING

    @property
    def physics_frozen(self) -> bool:
        """Hit-stop freeze frames pause simulation but not rendering."""
        return self.hit_stop > 0.0

    @property
    def presentation(self) -> tuple[int, str] | None:
        """``(scorer, 'point')`` exactly once for the frame a goal happened."""
        value = self._goal_presentation
        self._goal_presentation = None
        return value

    def score_string(self) -> str:
        return f"{self.score[0]} - {self.score[1]}"

    def time_label(self) -> str:
        # round(), not int(): a full 2.00s of steps sums to 1.9999... in
        # floating point and must not display as 00:01.
        total = int(round(self.stats.duration))
        return f"{total // 60:02d}:{total % 60:02d}"


def build_config(mode: GameMode, difficulty: Difficulty, target: int,
                 rally_speedup: bool, english: bool) -> MatchConfig:
    """Convenience factory used by the gameplay scene."""
    return MatchConfig(
        mode=mode,
        target_score=target,
        difficulty=difficulty,
        rally_speedup=rally_speedup,
        english=english,
    )
