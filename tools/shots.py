"""Render every screen to a PNG so the layout can be eyeballed.

Headless (SDL dummy drivers, scratch ``%LOCALAPPDATA%``): it boots the real
Application, walks the real scene stack and dumps ``app.frame`` -- the same
1280x720 logical surface the game presents.

Run:  python tools\\shots.py     ->  tools\\shots\\*.png
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tools" / "shots"
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="pongpro_shots_")

import pygame  # noqa: E402

from pongpro.app import Application  # noqa: E402
from pongpro.core.constants import (  # noqa: E402
    Difficulty,
    GameMode,
    MatchPhase,
)
from pongpro.core.state_machine import Transition  # noqa: E402
from pongpro.rendering.hud import Hud  # noqa: E402
from pongpro.scenes.gameplay import GameplayScene  # noqa: E402
from pongpro.scenes.menu import MenuScene  # noqa: E402
from pongpro.scenes.pause import PauseScene  # noqa: E402
from pongpro.scenes.results import ResultsScene  # noqa: E402
from pongpro.scenes.settings_scene import SettingsScene  # noqa: E402
from pongpro.scenes.shop import ShopScene  # noqa: E402
from pongpro.economy.catalog import CATEGORIES, ShopCategory  # noqa: E402
from pongpro.gameplay.bubbles import FIRST_SPAWN_DELAY  # noqa: E402
from pongpro.scenes.gameplay import BUBBLE_FADE_IN  # noqa: E402

FULL_STATS = {
    "matches_played": 1234,
    "wins": 987,
    "losses": 247,
    "longest_rally": 512,
    "total_hits": 98765,
    "fastest_ball": 1834.0,
    "playtime_seconds": 98765.0,
    "focus_best_time": 372.0,
    "focus_best_returns": 411,
    "by_difficulty": {d.value: {"won": 99, "lost": 1} for d in Difficulty},
}

RESULTS_PAYLOAD = {
    "winner": 0,
    "score": (11, 7),
    "mode": GameMode.SOLO,
    "difficulty": Difficulty.HARD,
    "duration": 184.0,
    "longest_rally": 37,
    "label": "1P vs AI · HARD · FIRST TO 11",
    "summary": {
        "total_hits": 214,
        "total_goals": 18,
        "fastest_ball": 1520.0,
        "hits_by_player": (120, 94),
    },
    "stats": dict(FULL_STATS),
}

#: A finished FOCUS run.  Deliberately carries no winner and a zeroed score:
#: the results screen reads ``mode`` first and must take the run branch rather
#: than the duel branch that headline a victory or a draw.
FOCUS_RESULTS_PAYLOAD = {
    "winner": None,
    "score": (0, 0),
    "mode": GameMode.FOCUS,
    "difficulty": None,
    "target": 5,
    "duration": 372.0,
    "longest_rally": 34,
    "label": "FOCUS · 5 LIVES",
    "earned": 468,
    "live_coins": 25,
    "coins": 98250,
    "summary": {
        "total_hits": 411,
        "total_goals": 4,
        "fastest_ball": 1104.0,
        "hits_by_player": (0, 0),
        "lives_left": 1,
    },
    "stats": dict(FULL_STATS),
    "focus": {
        "lives_start": 5,
        "lives_left": 1,
        "lives_lost": 4,
        "returns": 411,
        "time": 372.0,
        "best_time": 372.0,
        "best_returns": 411,
        "new_time_best": True,
        "new_returns_best": False,
    },
}

saved: list[str] = []


def shot(app, name: str) -> None:
    path = OUT / f"{name}.png"
    pygame.image.save(app.frame, str(path))
    saved.append(path.name)
    print(f"  wrote {path.relative_to(ROOT)}")


def settle_bubble(field, *, budget: float | None = None) -> None:  # type: ignore[no-untyped-def]
    """Spawn a bubble and let it finish fading in.

    Two timing traps make a naive one-shot step capture nothing useful:

    * the field only spawns once its *opening* delay has elapsed, and that
      delay is a different number in FOCUS (30 s) than in a duel (6 s), so the
      budget has to come from the field rather than a hard-coded constant;
    * stepping in one big lump spawns the bubble at the *end* of that step, so
      its ``pulse`` is still zero and the renderer's ``BUBBLE_FADE_IN``
      envelope leaves it fully transparent.

    Stepping at the real 120 Hz rate past both thresholds captures the frame
    the player would actually see.
    """
    first_delay = getattr(field, "_first_delay", FIRST_SPAWN_DELAY)
    span = (first_delay if budget is None else budget) + BUBBLE_FADE_IN + 0.5
    for _ in range(int(span * 120) + 4):
        field.update(1.0 / 120.0, playing=True)
        bubble = field.bubble
        if bubble is not None and bubble.pulse >= BUBBLE_FADE_IN:
            return


def main() -> int:
    # Start from a clean slate so renamed or retired shots never linger.
    for stale in OUT.glob("*.png"):
        stale.unlink()

    app = Application(max_frames=None, quiet=True)
    app.settings.video.fps_cap = 0
    app.settings.audio.master = 0.0

    def run(frames: int) -> None:
        for _ in range(frames):
            app.step_frame(1.0 / 120.0)

    run(300)  # splash -> menu

    # -- menu: empty profile, then a fully populated one -------------------
    menu = app.stack.current
    assert isinstance(menu, MenuScene)
    run(3)
    shot(app, "01_menu_empty_profile")

    menu._stats = FULL_STATS
    run(3)
    shot(app, "02_menu_full_profile")

    menu._toast = "NO SAVED REPLAY YET - PLAY A MATCH FIRST"
    menu._toast_timer = 2.4
    run(3)
    shot(app, "03_menu_toast")
    menu._toast_timer = 0.0

    # -- settings ----------------------------------------------------------
    depth = app.stack.depth
    app.stack.push(SettingsScene(), transition=Transition.NONE)
    run(6)
    shot(app, "04_settings")
    while app.stack.depth > depth:
        app.stack.pop(transition=Transition.NONE)

    # -- results -----------------------------------------------------------
    app.stack.push(ResultsScene(payload=dict(RESULTS_PAYLOAD)),
                   transition=Transition.NONE)
    run(6)
    shot(app, "05_results")
    while app.stack.depth > depth:
        app.stack.pop(transition=Transition.NONE)

    # -- gameplay + HUD ----------------------------------------------------
    menu = app.stack.current
    assert isinstance(menu, MenuScene)
    menu._start_match(GameMode.SOLO)
    run(150)
    shot(app, "06_gameplay_hints")  # control hints are on a timer
    run(750)
    scene = app.stack.current
    assert isinstance(scene, GameplayScene)
    run(60)
    shot(app, "07_gameplay")

    # -- powerup pickup bubble ---------------------------------------------
    # The field normally waits ~6s of live play before the first pickup, so
    # park one on the court by hand and catch it mid-rally: this is the frame
    # that proves the orb, its spec glyph and the shrinking countdown ring
    # all render over the court without disturbing the HUD.
    scene.bubbles.reset()
    settle_bubble(scene.bubbles)
    bubble = scene.bubbles.bubble
    if bubble is not None:
        scene.ball.active = True
        scene.ball.x, scene.ball.y = bubble.x - 80.0, bubble.y
        scene.ball.begin_step()
        run(1)
        if scene.bubbles.bubble is not None:
            shot(app, "07b_powerup_bubble")
        # Park it again so it cannot turn up unannounced in the HUD shots.
        scene.bubbles.reset()

    # Match point + deuce + a long rally all at once (the worst case for the
    # HUD centre strip).
    match = scene.match
    target = match.config.target_score
    match.score[0] = target + 1
    match.score[1] = target
    match.rally = 12
    match.phase = MatchPhase.PLAYING
    run(4)
    shot(app, "08_hud_match_point_deuce_rally")

    # Match point only (no deuce).
    match.score[0] = target - 1
    match.score[1] = target - 2
    match.rally = 9
    run(4)
    shot(app, "09_hud_match_point_rally")

    # -- pause overlay over a live match -----------------------------------
    scene._open_pause()
    run(60)
    shot(app, "10_pause_over_match")

    # -- finish the match so a replay lands on disk -------------------------
    if isinstance(app.stack.current, PauseScene):
        app.stack.current._action("pause.resume")
    run(60)
    scene = app.stack.current
    assert isinstance(scene, GameplayScene)
    scene.match.config.target_score = 1  # one forced goal ends the match
    scene.match.score[0] = 0
    scene.match.score[1] = 0
    scene.match.phase = MatchPhase.PLAYING
    scene._on_goal(0, exit_point=(1400.0, 360.0))
    run(900)

    # -- replay ------------------------------------------------------------
    app.stack.pop_to(MenuScene, transition=Transition.NONE)
    run(30)
    menu = app.stack.current
    assert isinstance(menu, MenuScene)
    menu._open_replay()
    run(90)
    shot(app, "12_replay")

    # -- synthetic HUD worst case (rally scaled up by the pulse) -----------
    app.stack.pop(transition=Transition.NONE)
    hud = Hud(app.fonts)
    hud.pulse_rally()
    surface = pygame.Surface(app.frame.get_size())
    surface.fill((12, 14, 24))
    hud.draw(
        surface,
        score=(target + 1, target),
        phase=MatchPhase.PLAYING,
        rally=47,
        target=target,
        server=0,
        banner=None,
        countdown=None,
        fps=144.0,
        show_fps=True,
        speed=1834.0,
        max_speed=2400.0,
        match_point=0,
        mode_label="1P vs AI · HARD",
        match_over=False,
        deuce=True,
    )
    pygame.image.save(surface, str(OUT / "11_hud_stack_worst_case.png"))
    saved.append("11_hud_stack_worst_case.png")
    print(f"  wrote {(OUT / '11_hud_stack_worst_case.png').relative_to(ROOT)}")

    # -- shop: cosmetics first, then a powerup card and a background -------
    depth = app.stack.depth
    app.stack.push(ShopScene(), transition=Transition.NONE)
    run(8)
    shot(app, "13_shop_balls")

    shop = app.stack.current
    assert isinstance(shop, ShopScene)
    shop._set_category(CATEGORIES.index(ShopCategory.POWERUP))
    shop._focus_on(("item", 4))          # an unaffordable powerup: stats + price
    run(8)
    shot(app, "14_shop_powerup")

    shop._set_category(CATEGORIES.index(ShopCategory.BACKGROUND))
    shop._focus_on(("item", 2))          # AURORA: shows the court preview
    shop._say("BOUGHT AURORA")
    shop._toast_t = 1.2
    run(8)
    shot(app, "15_shop_background_toast")

    while app.stack.depth > depth:
        app.stack.pop(transition=Transition.NONE)

    # -- FOCUS mode ---------------------------------------------------------
    # Reached through the real menu path, so the explainer gate is exercised
    # rather than bypassed: the first press opens the modal, the second (with
    # the toggle persisted) goes straight into the run.
    menu = app.stack.current
    assert isinstance(menu, MenuScene)

    menu._start_match(GameMode.FOCUS)
    run(45)
    assert type(app.stack.current).__name__ == "FocusIntroScene", (
        "FOCUS must route through its explainer on a fresh profile")
    shot(app, "16_focus_explainer")
    app.stack.pop(transition=Transition.NONE)
    run(10)

    # Now with the explainer acknowledged: the menu row shows FOCUS focused
    # and its hint in the footer band.
    app.settings.gameplay.focus_intro_seen = True
    menu = app.stack.current
    assert isinstance(menu, MenuScene)
    menu.menu.set_focus_by_action("play_focus")
    run(10)
    shot(app, "17_menu_focus_row")

    # The How-to-Play reference, reached from the menu's CONTROLS row.
    # A FADE push waits for a full 1/4 s of fade-out before the swap, so this
    # needs materially more than 30 frames or it captures the menu still
    # mid-fade.
    menu.menu.set_focus_by_action("controls")
    run(4)
    menu._dispatch("controls")
    run(60)
    assert type(app.stack.current).__name__ == "ControlsScene", (
        "CONTROLS must open the reference card")
    shot(app, "22_controls")
    app.stack.pop(transition=Transition.NONE)
    run(10)
    menu = app.stack.current
    assert isinstance(menu, MenuScene)

    menu._start_match(GameMode.FOCUS)
    run(120)
    scene = app.stack.current
    assert isinstance(scene, GameplayScene)
    assert scene.match.focus is not None, "FOCUS must carry a life budget"
    run(900)
    shot(app, "18_focus_run")

    # Last life: the surviving pip breathes red and the caption warns.
    focus = scene.match.focus
    focus.lives = 1
    scene.match.stats.lives_left = 1
    scene.hud.pulse_life()
    run(4)
    shot(app, "19_focus_last_life")

    # The life orb - the one pickup this mode has - parked on the court.
    scene.bubbles.reset()
    settle_bubble(scene.bubbles)
    orb = scene.bubbles.bubble
    if orb is not None:
        scene.ball.active = True
        scene.ball.x, scene.ball.y = orb.x - 80.0, orb.y
        scene.ball.begin_step()
        run(1)
        if scene.bubbles.bubble is not None:
            shot(app, "20_focus_life_orb")
        scene.bubbles.reset()

    # A finished run's results screen (bests, no winner, bonus coins).
    app.stack.pop_to(MenuScene, transition=Transition.NONE)
    run(20)
    depth = app.stack.depth
    app.stack.push(ResultsScene(payload=dict(FOCUS_RESULTS_PAYLOAD)),
                   transition=Transition.NONE)
    run(10)
    shot(app, "21_focus_results")
    while app.stack.depth > depth:
        app.stack.pop(transition=Transition.NONE)

    app.stop()
    app.shutdown()
    print(f"\n{len(saved)} screenshots in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
