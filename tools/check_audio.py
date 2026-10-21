"""Verify synthesised samples convert into playable pygame Sounds."""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pygame  # noqa: E402

from pongpro.audio import synth  # noqa: E402
from pongpro.audio.manager import AudioManager, _as_sound  # noqa: E402
from pongpro.core.settings import Settings  # noqa: E402


def main() -> int:
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    print("mixer init:", pygame.mixer.get_init())

    samples = synth.make_paddle_hit(44100, 1.0)
    print("synth output:", samples.shape, samples.dtype)

    sound = _as_sound(samples)
    print("sound ->", type(sound).__name__, "len ms:",
          int(sound.get_length() * 1000))

    music = _as_sound(synth.make_music_loop(44100))
    print("music ->", type(music).__name__, "len s:", round(music.get_length(), 2))

    manager = AudioManager(Settings())
    ok = manager.initialise()
    print("manager.initialise():", ok, "enabled:", manager.enabled)
    if ok:
        manager.apply_volumes()
        manager.play("paddle", variant=2)
        manager.play("goal")
        manager.play_paddle(9)
        print("played 3 one-shots ok")
        manager.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
