"""The match scene: input, simulation, FX, HUD, recording and transitions.

Responsibility split (deliberate):

* :class:`~pongpro.gameplay.match.Match` owns *rules* (score/phase/win),
* :mod:`pongpro.gameplay.physics` owns *contact maths*,
* this scene owns *orchestration*: it pumps input into paddles, steps the
  ball, turns physical contacts into presentation (sound/particles/shake),
  and records every tick for replay.
"""

from __future__ import annotations

import dataclasses
import logging
import math

import pygame

from ..core.constants import (
    BASE_BALL_SPEED,
    BALL_RADIUS,
    Color,
    FOCUS_LIFE_BONUS,
    LOGICAL_H,
    LOGICAL_W,
    MAX_BALL_SPEED,
    MAX_DEFLECT_DEG,
    PADDLE_W,
    PHYSICS_HZ,
    Difficulty,
    GameMode,
    MatchPhase,
)
from ..core.events import EventBus, EventType, GameEvent
from ..core.rng import Rng
from ..core.state_machine import Scene, Transition
from ..economy.catalog import (
    BackgroundLook,
    BallLook,
    ImpactLook,
    PaddleLook,
    PowerEffect,
    ShopCategory,
    TrailLook,
    get_item,
)
from ..economy.wallet import (
    Wallet,
    focus_reward,
    get_wallet,
    match_reward,
    save_wallet,
)
from ..gameplay.ai import PRESETS, AIController
from ..gameplay.entities import Ball, Court, Paddle, default_court
from ..gameplay.focus import LIFE_ORB, life_orb_field
from ..gameplay.match import Match, MatchConfig
from ..gameplay.physics import next_paddle_speed, resolve_walls, try_paddle_contact
from ..gameplay.bubbles import BubbleField, PowerupBubble
from ..gameplay.powerups import (
    Disoriented,
    PowerupSystem,
    apply_magnet,
    choose_powerup,
    owned_powerups,
)
from ..gameplay.replay import ReplayRecorder
from ..rendering.camera import Camera
from ..rendering.hud import CONTROL_HINT_Y, Hud
from ..rendering.particles import ParticleSystem
from ..rendering.skins import (
    CLASSIC_BACKGROUND,
    draw_ball,
    draw_paddle,
    draw_trail,
    emit_impact,
    glow_sprite,
)
from .common import format_duration, render_court

log = logging.getLogger(__name__)

RESULTS_DELAY = 2.6  # seconds between MATCH_OVER and the results screen
HINT_SECONDS = 7.0

#: Seconds the pickup takes to bloom in from nothing when it spawns.
BUBBLE_FADE_IN = 0.45
#: Seconds of warning before a pickup expires, over which it fades back out so
#: a bubble never simply vanishes from under the player.
BUBBLE_FADE_OUT = 1.50
#: Amplitude of the pickup's idle bob, in logical pixels.  Deliberately small:
#: the bubble is a *target*, so it should hover, not swim.
BUBBLE_BOB = 3.0
#: Outer radius of the halo, as a multiple of the pickup's own radius.
BUBBLE_HALO = 1.9


class GameplayScene(Scene):
    """One match of Pong."""

    opaque = True

    def __init__(self, *, mode: GameMode, difficulty: Difficulty,
                 target_score: int, rally_speedup: bool = True,
                 english: bool = True, seed: int | None = None) -> None:
        super().__init__()
        self.mode = mode
        self.difficulty = difficulty
        self.target_score = target_score
        self.rally_speedup = rally_speedup
        self.english = english
        self.seed = seed if seed is not None else Rng().seed

        # world ---------------------------------------------------------
        self.court: Court = default_court()
        self.p1 = Paddle(True, self.court)
        self.p2 = Paddle(False, self.court)
        self.ball = Ball(self.court)
        self.rng = Rng(self.seed)
        # Replaced in on_enter (where the real event bus is available); here we
        # just need a valid object so attributes always exist.
        self.match = Match(MatchConfig(
            mode=mode, target_score=target_score, difficulty=difficulty,
            rally_speedup=rally_speedup, english=english,
        ), EventBus())

        # presentation --------------------------------------------------
        self.particles: ParticleSystem | None = None
        self.camera: Camera | None = None
        self.hud: Hud | None = None
        self.recorder = ReplayRecorder()
        self.ai_left: AIController | None = None
        self.ai_right: AIController | None = None

        self._world: pygame.Surface | None = None
        self._court_surface: pygame.Surface | None = None
        self._glow_ball: pygame.Surface | None = None
        self._glow_p1: pygame.Surface | None = None
        self._glow_p2: pygame.Surface | None = None

        # Cosmetic loadout (resolved from the wallet in ``on_enter``).
        self.ball_look: BallLook = get_item("ball.classic").data
        self.paddle_look: PaddleLook = get_item("paddle.classic").data
        self.background_look: BackgroundLook = CLASSIC_BACKGROUND
        self.trail_look: TrailLook = get_item("trail.classic").data
        self.impact_look: ImpactLook = get_item("impact.classic").data
        #: Live coins banked during the match (Gold Rush), added to the
        #: match-end award so a crash before the results screen costs them.
        self._live_coins = 0

        self._trail: list[list[float]] = []
        self._trail_tick = 0
        self._prev_phase = MatchPhase.COUNTDOWN
        self._phase_since = 0.0
        self._rec_time = 0.0
        self._hint_timer = HINT_SECONDS
        self._results_pushed = False
        self._debug_ai = False
        self._unsubs: list = []
        self._results_payload: dict | None = None
        self.wallet: Wallet | None = None
        self.powerups = PowerupSystem()
        #: Shop display name of each paddle's held powerup (per side).
        self.powerup_names: list[str] = ["", ""]
        #: Mid-match powerup pickups; built in ``on_enter`` once the wallet
        #: tells us which powerups this profile actually owns.
        self.bubbles: BubbleField | None = None
        #: Side whose paddle last returned the ball.  A bubble only pays out
        #: to a side that has actually been *rallied* with.
        self._last_paddle: int | None = None
        #: Per-side disorientation for bot-driven paddles under REVERSER.
        self._disorient: list[Disoriented] = [Disoriented(Rng()), Disoriented(Rng())]
        #: Ball-speed multiplier currently folded into the live velocity, so
        #: expiring Slow Field restores the original speed exactly.
        self._applied_slow = 1.0
        #: Speed the next serve launches at.  Base speed in a duel; a FOCUS
        #: run swaps in its partially-reset figure after a life is lost, so
        #: the ladder picks up from there instead of from scratch.
        self._next_serve_speed = BASE_BALL_SPEED

    # -- lifecycle --------------------------------------------------------
    @property
    def params(self) -> dict:
        """Serializable description used to rebuild this match."""
        return {
            "mode": self.mode,
            "difficulty": self.difficulty,
            "target_score": self.target_score,
            "rally_speedup": self.rally_speedup,
            "english": self.english,
        }

    def on_enter(self, **kwargs) -> None:
        ctx = self.ctx
        self.court = default_court()
        self.p1 = Paddle(True, self.court)
        self.p2 = Paddle(False, self.court)
        self.ball = Ball(self.court)
        self.rng = Rng(self.seed)
        self.match = Match(MatchConfig(
            mode=self.mode,
            target_score=self.target_score,
            difficulty=self.difficulty,
            rally_speedup=self.rally_speedup,
            english=self.english,
        ), ctx.bus)

        self.particles = ParticleSystem(self.rng.fork(),
                                        ctx.settings.video.particles)
        self.camera = Camera(self.rng.fork(),
                             enabled=ctx.settings.video.screen_shake)
        self.hud = Hud(ctx.fonts)

        # Cosmetic + powerup loadout -------------------------------------
        self.wallet = get_wallet(ctx)
        self.ball_look = self.wallet.equipped_item(ShopCategory.BALL).data
        self.paddle_look = self.wallet.equipped_item(ShopCategory.PADDLE).data
        self.background_look = self.wallet.equipped_item(
            ShopCategory.BACKGROUND).data
        self.trail_look = self.wallet.equipped_item(ShopCategory.TRAIL).data
        self.impact_look = self.wallet.equipped_item(ShopCategory.IMPACT).data
        self._live_coins = 0
        self._applied_slow = 1.0
        self._next_serve_speed = BASE_BALL_SPEED
        self._assign_powerups()
        self._last_paddle = None

        # Opponents -----------------------------------------------------
        preset = PRESETS[self.difficulty]
        if self.mode in (GameMode.SOLO, GameMode.AI_VS_AI):
            self.ai_right = AIController(self.p2, preset, self.rng.fork())
        else:
            self.ai_right = None
        if self.mode is GameMode.AI_VS_AI:
            self.ai_left = AIController(self.p1, preset, self.rng.fork())
        else:
            self.ai_left = None

        # Static art ----------------------------------------------------
        self._world = pygame.Surface((LOGICAL_W, LOGICAL_H))
        self._court_surface = render_court(self.court, self.background_look)
        self._glow_ball = glow_sprite(self.ball_look.fill, 64)
        self._glow_p1 = glow_sprite(Color.P1, 48)
        self._glow_p2 = glow_sprite(Color.P2, 48)

        # Recording -----------------------------------------------------
        self.recorder.start({
            "label": self._label(),
            "mode": self.mode.value,
            "difficulty": self.difficulty.value,
            "seed": self.seed,
            "target": self.target_score,
            "fps": PHYSICS_HZ,
        })

        # Events --------------------------------------------------------
        bus = ctx.bus
        self._unsubs = [
            bus.subscribe(EventType.BALL_HIT_PADDLE, self._fx_paddle),
            bus.subscribe(EventType.BALL_HIT_WALL, self._fx_wall),
            bus.subscribe(EventType.SERVE, self._fx_serve),
            bus.subscribe(EventType.MATCH_POINT, self._fx_match_point),
            bus.subscribe(EventType.MATCH_END, self._fx_match_end),
        ]

        self._trail.clear()
        self._prev_phase = MatchPhase.COUNTDOWN
        self._phase_since = 0.0
        self._rec_time = 0.0
        self._hint_timer = HINT_SECONDS
        self._results_pushed = False
        self._results_payload = None
        log.info("Match start: %s (seed=%d)", self._label(), self.seed)

    def on_exit(self) -> None:
        for unsubscribe in self._unsubs:
            unsubscribe()
        self._unsubs.clear()

    def on_resume(self) -> None:
        # Coming back from pause/settings: drop any accumulated frame time.
        self._hint_timer = max(self._hint_timer, 1.5)

    def _loadout_ids(self) -> dict[str, str]:
        """Cosmetics worn for this match, as catalog ids, one per category."""
        if self.wallet is None:
            return {}
        return {category.value: self.wallet.equipped_id(category)
                for category in ShopCategory}

    def _assign_powerups(self) -> None:
        """Give each paddle the powerup it will play this match.

        A human always gets the profile's equipped powerup.  A bot instead
        draws one at random from the profile's *own collection* - in AI-vs-AI
        both bots draw - so the machine is never simply handed the player's
        choice.  The draw can still coincide with it, but only by luck.

        Two-player keeps sharing the equipped spec, which preserves the
        original symmetric duel: both humans pick the same move and spend it.

        FOCUS is the exception and holds nothing at all: a timed modifier is
        a decision about *which* player it helps, and there is only one player
        here.  Leaving both paddles on the blank spec is what switches the
        whole subsystem off - no binding, no pill, no shield, no magnet - and
        the pickup field carries the life orb instead of shop powerups.
        Cosmetics are resolved separately in ``on_enter``, so equipped balls
        and trails still apply.
        """
        wallet = self.wallet
        assert wallet is not None

        if self.mode is GameMode.FOCUS:
            self.powerups = PowerupSystem()
            self.powerup_names = ["", ""]
            self.bubbles = life_orb_field(self.court, self.rng.fork())
            self._disorient = [Disoriented(self.rng.fork()),
                               Disoriented(self.rng.fork())]
            log.info("Powerups: disabled (FOCUS) - life orb only")
            return

        equipped = wallet.equipped_item(ShopCategory.POWERUP)

        if self.mode is GameMode.AI_VS_AI:
            picker = self.rng.fork()
            left, right = (choose_powerup(wallet, picker),
                           choose_powerup(wallet, picker))
        elif self.mode is GameMode.SOLO:
            left, right = equipped, choose_powerup(wallet, self.rng.fork())
        else:
            left = right = equipped

        self.powerups = PowerupSystem()
        self.powerups.set_held(0, left.data, left.name)
        self.powerups.set_held(1, right.data, right.name)
        self.powerup_names = [left.name, right.name]
        log.info("Powerups: P1=%s  P2=%s", left.id, right.id)

        # Pickups draw from the same collection, so buying powerups also makes
        # richer bubbles appear mid-match.
        self.bubbles = BubbleField(owned_powerups(wallet), self.court,
                                   self.rng.fork())

        # Fresh disorientation state, forked off the match seed so a rematch
        # behaves differently without breaking replay determinism.
        self._disorient = [Disoriented(self.rng.fork()),
                           Disoriented(self.rng.fork())]

    def _label(self) -> str:
        if self.mode is GameMode.FOCUS:
            # "First to N" means N *lives* here, so say so rather than
            # printing a points target the HUD will never show.
            return f"FOCUS · {self.target_score} LIVES"
        if self.mode is GameMode.TWO_PLAYER:
            return f"2 PLAYERS · FIRST TO {self.target_score}"
        if self.mode is GameMode.AI_VS_AI:
            return (f"AI vs AI · {self.difficulty.value.upper()} · "
                    f"FIRST TO {self.target_score}")
        return (f"1P vs AI · {self.difficulty.value.upper()} · "
                f"FIRST TO {self.target_score}")

    # -- input ------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_ESCAPE, pygame.K_p):
            self._open_pause()
        elif event.key == pygame.K_F2:
            self._debug_ai = not self._debug_ai
        elif self.powerups.enabled and not self.match.physics_frozen:
            # SPACE fires P1's powerup, RETURN the right-hand paddle's.  AI
            # paddles are driven from `_update_powerups` instead, so keys for
            # a bot-controlled side are ignored here.
            if event.key == pygame.K_SPACE and self.ai_left is None \
                    and self.mode is not GameMode.AI_VS_AI:
                self._fire_powerup(0)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) \
                    and self.ai_right is None:
                self._fire_powerup(1)

    def _open_pause(self) -> None:
        if self.match.match_over:
            return
        from .pause import PauseScene
        self.ctx.audio.play("ui_back")
        assert self.stack is not None
        self.stack.push(PauseScene(self.params), transition=Transition.FADE)

    def _read_axes(self) -> tuple[float, float]:
        """Polled (state-based) input: correct even for key-tap frames."""
        keys = pygame.key.get_pressed()
        if self.mode is GameMode.FOCUS:
            # One person, two hands.  The left paddle takes W/S and the right
            # one takes I/K *or* the arrow keys, combined with max() so
            # pressing both together cannot cancel itself out.  Arrows are
            # deliberately not aliased onto the left paddle here - unlike
            # SOLO, where they double for the single human - because in this
            # mode they belong to the right hand.
            p1_axis = ((1.0 if keys[pygame.K_s] else 0.0)
                       - (1.0 if keys[pygame.K_w] else 0.0))
            # The two binding groups are summed and then clamped, exactly as
            # SOLO does for its left paddle.  Merging them with ``max()`` was
            # tempting but wrong: an idle group contributes 0.0, and
            # ``max(-1.0, 0.0) == 0.0`` silently deleted every "up" input,
            # leaving the right paddle able to travel downwards only.  Summing
            # keeps "up" intact and still means holding both groups together
            # cannot cancel itself out (-1 + -1 clamps to -1).
            p2_axis = ((1.0 if keys[pygame.K_k] else 0.0)
                       - (1.0 if keys[pygame.K_i] else 0.0))
            p2_axis += ((1.0 if keys[pygame.K_DOWN] else 0.0)
                        - (1.0 if keys[pygame.K_UP] else 0.0))
            return (max(-1.0, min(1.0, p1_axis)),
                    max(-1.0, min(1.0, p2_axis)))

        if self.mode is GameMode.AI_VS_AI:
            p1_axis = 0.0
        else:
            p1_axis = ((1.0 if keys[pygame.K_s] else 0.0)
                       - (1.0 if keys[pygame.K_w] else 0.0))
            if self.mode is not GameMode.TWO_PLAYER:
                p1_axis += ((1.0 if keys[pygame.K_DOWN] else 0.0)
                            - (1.0 if keys[pygame.K_UP] else 0.0))
            p1_axis = max(-1.0, min(1.0, p1_axis))

        if self.mode is GameMode.TWO_PLAYER:
            p2_axis = ((1.0 if keys[pygame.K_DOWN] else 0.0)
                       - (1.0 if keys[pygame.K_UP] else 0.0))
        else:
            p2_axis = 0.0
        return p1_axis, p2_axis

    # -- simulation -------------------------------------------------------
    def update(self, dt: float) -> None:
        ctx = self.ctx
        match = self.match

        # 1. phase bookkeeping (runs before timers so transitions are stable)
        if match.phase is not self._prev_phase:
            self._on_phase_change(self._prev_phase, match.phase)
            self._prev_phase = match.phase
            self._phase_since = 0.0
        self._phase_since += dt

        # 2. rules & timers
        events = match.update(dt)
        if events:
            self._publish(events)

        # 3. results hand-off
        if match.match_over and not self._results_pushed:
            if match.timer >= RESULTS_DELAY:
                self._results_pushed = True
                self._open_results()

        # 4. control
        p1_axis, p2_axis = self._read_axes()
        if self.ai_left is not None:
            p1_axis = self.ai_left.update(dt, self.ball, self.court)
        if self.ai_right is not None:
            p2_axis = self.ai_right.update(dt, self.ball, self.court)

        frozen = match.physics_frozen or match.match_over

        # Powerup timers only advance while the ball is genuinely in play, so
        # a buff can never quietly expire during a goal celebration.
        if match.is_playing and not frozen:
            self.powerups.tick(dt)
            if self.bubbles is not None:
                self.bubbles.update(dt, playing=True)
        self.p1.apply_modifiers(
            self.court, height=self.powerups.height_scale(0),
            speed=self.powerups.speed_scale(0))
        self.p2.apply_modifiers(
            self.court, height=self.powerups.height_scale(1),
            speed=self.powerups.speed_scale(1))

        if self.powerups.enabled:
            p1_axis, p2_axis = self._update_powerups(dt, p1_axis, p2_axis)

        if not frozen:
            self.p1.update(p1_axis, dt, self.court)
            self.p2.update(p2_axis, dt, self.court)

        # 5. ball
        if match.is_playing and not frozen:
            if not self.ball.active:
                self._launch_ball()
            self._step_ball(dt)

        # 6. presentation state
        assert self.camera is not None and self.particles is not None
        assert self.hud is not None
        self.camera.compute(dt)
        self.particles.update(dt)
        self.hud.update(dt)
        if self._hint_timer > 0.0:
            self._hint_timer = max(0.0, self._hint_timer - dt)

        self._update_trail(dt)

        # 7. record every tick for the replay feature
        self._rec_time += dt
        self.recorder.capture(
            self._rec_time,
            self.ball.x, self.ball.y, self.ball.vx, self.ball.vy,
            self.p1.y, self.p2.y,
            match.score[0], match.score[1], match.rally,
            _phase_code(match.phase),
        )

    def _launch_ball(self) -> None:
        """Send the ball out from centre towards the serving side's opponent."""
        # A serve has not been rallied yet, so it must not be able to claim a
        # pickup bubble on its way out.
        self._last_paddle = None
        direction = 1.0 if self.match.server == 0 else -1.0
        angle = self.rng.uniform(0.14, 0.36) * (1.0 if self.rng.chance(0.5) else -1.0)
        self.ball.active = True
        self.ball.set_direction(self._next_serve_speed, angle * direction)
        # A FOCUS concession parks a partially-reset figure here for exactly
        # one serve; every other launch starts the ladder from scratch.
        self._next_serve_speed = BASE_BALL_SPEED
        self.ball.begin_step()

    # -- powerups ---------------------------------------------------------
    def _human_power_key(self, player: int) -> str:
        """Activation hint for a paddle; empty when a bot drives it."""
        if player == 0 and self.ai_left is None and self.mode is not GameMode.AI_VS_AI:
            return "SPACE"
        if player == 1 and self.ai_right is None:
            return "ENTER"
        return ""

    def _fire_powerup(self, player: int) -> bool:
        """Trigger ``player``'s powerup if it is ready (sound on success)."""
        if not self.powerups.trigger(player):
            if self.powerups.enabled:
                self.ctx.audio.play("deny", volume=0.45)
            return False
        self.ctx.audio.play("go", volume=0.75)
        return True

    def _update_powerups(self, dt: float, p1_axis: float,
                         p2_axis: float) -> tuple[float, float]:
        """AI triggers, magnet steering and control inversion for one step.

        Returns the (possibly inverted) movement axes so the caller can apply
        them to the paddles in the same step the effect starts.
        """
        powerups = self.powerups
        ball, court = self.ball, self.court

        for player, controller in ((0, self.ai_left), (1, self.ai_right)):
            if controller is None:
                continue
            toward = ((controller.is_left and ball.vx < 0.0)
                      or ((not controller.is_left) and ball.vx > 0.0))
            if powerups.ai_should_fire(player, dt, incoming=toward and ball.active,
                                       rng=self.rng):
                self._fire_powerup(player)

        # Magnet bends the ball toward the owner's paddle while it travels in.
        # The paddle's own speed is handed over so a sliding mallet is tracked
        # rather than perpetually chased.
        for player, paddle in ((0, self.p1), (1, self.p2)):
            target = powerups.magnet_target(player, ball, court, paddle)
            if target is not None:
                apply_magnet(ball, target, dt, target_vy=paddle.vel)

        p1_axis = self._apply_inversion(0, p1_axis, dt)
        p2_axis = self._apply_inversion(1, p2_axis, dt)
        return p1_axis, p2_axis

    def _apply_inversion(self, player: int, axis: float, dt: float) -> float:
        """REVERSER hits a bot very differently from a human.

        A person keeps full, perfectly negated control - that *is* the
        punishment, because they have to re-map their own hands under
        pressure.  A bot gets none of that: negating its output outright would
        send it marching away from the ball for the whole duration, so the
        paddle would be a guaranteed free point and the powerup would read as
        a cheat rather than as a debuff.  Instead the bot mis-reads its own
        controls in bursts - mostly wrong, occasionally right - so it
        overshoots and half-recovers like a disoriented player.  Its hit rate
        collapses without going to zero.
        """
        if not self.powerups.controls_inverted(player):
            self._disorient[player].step(dt, False)
            return axis
        driven = (player == 0 and self.ai_left is not None) or (
            player == 1 and self.ai_right is not None)
        if not driven:
            return -axis
        return axis * self._disorient[player].step(dt, True)

    def _apply_shield(self) -> bool:
        """Bounce the ball off a sealed goal line.  True when it absorbed."""
        ball, court = self.ball, self.court
        for player, paddle in ((0, self.p1), (1, self.p2)):
            if not self.powerups.shielded(player):
                continue
            travelling_in = ((paddle.is_left and ball.vx < 0.0)
                             or ((not paddle.is_left) and ball.vx > 0.0))
            if not travelling_in:
                continue
            line = court.left + 14.0 if paddle.is_left else court.right - 14.0
            crossing = (ball.x - ball.r < line) if paddle.is_left else (
                ball.x + ball.r > line)
            if not crossing:
                continue
            ball.x = (line + ball.r) if paddle.is_left else (line - ball.r)
            ball.vx = -ball.vx
            color = Color.P1 if player == 0 else Color.P2
            if self.particles is not None:
                emit_impact(self.particles, self.impact_look, ball.x, ball.y,
                            color, normal=0.0)
            if self.camera is not None:
                self.camera.add_trauma(0.35)
            self.ctx.audio.play("wall", volume=0.9)
            return True
        return False

    def _step_ball(self, dt: float) -> None:
        ball, court, match = self.ball, self.court, self.match
        ball.begin_step()
        ball.integrate(dt)

        # Global ball-speed effects (Slow Field) rescale the live velocity
        # rather than the target speed, so they apply instantly and expire
        # cleanly when the timer drops.
        slow = self.powerups.ball_speed_scale()
        if slow != self._applied_slow:
            if self._applied_slow != 0.0 and self._applied_slow > 0.0:
                ball.vx *= slow / self._applied_slow
                ball.vy *= slow / self._applied_slow
            self._applied_slow = slow

        # -- walls
        if resolve_walls(ball, court):
            wall_y = court.top if ball.y <= court.center_y else court.bottom
            self._publish(match.on_wall_hit(ball.speed))

        # -- paddles (swept test, one contact per step is enough at 120 Hz)
        player_paddles = ((self.p1, 0), (self.p2, 1))
        for paddle, player in player_paddles:
            new_speed = next_paddle_speed(ball.speed, match.rally,
                                          self.rally_speedup)
            new_speed *= self.powerups.return_speed_scale(player)
            contact = try_paddle_contact(ball, paddle, new_speed,
                                         english=self.english)
            if contact is None:
                continue
            _ignore, edge = contact
            self._last_paddle = player
            self._bank_powerup_coins(player)
            self._publish(match.on_paddle_hit(player, ball.speed))
            if edge and self.camera is not None:
                # A glancing edge return gets a slightly larger camera kick.
                self.camera.add_trauma(0.30)
            break

        # -- powerup pickups (checked after the paddle test, so a ball that
        #    strikes a paddle and a bubble in the same step credits the side
        #    that has just returned it)
        self._collect_bubble()

        # -- goals (a sealed goal line absorbs the ball first)
        shielded = self.powerups.enabled and self._apply_shield()
        if not shielded:
            if ball.x + ball.r < court.left - 26:
                self._concede(0, exit_point=(court.left - 8, ball.y))
            elif ball.x - ball.r > court.right + 26:
                self._concede(1, exit_point=(court.right + 8, ball.y))

    def _concede(self, side: int, exit_point: tuple[float, float]) -> None:
        """Route a ball that beat a goal line: a point in a duel, a life in FOCUS.

        ``side`` is the index of the paddle that *failed*, which is the
        opposite convention to :meth:`_on_goal`'s scorer - one player owns
        both ends here, so "who scored" is not a question worth asking.
        """
        if self.match.focus is not None:
            self._on_life_lost(side, exit_point)
        else:
            self._on_goal(1 - side, exit_point=exit_point)

    def _bank_powerup_coins(self, player: int) -> None:
        """Gold Rush: pay out per return, immediately, into the live purse."""
        amount = self.powerups.coins_per_hit(player)
        if amount <= 0:
            return
        self._live_coins += amount
        if self.wallet is not None:
            self.wallet.award(amount)
        self.ctx.audio.play("count", volume=0.5)

    def _collect_bubble(self) -> None:
        """Hand the live bubble to whichever paddle last returned the ball.

        The bubble pays out as an *effect*, not as a replacement: the collector
        gets that powerup running for its own duration but keeps whatever it
        was holding, so grabbing a pickup never costs you your special move.

        The one exception is FOCUS's life orb, which has nothing to run and
        therefore settles up here instead of in the powerup system.
        """
        if self.bubbles is None or not self.ball.active:
            return
        taken = self.bubbles.collect(self.ball, self._last_paddle)
        if taken is None:
            return
        spec = taken.item.data
        if spec.effect is PowerEffect.LIFE:
            self._collect_life_orb(taken)
            return
        collector = self._last_paddle
        assert collector is not None
        if not self.powerups.grant(collector, spec, taken.item.name):
            return
        accent = spec.accent or Color.ACCENT
        if self.particles is not None:
            self.particles.burst(taken.x, taken.y, accent, count=30,
                                 speed=230.0, life=0.6, size=3.4, glow=1.5)
            self.particles.burst(taken.x, taken.y, (255, 255, 255), count=10,
                                 speed=140.0, life=0.35, size=2.4, ring=True)
        if self.camera is not None:
            self.camera.add_trauma(0.25)
        self.ctx.audio.play("go", volume=0.7)
        log.info("Pickup %s collected by P%d", taken.item.id, collector + 1)

    def _collect_life_orb(self, taken: PowerupBubble) -> None:
        """FOCUS: bank a life, or pay coins when the budget is already full.

        An orb is a *repair*, never an extra credit - so at full health it
        still pays out, just in coins.  That keeps the detour worth making
        without letting a run outgrow the life count its player chose in the
        menu.

        Feedback goes to the HUD's life-pip row rather than the centre banner
        because the ball is live while an orb is being collected, and a banner
        across the middle of the court would be one more thing to dodge.
        """
        focus = self.match.focus
        assert focus is not None  # only the FOCUS field can carry this orb

        accent = taken.item.data.accent or Color.GOLD
        if self.particles is not None:
            self.particles.burst(taken.x, taken.y, accent, count=30,
                                 speed=230.0, life=0.6, size=3.4, glow=1.5)
            self.particles.burst(taken.x, taken.y, (255, 255, 255), count=10,
                                 speed=140.0, life=0.35, size=2.4, ring=True)
        if self.camera is not None:
            self.camera.add_trauma(0.25)

        if focus.restore():
            self.match.stats.lives_left = focus.lives
            if self.hud is not None:
                self.hud.pulse_life(note="+1 LIFE")
            self.ctx.audio.play("go", volume=0.75)
            log.info("Life orb banked (%d/%d)", focus.lives, focus.max_lives)
            return

        # Cap reached: the orb still pays, just not in lives.
        self._live_coins += FOCUS_LIFE_BONUS
        if self.wallet is not None:
            self.wallet.award(FOCUS_LIFE_BONUS)
        if self.hud is not None:
            self.hud.pulse_life(note=f"+{FOCUS_LIFE_BONUS} COINS")
        self.ctx.audio.play("count", volume=0.7)
        log.info("Life orb at full health -> %d bonus coins", FOCUS_LIFE_BONUS)

    def _on_goal(self, scorer: int, exit_point: tuple[float, float]) -> None:
        self._last_paddle = None
        self.ball.active = False
        self.ball.vx = self.ball.vy = 0.0
        color = Color.P1 if scorer == 0 else Color.P2
        if self.particles is not None:
            x = max(24.0, min(LOGICAL_W - 24.0, exit_point[0]))
            y = max(40.0, min(LOGICAL_H - 40.0, exit_point[1]))
            # A goal is a paddle contact plus the stock celebration, so the
            # equipped effect always reads and the confetti never disappears.
            emit_impact(self.particles, self.impact_look, x, y, color, scale=1.8)
            self.particles.goal_burst(x, y, color)
        if self.camera is not None:
            self.camera.add_trauma(0.95)
        self._publish(self.match.on_goal(scorer, self.ball.speed))

    def _on_life_lost(self, side: int, exit_point: tuple[float, float]) -> None:
        """FOCUS: one of the player's own paddles was beaten.

        Presentation mirrors a goal - the same burst, shake and hit-stop -
        but the colour belongs to the hand that *failed* rather than to a
        scorer, because telling the player which side to fix is the only
        coaching this mode can give.

        The re-serve direction is chosen here instead of defaulting to the
        conceding side: a run that always served back at the hand that just
        missed would compound one slip into two.
        """
        focus = self.match.focus
        assert focus is not None  # only ever called on the FOCUS path

        self._last_paddle = None
        # Captured while the ball is still moving - it dies in the next line.
        speed = self.ball.speed
        self._next_serve_speed = focus.recovered_speed(speed)
        self.ball.active = False
        self.ball.vx = self.ball.vy = 0.0

        color = Color.P1 if side == 0 else Color.P2
        if self.particles is not None:
            x = max(24.0, min(LOGICAL_W - 24.0, exit_point[0]))
            y = max(40.0, min(LOGICAL_H - 40.0, exit_point[1]))
            emit_impact(self.particles, self.impact_look, x, y, color, scale=1.8)
            self.particles.goal_burst(x, y, color)
        if self.camera is not None:
            self.camera.add_trauma(0.95)
        if self.hud is not None:
            self.hud.pulse_life()

        serve_side = 0 if self.rng.chance(0.5) else 1
        self._publish(self.match.on_concede(side, speed, serve_side))

    def _update_trail(self, dt: float) -> None:
        if self.ball.active and self.ball.speed > 0.0:
            self._trail_tick += 1
            if self._trail_tick % 2 == 0:
                self._trail.append([self.ball.x, self.ball.y, 1.0])
        alive: list[list[float]] = []
        for px, py, life in self._trail:
            life -= dt * 3.6
            if life > 0.0:
                alive.append([px, py, life])
        self._trail = alive[-18:]

    def _on_phase_change(self, old: MatchPhase, new: MatchPhase) -> None:
        if new is MatchPhase.COUNTDOWN and old is not MatchPhase.COUNTDOWN:
            self.ball.park(self.court)
            self._trail.clear()
        elif new is MatchPhase.MATCH_OVER:
            self.ball.active = False

    # -- events -----------------------------------------------------------
    def _publish(self, events: list[GameEvent]) -> None:
        for event in events:
            self.ctx.bus.emit(event)
            self._handle_scene_event(event)

    def _handle_scene_event(self, event: GameEvent) -> None:
        """Presentation reactions for logical events raised by the match."""
        audio = self.ctx.audio
        if event.type is EventType.SERVE:
            label = event.get("countdown")
            if label is not None:
                audio.play("count", volume=0.9)
            elif event.get("launch"):
                audio.play("go")
        elif event.type is EventType.MATCH_POINT:
            audio.play("go", volume=0.55)

    # -- FX subscribers ---------------------------------------------------
    def _fx_paddle(self, event: GameEvent) -> None:
        if self.particles is None or self.camera is None or self.hud is None:
            return
        player = int(event.get("player", 0))
        paddle = self.p1 if player == 0 else self.p2
        color = Color.P1 if player == 0 else Color.P2
        outgoing = 1.0 if player == 0 else -1.0
        edge_x = paddle.x + (paddle.w * 0.5 if player == 0 else -paddle.w * 0.5)
        emit_impact(self.particles, self.impact_look, edge_x, self.ball.y, color,
                    outgoing=outgoing, scale=1.0)
        self.camera.kick(self.ball.vy)
        self.hud.pulse_rally()
        self.ctx.audio.play_paddle(int(event.get("rally", 0)))

    def _fx_wall(self, event: GameEvent) -> None:
        if self.particles is None or self.camera is None:
            return
        y = self.court.top if self.ball.y < self.court.center_y else self.court.bottom
        normal = 1.0 if y > self.court.center_y else -1.0
        emit_impact(self.particles, self.impact_look, self.ball.x, y,
                    self.ball_look.fill, normal=normal, scale=0.75)
        self.camera.add_trauma(0.13)
        self.ctx.audio.play("wall", volume=0.85)

    def _fx_serve(self, event: GameEvent) -> None:
        if event.get("launch") and self.camera is not None:
            self.camera.add_trauma(0.20)

    def _fx_match_point(self, event: GameEvent) -> None:
        if self.hud is not None:
            self.hud.pop_banner()

    def _fx_match_end(self, event: GameEvent) -> None:
        ctx = self.ctx
        raw_winner = event.get("winner")
        # FOCUS ends a run with no winner at all, so this has to stay a
        # nullable int rather than defaulting to player 1.
        winner: int | None = None if raw_winner is None else int(raw_winner)
        assert self.particles is not None and self.camera is not None
        assert self.hud is not None

        # Persist the replay + lifetime statistics exactly once.
        payload = self.recorder.finish(
            score=tuple(self.match.score),
            winner=winner,
            duration=self.match.stats.duration,
        )
        # Freeze the cosmetics into the recording: a replay is a historical
        # record and must keep showing the loadout the player actually wore,
        # even after they re-equip something else later.
        payload["loadout"] = self._loadout_ids()
        ctx.storage.save_replay(payload)
        stats = ctx.storage.record_match(
            winner=winner,
            mode=self.mode.value,
            difficulty=self.difficulty.value if self.mode is GameMode.SOLO else None,
            score=(self.match.score[0], self.match.score[1]),
            rally=self.match.stats.longest_rally,
            hits=self.match.stats.total_hits,
            goals=self.match.stats.total_goals,
            duration=self.match.stats.duration,
            fastest=self.match.stats.fastest_ball,
        )

        if self.mode is GameMode.FOCUS:
            self._finish_focus_run(stats)
            return

        self._results_payload = {
            "summary": dataclasses.asdict(self.match.stats),
            "score": (self.match.score[0], self.match.score[1]),
            "winner": winner,
            "mode": self.mode,
            "difficulty": self.difficulty,
            "target": self.target_score,
            "label": self._label(),
            "stats": stats,
            "duration": self.match.stats.duration,
            "longest_rally": self.match.stats.longest_rally,
        }

        # Coin award.  Gold Rush already paid into the wallet as the returns
        # happened (that is the point of the powerup), so the profile's total
        # only needs the match reward on top; `earned` reports both to the
        # results screen and must never under-count what the player banked.
        earned = match_reward(
            mode=self.mode,
            winner=winner,
            difficulty=self.difficulty if self.mode is GameMode.SOLO else None,
            score=self.match.score,
            longest_rally=self.match.stats.longest_rally,
            total_hits=self.match.stats.total_hits,
        )
        if self.wallet is not None:
            self.wallet.award(earned)
            save_wallet(ctx, self.wallet)
        self._results_payload["earned"] = earned + self._live_coins
        self._results_payload["live_coins"] = self._live_coins
        self._results_payload["coins"] = (self.wallet.coins
                                          if self.wallet is not None else 0)

        self.camera.add_trauma(1.0)
        self.hud.pop_banner()
        self.hud.flash()
        self.particles.confetti(LOGICAL_W * 0.5, LOGICAL_H * 0.42)
        self.particles.confetti(LOGICAL_W * 0.36, LOGICAL_H * 0.5)
        self.particles.confetti(LOGICAL_W * 0.64, LOGICAL_H * 0.5)
        ctx.audio.play("win" if winner == 0 else "lose")
        log.info("Match over: %s", self.match.score_string())

    def _finish_focus_run(self, stats: dict[str, object]) -> None:
        """Pay out a finished FOCUS run and build its results payload.

        Split out because almost nothing carries over from a duel: there is
        no score, no winner and no difficulty, so the headline pair are the
        two things the mode actually measures - how long the run lasted and
        how many returns it produced.
        """
        ctx = self.ctx
        focus = self.match.focus
        assert focus is not None

        seconds = self.match.stats.duration
        returns = self.match.stats.total_hits
        # Captured *before* the bests move, so "NEW BEST" is a genuine delta
        # rather than a comparison against the record this run just set.
        old_time = float(stats.get("focus_best_time", 0.0) or 0.0)
        old_returns = int(stats.get("focus_best_returns", 0) or 0)
        stats = ctx.storage.record_focus(time=seconds, returns=returns)

        earned = focus_reward(time=seconds, returns=returns)
        if self.wallet is not None:
            self.wallet.award(earned)
            save_wallet(ctx, self.wallet)

        self._results_payload = {
            "summary": dataclasses.asdict(self.match.stats),
            # A run has no score line, so report a zeroed pair to keep the
            # shape every other screen reads.
            "score": (0, 0),
            "winner": None,
            "mode": self.mode,
            "difficulty": self.difficulty,
            "target": self.target_score,
            "label": self._label(),
            "stats": stats,
            "duration": seconds,
            "longest_rally": self.match.stats.longest_rally,
            "earned": earned + self._live_coins,
            "live_coins": self._live_coins,
            "coins": (self.wallet.coins if self.wallet is not None else 0),
            "focus": {
                "lives_start": focus.max_lives,
                "lives_left": focus.lives,
                "lives_lost": focus.lost,
                "returns": returns,
                "time": seconds,
                "best_time": float(stats["focus_best_time"]),
                "best_returns": int(stats["focus_best_returns"]),
                "new_time_best": seconds > old_time,
                "new_returns_best": returns > old_returns,
            },
        }

        self.camera.add_trauma(1.0)
        self.hud.pop_banner()
        self.hud.flash()
        # Gold rather than the win fanfare: a run has no winner to celebrate,
        # but finishing one is still worth marking.
        self.particles.confetti(LOGICAL_W * 0.5, LOGICAL_H * 0.42)
        self.particles.confetti(LOGICAL_W * 0.36, LOGICAL_H * 0.5)
        self.particles.confetti(LOGICAL_W * 0.64, LOGICAL_H * 0.5)
        ctx.audio.play("win")
        log.info("Focus run over: %.1fs, %d returns", seconds, returns)

    def _open_results(self) -> None:
        from .results import ResultsScene
        assert self.stack is not None
        self.stack.push(ResultsScene(self._results_payload or {},
                                     resume_params=self.params),
                        transition=Transition.FADE)

    # -- drawing ----------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        assert self._world is not None and self._court_surface is not None
        assert self.hud is not None and self.camera is not None
        ctx = self.ctx
        alpha = ctx.render_alpha
        world = self._world
        world.blit(self._court_surface, (0, 0))

        self._draw_trail(world)
        self._draw_paddle(world, self.p1, self._glow_p1, alpha, Color.P1)
        self._draw_paddle(world, self.p2, self._glow_p2, alpha, Color.P2)
        self._draw_ball(world, alpha)
        self._draw_bubbles(world)
        if self._debug_ai:
            self._draw_ai_debug(world)
        if self.particles is not None:
            self.particles.draw(world)

        surface.fill(self.background_look.bg)
        surface.blit(world, self.camera.offset)

        self._draw_hud(surface)
        self._draw_powerup_pills(surface)
        if self._hint_timer > 0.0 and not self.match.match_over:
            self._draw_hints(surface)

    def _draw_trail(self, world: pygame.Surface) -> None:
        if not self._trail:
            return
        draw_trail(world, self._trail, self.trail_look, BALL_RADIUS)

    def _draw_paddle(self, world: pygame.Surface, paddle: Paddle,
                     glow: pygame.Surface | None, alpha: float,
                     color: tuple[int, int, int]) -> None:
        y = paddle.lerp_y(alpha)
        rect = pygame.Rect(int(paddle.x - paddle.w * 0.5),
                           int(y - paddle.h * 0.5),
                           int(paddle.w), int(paddle.h))
        draw_paddle(world, rect, color, self.paddle_look, glow=glow)

    def _draw_ball(self, world: pygame.Surface, alpha: float) -> None:
        x, y = (self.ball.lerp_pos(alpha) if self.ball.active
                else (self.ball.x, self.ball.y))
        speed = self.ball.speed if self.ball.active else 0.0
        boost = 1.0 + min(0.5, speed / MAX_BALL_SPEED * 0.5)
        draw_ball(world, x, y, int(self.ball.r), self.ball_look,
                  glow=self._glow_ball, glow_boost=boost)

    def _draw_ai_debug(self, world: pygame.Surface) -> None:
        """F2: show where each AI intends to be and what it predicted."""
        for controller, color in ((self.ai_left, Color.P1),
                                  (self.ai_right, Color.P2)):
            if controller is None:
                continue
            y = controller.target_y
            pygame.draw.line(world, color, (self.court.left, int(y)),
                             (self.court.right, int(y)), 1)
            pygame.draw.circle(world, color, (int(controller.paddle.x), int(y)), 7, 1)
            prediction = controller.last_prediction
            if prediction is not None:
                pygame.draw.circle(world, Color.ACCENT,
                                   (int(controller.paddle.x), int(prediction)), 5)
                pygame.draw.line(world, Color.ACCENT,
                                 (int(self.ball.x), int(self.ball.y)),
                                 (int(controller.paddle.x), int(prediction)), 1)

    def _draw_hud(self, surface: pygame.Surface) -> None:
        ctx = self.ctx
        match = self.match
        mode_label = self._label()
        if match.focus is not None:
            focus = match.focus
            self.hud.draw_focus(
                surface,
                lives=focus.lives,
                max_lives=focus.max_lives,
                returns=match.stats.total_hits,
                time_label=format_duration(match.stats.duration),
                phase=match.phase,
                rally=match.rally,
                banner=match.banner,
                countdown=match.countdown_label(),
                fps=ctx.fps,
                show_fps=ctx.settings.video.show_fps,
                speed=self.ball.speed if match.is_playing else 0.0,
                max_speed=MAX_BALL_SPEED,
                mode_label=mode_label,
                match_over=match.match_over,
            )
            return
        self.hud.draw(
            surface,
            score=(match.score[0], match.score[1]),
            phase=match.phase,
            rally=match.rally,
            target=match.config.target_score,
            server=None if match.match_over else match.server,
            banner=match.banner,
            countdown=match.countdown_label(),
            fps=ctx.fps,
            show_fps=ctx.settings.video.show_fps,
            speed=self.ball.speed if match.is_playing else 0.0,
            max_speed=MAX_BALL_SPEED,
            match_point=match.match_point_for,
            mode_label=mode_label,
            match_over=match.match_over,
            deuce=self.match.is_deuce() and not self.match.match_over,
        )

    def _draw_powerup_pills(self, surface: pygame.Surface) -> None:
        """Powerup status pill for each paddle (space left of the score).

        The two paddles do not necessarily share a powerup any more - a bot
        draws its own - and a paddle holding a bubble also reports the pickup
        it is currently running rather than the move it is saving.
        """
        if self.hud is None or not self.powerups.enabled:
            return
        for player, align in ((0, "left"), (1, "right")):
            grant = self.powerups.active_grant(player)
            if grant is not None:
                spec, left, name = grant
                ready, cooldown, active = False, 0.0, left
            else:
                spec = self.powerups.held_spec(player)
                name = self.powerup_names[player]
                ready = self.powerups.ready(player)
                cooldown = self.powerups.cooldown_left(player)
                active = self.powerups.active_for(player)
            self.hud.draw_powerup_pill(
                surface,
                name=name,
                key=self._human_power_key(player),
                accent=spec.accent,
                ready=ready,
                cooldown=cooldown,
                active=active,
                cooldown_total=spec.cooldown,
                align=align,
            )

    def _draw_bubbles(self, world: pygame.Surface) -> None:
        """Render the live powerup pickup: soft halo, orb, glyph and life ring.

        Everything goes onto SRCALPHA layers and is blitted with per-surface
        alpha, so the pickup *blooms* in when it spawns and fades over its last
        moments instead of popping in and out from under the player.  There are
        two layers on purpose: the halo gets its own so it can pulse behind an
        orb that stays perfectly steady - a countdown glyph should not shimmer.

        The halo is a single cached radial gradient (``glow_sprite``, the same
        sprite that lights the ball) where it used to be three hard-edged
        concentric discs.  Those banded visibly against the court and made the
        pickup read as a flat painted target rather than something hanging in
        the air.  Nothing here uses additive blending: per-surface alpha is
        exact on the software renderer, ``BLEND_ADD`` is not.
        """
        if self.bubbles is None:
            return
        bubble = self.bubbles.bubble
        if bubble is None:
            return

        # Envelope: bloom in over the first moment of life, warn out over the
        # last, so a bubble never simply vanishes mid-thought.
        fade = min(1.0, bubble.pulse / BUBBLE_FADE_IN)
        if bubble.life < BUBBLE_FADE_OUT:
            fade = min(fade, max(0.0, bubble.life / BUBBLE_FADE_OUT))
        if fade <= 0.0:
            return

        spec = bubble.item.data
        accent = spec.accent or Color.ACCENT
        r = bubble.radius
        halo_r = int(r * BUBBLE_HALO)
        side = halo_r * 2 + 2
        mid = halo_r + 1                       # centre within both layers
        x = bubble.x
        y = bubble.y + math.sin(bubble.pulse * 1.7) * BUBBLE_BOB
        top_left = (int(round(x)) - mid, int(round(y)) - mid)

        # -- halo: one gradient, breathing on its own timescale --------------
        halo = pygame.Surface((side, side), pygame.SRCALPHA)
        glow = glow_sprite(Color.blend(Color.PANEL, accent, 0.55), halo_r)
        halo.blit(glow, (mid - glow.get_width() // 2,
                         mid - glow.get_height() // 2))
        breathe = 0.5 + 0.5 * math.sin(bubble.pulse * 1.9)
        halo.set_alpha(int(255 * fade * (0.55 + 0.35 * breathe)))
        world.blit(halo, top_left)

        # -- orb: opaque shapes, so they composite against each other --------
        # pygame.draw *replaces* pixels on an SRCALPHA surface rather than
        # blending them, so anything drawn on top has to carry its own opacity
        # (the glass highlight below is the one exception - blits do blend).
        layer = pygame.Surface((side, side), pygame.SRCALPHA)
        body = Color.blend(Color.PANEL, accent, 0.50)
        pygame.draw.circle(layer, body, (mid, mid), int(r))
        pygame.draw.circle(layer, accent, (mid, mid), int(r), width=2)

        speck = int(r * 0.30)
        halo_key = glow_sprite((255, 255, 255), max(2, speck))
        layer.blit(halo_key,
                   (mid - int(r * 0.30) - speck, mid - int(r * 0.30) - speck))

        # Countdown arc: gold while there is time, cooling as it runs down.
        life = bubble.fraction_left
        if life > 0.0:
            box = pygame.Rect(0, 0, int(r * 2) + 11, int(r * 2) + 11)
            box.center = mid, mid
            warm = Color.blend((96, 74, 30), Color.GOLD,
                               min(1.0, life * 1.6))
            pygame.draw.arc(layer, warm, box,
                            math.radians(90.0),
                            math.radians(90.0 + 360.0 * life),
                            width=3)

        glyph = self.ctx.fonts.render(spec.glyph, 15, (255, 255, 255),
                                      bold=True)
        layer.blit(glyph, (mid - glyph.get_width() // 2,
                           mid - glyph.get_height() // 2))
        layer.set_alpha(int(255 * fade))
        world.blit(layer, top_left)

    def _draw_hints(self, surface: pygame.Surface) -> None:
        fonts = self.ctx.fonts
        if self.mode is GameMode.FOCUS:
            # Both paddles belong to one person here, so the hint is a key
            # legend rather than a claim about who is playing.  The right
            # paddle gets two bindings because either works, and saying so is
            # cheaper than a settings screen.
            left, right = "LEFT  W / S", "RIGHT  I / K  or  ↑ / ↓"
        elif self.mode is GameMode.TWO_PLAYER:
            left, right = "P1  W / S", "P2  ↑ / ↓"
        elif self.mode is GameMode.SOLO:
            left, right = "W / S  or  ↑ / ↓", f"AI  {self.difficulty.value.upper()}"
        else:
            left = f"AI  {self.difficulty.value.upper()}"
            right = f"AI  {self.difficulty.value.upper()}"
        for text, align, color in ((left, "left", Color.P1),
                                   (right, "right", Color.P2)):
            rendered = fonts.render(text, 15, color, bold=True)
            x = 28 if align == "left" else LOGICAL_W - rendered.get_width() - 28
            surface.blit(rendered, (x, CONTROL_HINT_Y))
        if self.mode is GameMode.FOCUS:
            # No powerups exist in this mode, so SPACE/ENTER must never be
            # advertised - pointing at a key that does nothing is worse than
            # saying nothing at all.
            centre_text = "ESC  PAUSE   ·   F2  AI DEBUG"
        elif self.powerups.enabled:
            centre_text = ("SPACE  POWER   ·   ESC  PAUSE   ·   F2  AI DEBUG"
                           if self.mode is GameMode.SOLO
                           else "SPACE / ENTER  POWER   ·   ESC  PAUSE   ·   F2  AI DEBUG")
        else:
            centre_text = "ESC  PAUSE   ·   F2  AI DEBUG"
        center = fonts.render(centre_text, 13, Color.TEXT_DIM)
        surface.blit(center, (LOGICAL_W // 2 - center.get_width() // 2,
                              CONTROL_HINT_Y))


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
_PHASE_CODES = {
    MatchPhase.COUNTDOWN: 0,
    MatchPhase.SERVE: 1,
    MatchPhase.PLAYING: 2,
    MatchPhase.GOAL: 3,
    MatchPhase.MATCH_OVER: 4,
}


def _phase_code(phase: MatchPhase) -> int:
    return _PHASE_CODES.get(phase, 0)


__all__ = ["GameplayScene"]
