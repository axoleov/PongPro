"""End-to-end smoke test (headless).

Boots the real Application with SDL's dummy drivers, drives it through
splash -> menu -> match -> pause -> goal -> results, and asserts that the
persistence layer recorded the match and wrote a replay.

Run:  python tools\\smoke_run.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

from pongpro.app import Application  # noqa: E402
from pongpro.core.constants import Difficulty, GameMode, MatchPhase  # noqa: E402
from pongpro.core.state_machine import Transition  # noqa: E402
from pongpro.economy.catalog import (  # noqa: E402
    ITEMS,
    PowerEffect,
    ShopCategory,
    items_in,
)
from pongpro.economy.wallet import (  # noqa: E402
    STARTING_COINS,
    get_wallet,
    save_wallet,
)
from pongpro.scenes.gameplay import GameplayScene  # noqa: E402
from pongpro.scenes.menu import MenuScene  # noqa: E402
from pongpro.scenes.pause import PauseScene  # noqa: E402
from pongpro.scenes.results import ResultsScene  # noqa: E402
from pongpro.scenes.shop import ShopScene  # noqa: E402
from pongpro.storage import Storage  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(condition), detail))
    print(("PASS  " if condition else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def main() -> int:
    app = Application(max_frames=None, quiet=True)
    app.settings.video.fps_cap = 0  # run as fast as the CPU allows
    app.settings.audio.master = 0.0  # keep the test silent
    app.settings.gameplay.target_score = 5
    app.settings.gameplay.difficulty = Difficulty.HARD

    # Isolate persistence so the test never pollutes the real player profile.
    tmp = Path(tempfile.mkdtemp(prefix="pongpro_smoke_"))
    storage = Storage(tmp)
    app.storage = storage
    app.ctx.storage = storage

    def run(frames: int, label: str) -> None:
        """Advance deterministically: one call == one physics tick."""
        for _ in range(frames):
            app.step_frame(1.0 / 120.0)

    # -- phase 1: credits -> splash -> menu -------------------------------
    run(1100, "credits->splash")
    check("reached main menu", isinstance(app.stack.current, MenuScene),
          type(app.stack.current).__name__)

    # -- phase 2: start a solo match -------------------------------------
    menu = app.stack.current
    assert isinstance(menu, MenuScene)
    menu._start_match(GameMode.SOLO)
    run(150, "menu->game")
    scene = app.stack.current
    check("match scene pushed", isinstance(scene, GameplayScene),
          type(scene).__name__)
    assert isinstance(scene, GameplayScene)
    check("no pickup at kick-off",
          scene.bubbles is not None and scene.bubbles.bubble is None
          and scene.bubbles.armed,
          "a bubble must wait for live play")

    # -- phase 3: simulate play ------------------------------------------
    run(900, "match play")
    assert isinstance(scene, GameplayScene)
    check("match is running", not scene.match.match_over,
          f"phase={scene.match.phase.value} score={scene.match.score}")
    check("ball is live or recently scored",
          scene.ball.active or scene.match.score[0] + scene.match.score[1] > 0
          or scene.match.phase is not MatchPhase.PLAYING,
          f"phase={scene.match.phase.value}")

    # -- phase 3b: powerup loadout + pickup bubbles ------------------------
    from pongpro.gameplay.powerups import owned_powerups  # noqa: E402

    assert isinstance(scene, GameplayScene)
    owned_pool = {i.data for i in owned_powerups(get_wallet(app.ctx))}
    check("solo bot holds an owned powerup",
          scene.powerups.held_spec(1) in owned_pool
          and scene.powerups.held_spec(1).effect is not PowerEffect.NONE,
          f"P2={scene.powerup_names[1]}")
    check("solo human keeps the equipped powerup",
          scene.powerups.held_spec(0)
          is get_wallet(app.ctx).equipped_item(ShopCategory.POWERUP).data,
          f"P1={scene.powerup_names[0]}")
    check("pickup bubbles armed from the same collection",
          scene.bubbles is not None and scene.bubbles.armed,
          "single live bubble, drawn from the owned pool")

    # Keep the match from ending while we wait out the opening delay, then
    # let the scene's own update loop bring the first bubble onto the court.
    scene.match.config.target_score = 99
    scene.match.score[0] = scene.match.score[1] = 0
    bubble = None
    for _ in range(3600):
        bubble = scene.bubbles.bubble if scene.bubbles else None
        if bubble is not None or scene.match.match_over:
            break
        run(1, "bubble wait")
    bubble = scene.bubbles.bubble if scene.bubbles else None
    check("powerup bubble appears mid-match", bubble is not None,
          "no bubble within 30s of play" if bubble is None
          else f"{bubble.item.id} at ({bubble.x:.0f},{bubble.y:.0f})")

    if bubble is not None:
        held_before = scene.powerups.held_spec(1)
        held_name_before = scene.powerups.held_name(1)
        cooldown_before = scene.powerups.cooldown_left(1)
        active_before = scene.powerups.active_for(1)
        scene.ball.active = True
        scene.ball.x, scene.ball.y = bubble.x, bubble.y
        scene._last_paddle = 1  # that side's paddle is the one that returned it
        scene._collect_bubble()
        grant = scene.powerups.active_grant(1)
        check("bubble pays out to the returning side",
              grant is not None and scene.bubbles.bubble is None,
              "nothing granted" if grant is None else grant[2])
        # A grant is additive: it must neither borrow nor recharge the move
        # that paddle was already holding.
        check("collection leaves the held powerup intact",
              grant is not None
              and scene.powerups.held_spec(1) is held_before
              and scene.powerups.held_name(1) == held_name_before
              and scene.powerups.cooldown_left(1) == cooldown_before
              and scene.powerups.active_for(1) == active_before,
              f"held={scene.powerups.held_name(1)} "
              f"cd {cooldown_before:.2f}->{scene.powerups.cooldown_left(1):.2f}")
        check("the other side gets nothing",
              scene.powerups.active_grant(0) is None)

        # ... and a ball that has not been returned still cannot claim one.
        scene.bubbles.update(4.0, playing=True)  # fast-forward the respawn gap
        if scene.bubbles.bubble is None:
            scene.bubbles.update(8.0, playing=True)
        bubble = scene.bubbles.bubble
        if bubble is not None:
            scene.ball.x, scene.ball.y = bubble.x, bubble.y
            scene._last_paddle = None  # straight off a serve
            scene._collect_bubble()
            check("an unreturned ball passes the bubble by",
                  scene.bubbles.bubble is not None)

    # -- phase 4: pause overlay ------------------------------------------
    scene._open_pause()
    run(60, "pause")
    check("pause overlay active", isinstance(app.stack.current, PauseScene),
          type(app.stack.current).__name__)
    paused_ticks = scene.match.stats.duration
    run(60, "paused idle")
    check("simulation frozen while paused",
          scene.match.stats.duration == paused_ticks,
          f"{paused_ticks:.3f} -> {scene.match.stats.duration:.3f}")
    assert isinstance(app.stack.current, PauseScene)
    app.stack.current._action("pause.resume")
    run(60, "resume")
    check("resumed to match", app.stack.current is scene,
          type(app.stack.current).__name__)

    # -- phase 5: force the winning point --------------------------------
    # Shrink the win condition so a single forced goal ends the match.
    scene.match.config.target_score = 1
    scene.match.score[0] = 0
    scene.match.score[1] = 0
    scene.match.phase = MatchPhase.PLAYING
    scene._on_goal(0, exit_point=(1400.0, 360.0))
    run(600, "goal -> over")
    check("match over reached", scene.match.match_over,
          f"score={scene.match.score}")
    run(200, "results hand-off")
    results = app.stack.current
    check("results screen shown", isinstance(results, ResultsScene),
          type(results).__name__)

    # -- phase 6: persistence --------------------------------------------
    stats = storage.load_stats()
    check("match recorded in profile",
          int(stats.get("matches_played", 0)) == 1
          and int(stats.get("wins", 0)) == 1,
          f"played={stats.get('matches_played')} wins={stats.get('wins')}")
    replay = storage.load_replay()
    check("replay written", replay is not None and len(replay.get("frames", [])) > 100,
          f"{0 if replay is None else len(replay.get('frames', []))} frames")
    check("settings file written", (tmp / "settings.json").exists())

    # -- phase 7: rematch / quit ------------------------------------------
    assert isinstance(results, ResultsScene)
    results._action("results.rematch")
    run(120, "rematch")
    check("rematch started new match",
          isinstance(app.stack.current, GameplayScene)
          and app.stack.current.match.score == [0, 0],
          f"depth={app.stack.depth}")
    app.stack.pop_to(MenuScene, transition=Transition.NONE)
    run(30, "back to menu")
    check("returned to menu", isinstance(app.stack.current, MenuScene)
          and app.stack.depth == 1, f"depth={app.stack.depth}")

    # -- phase 8: economy -------------------------------------------------
    # The match has already paid out: `shop.json` must exist and the wallet
    # must hold more than a fresh profile starts with.
    check("shop document written", (tmp / "shop.json").exists())
    wallet = get_wallet(app.ctx)
    balance = wallet.coins
    check("match paid coins", balance > STARTING_COINS,
          f"{balance} > {STARTING_COINS} starting")
    check("fresh profile owns the free starter set",
          all(wallet.owns(i.id) for i in ITEMS if i.price == 0),
          f"{wallet.owned_count(ShopCategory.BALL)} balls owned")

    # -- phase 9: open the shop and buy through the UI ---------------------
    depth = app.stack.depth
    app.stack.push(ShopScene(), transition=Transition.NONE)
    run(30, "shop")
    shop = app.stack.current
    check("shop opened", isinstance(shop, ShopScene), type(shop).__name__)
    assert isinstance(shop, ShopScene)

    affordable = [i for i in ITEMS
                  if i.price > 0 and not wallet.owns(i.id)
                  and wallet.can_afford(i.price)]
    check("something affordable in the catalog", len(affordable) > 0,
          f"balance={balance}")
    target = affordable[0]
    shop._set_category(list(ShopCategory).index(target.category))
    row = [i for i in shop.visible_items()].index(target)
    shop._focus_on(("item", row))
    shop._activate()
    run(12, "buy")
    check("purchase debited exactly the price",
          wallet.coins == balance - target.price,
          f"{balance} - {target.price} -> {wallet.coins}")
    check("purchase recorded in lifetime spend",
          wallet.purchases == 1 and wallet.lifetime_spent == target.price,
          f"purchases={wallet.purchases} spent={wallet.lifetime_spent}")
    check("purchase auto-equipped the new item",
          wallet.equipped_id(target.category) == target.id,
          f"{target.id} in {target.category.value}")
    check("affordable buy never rejected", wallet.owns(target.id), target.id)

    # Equipping a different owned item must be a second, separate operation.
    owned_rows = [i for i in items_in(target.category) if wallet.owns(i.id)
                  and i.id != target.id]
    if owned_rows:
        other = owned_rows[0]
        shop._focus_on(("item", shop.visible_items().index(other)))
        shop._activate()
        check("re-equip switches loadout",
              wallet.equipped_id(target.category) == other.id, other.id)

    app.stack.pop(transition=Transition.NONE)
    run(12, "close shop")
    check("shop popped back to the menu", app.stack.depth == depth,
          f"depth={app.stack.depth}")

    # The wallet on disk must reflect what the UI just did.
    on_disk = Storage(tmp).load_wallet()
    check("purchase persisted to disk",
          target.id in (on_disk.get("owned") or []),
          f"{target.id} not in shop.json")
    check("balance persisted to disk",
          int(on_disk.get("coins", -1)) == wallet.coins,
          f"{on_disk.get('coins')} vs {wallet.coins}")
    save_wallet(app.ctx, wallet)  # explicit write path used by the scene

    # -- teardown ---------------------------------------------------------
    app.stop()
    code = app.shutdown()

    failures = [c for c in CHECKS if not c[1]]
    print("")
    print(f"{len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed")
    if failures:
        for name, _, detail in failures:
            print(f"  FAILED: {name} {detail}")
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
