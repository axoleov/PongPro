"""Import check: every module must import cleanly (headless)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

MODULES = [
    "pongpro",
    "pongpro.app",
    "pongpro.__main__",
    "pongpro.core.constants",
    "pongpro.core.context",
    "pongpro.core.events",
    "pongpro.core.logging_setup",
    "pongpro.core.paths",
    "pongpro.core.rng",
    "pongpro.core.settings",
    "pongpro.core.state_machine",
    "pongpro.core.timestep",
    "pongpro.economy.catalog",
    "pongpro.economy.wallet",
    "pongpro.economy",
    "pongpro.audio.synth",
    "pongpro.audio.manager",
    "pongpro.storage",
    "pongpro.storage.store",
    "pongpro.gameplay.entities",
    "pongpro.gameplay.physics",
    "pongpro.gameplay.ai",
    "pongpro.gameplay.match",
    "pongpro.gameplay.bubbles",
    "pongpro.gameplay.focus",
    "pongpro.gameplay.powerups",
    "pongpro.gameplay.replay",
    "pongpro.rendering.camera",
    "pongpro.rendering.fonts",
    "pongpro.rendering.hud",
    "pongpro.rendering.icon",
    "pongpro.rendering.particles",
    "pongpro.rendering.skins",
    "pongpro.rendering.ui",
    "pongpro.rendering.video",
    "pongpro.scenes.common",
    "pongpro.scenes.splash",
    "pongpro.scenes.controls",
    "pongpro.scenes.focus_intro",
    "pongpro.scenes.menu",
    "pongpro.scenes.settings_scene",
    "pongpro.scenes.shop",
    "pongpro.scenes.gameplay",
    "pongpro.scenes.pause",
    "pongpro.scenes.results",
    "pongpro.scenes.replay_scene",
]

failures = []
for name in MODULES:
    try:
        __import__(name)
    except Exception as exc:
        failures.append(name)
        print("FAIL  " + name + ": " + type(exc).__name__ + ": " + str(exc))
    else:
        print("ok    " + name)

print("")
if failures:
    print(str(len(failures)) + " import failure(s)")
    sys.exit(1)
print("all " + str(len(MODULES)) + " modules imported")
