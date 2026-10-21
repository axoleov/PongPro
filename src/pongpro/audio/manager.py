"""Audio manager: lazy-safe mixer wrapper with volume routing and pooling.

Every public method is a no-op when audio initialisation fails (locked-down
machines, missing drivers), so gameplay code never has to guard its calls.
"""

from __future__ import annotations

import logging

import numpy as np
import pygame

from ..core.settings import Settings
from . import synth

log = logging.getLogger(__name__)

#: Pitch variants for the paddle blip, indexed by rally length.
PADDLE_PITCHES = (0.92, 1.0, 1.10, 1.20, 1.33, 1.47)


def _as_sound(samples: synth.Samples) -> pygame.mixer.Sound:
    """Wrap synthesised (n, 2) int16 frames in a ``pygame.mixer.Sound``.

    ``Sound(array=...)`` needs the array to match the mixer's channel count
    (2, stereo) and sample width (int16); we init the mixer that way, but the
    bytes fallback keeps audio alive if a host opens it differently.
    """
    array = np.ascontiguousarray(samples, dtype=np.int16)
    if pygame.mixer.get_init() is not None:
        _rate, size, channels = pygame.mixer.get_init()
        if size == -16 and channels == 2:
            return pygame.mixer.Sound(array=array)
    return pygame.mixer.Sound(buffer=array.tobytes())


class AudioManager:
    """Owns the mixer, the sample cache and the volume graph."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = False
        self._sounds: dict[str, list[pygame.mixer.Sound]] = {}
        self._music: pygame.mixer.Sound | None = None
        self._music_channel: pygame.mixer.Channel | None = None
        self._music_playing = False

    # -- lifecycle --------------------------------------------------------
    def initialise(self) -> bool:
        """Init the mixer and synthesise every sample. Returns success."""
        if self.enabled:
            return True
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            if pygame.mixer.get_init() is None:
                raise pygame.error("mixer unavailable")
            pygame.mixer.set_num_channels(24)
        except pygame.error as exc:  # pragma: no cover - depends on host audio
            log.warning("Audio disabled: %s", exc)
            return False

        rate = pygame.mixer.get_init()[0]
        try:
            self._build_library(rate)
        except Exception:  # noqa: BLE001 - never let audio kill start-up
            log.exception("Sample synthesis failed; audio disabled")
            return False

        self.enabled = True
        self.apply_volumes()
        log.info("Audio ready @ %d Hz (%d samples)", rate, len(self._sounds))
        return True

    def _build_library(self, rate: int) -> None:
        self._sounds["paddle"] = [
            _as_sound(synth.make_paddle_hit(rate, p)) for p in PADDLE_PITCHES
        ]
        self._sounds["wall"] = [_as_sound(synth.make_wall_hit(rate))]
        self._sounds["goal"] = [_as_sound(synth.make_goal(rate, True))]
        self._sounds["concede"] = [_as_sound(synth.make_goal(rate, False))]
        self._sounds["ui_move"] = [_as_sound(synth.make_ui(rate, "move"))]
        self._sounds["ui_select"] = [_as_sound(synth.make_ui(rate, "select"))]
        self._sounds["ui_back"] = [_as_sound(synth.make_ui(rate, "back"))]
        self._sounds["deny"] = [_as_sound(synth.make_ui(rate, "deny"))]
        self._sounds["count"] = [_as_sound(synth.make_countdown(rate, False))]
        self._sounds["go"] = [_as_sound(synth.make_countdown(rate, True))]
        self._sounds["win"] = [_as_sound(synth.make_fanfare(rate, True))]
        self._sounds["lose"] = [_as_sound(synth.make_fanfare(rate, False))]
        for bucket in self._sounds.values():
            for sound in bucket:
                sound.set_volume(1.0)
        self._music = _as_sound(synth.make_music_loop(rate))
        self._music.set_volume(1.0)

    # -- volume routing ---------------------------------------------------
    def apply_volumes(self) -> None:
        audio = self.settings.audio
        self._music_volume = (
            0.0 if (audio.muted or not audio.music_enabled)
            else audio.master * audio.music
        )
        self._sfx_volume = 0.0 if audio.muted else audio.master * audio.sfx
        if self._music_channel is not None and self._music_channel.get_busy():
            self._music_channel.set_volume(self._music_volume)
        if not self.enabled:
            return
        if self._music_playing and self._music_volume <= 0.0:
            self.stop_music()

    @property
    def music_volume(self) -> float:
        return getattr(self, "_music_volume", 0.0)

    @property
    def sfx_volume(self) -> float:
        return getattr(self, "_sfx_volume", 0.0)

    # -- playback ---------------------------------------------------------
    def play(self, name: str, *, variant: int = 0, volume: float = 1.0) -> None:
        """Play a cached sample by name (silently ignores unknown names)."""
        if not self.enabled or not self._sounds.get(name):
            return
        bucket = self._sounds[name]
        sound = bucket[variant % len(bucket)]
        try:
            channel = sound.play()
            if channel is not None:
                channel.set_volume(self._sfx_volume * volume)
        except pygame.error:  # pragma: no cover
            log.debug("play() failed for %s", name)

    def play_paddle(self, rally: int) -> None:
        """Paddle blip that rises in pitch as the rally speeds up."""
        index = min(len(PADDLE_PITCHES) - 1, max(0, rally // 3))
        self.play("paddle", variant=index)

    def start_music(self) -> None:
        if not self.enabled or self._music is None or self._music_playing:
            return
        if self._music_volume <= 0.0:
            return
        try:
            self._music_channel = self._music.play(loops=-1)
            if self._music_channel is not None:
                self._music_channel.set_volume(self._music_volume)
            self._music_playing = True
        except pygame.error:  # pragma: no cover
            log.debug("music start failed")

    def stop_music(self) -> None:
        if self._music_channel is not None:
            self._music_channel.fadeout(350)
        self._music_playing = False

    def pause_music(self) -> None:
        if self._music_channel is not None and self._music_playing:
            self._music_channel.pause()

    def unpause_music(self) -> None:
        if self._music_channel is not None and self._music_playing:
            self._music_channel.unpause()

    def shutdown(self) -> None:
        if self.enabled:
            try:
                pygame.mixer.quit()
            except pygame.error:  # pragma: no cover
                pass
        self.enabled = False
        self._sounds.clear()
        self._music = None
