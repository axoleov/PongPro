"""Settings model: typed dataclasses, validation and (de)serialisation.

The dataclasses are the single source of truth for defaults; user overrides
are persisted as JSON by :mod:`pongpro.storage`.  Unknown keys from newer
versions are ignored so a downgrade never crashes the game.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, fields
from typing import Any

from .constants import DEFAULT_TARGET_SCORE, Difficulty, GameMode, ParticleQuality

SETTINGS_VERSION = 2


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


@dataclass(slots=True)
class AudioSettings:
    master: float = 0.85  # 0..1
    sfx: float = 1.0  # 0..1
    music: float = 0.55  # 0..1
    muted: bool = False
    music_enabled: bool = True

    def validate(self) -> None:
        self.master = float(_clamp(self.master, 0.0, 1.0))
        self.sfx = float(_clamp(self.sfx, 0.0, 1.0))
        self.music = float(_clamp(self.music, 0.0, 1.0))


@dataclass(slots=True)
class VideoSettings:
    fullscreen: bool = False
    window_width: int = 1280
    window_height: int = 720
    vsync: bool = True
    fps_cap: int = 144  # 0 == uncapped
    show_fps: bool = False
    screen_shake: bool = True
    particles: ParticleQuality = ParticleQuality.HIGH
    ui_scale: float = 1.0

    def validate(self) -> None:
        self.window_width = int(_clamp(self.window_width, 640, 7680))
        self.window_height = int(_clamp(self.window_height, 360, 4320))
        self.fps_cap = int(_clamp(self.fps_cap, 0, 1000))
        self.ui_scale = float(_clamp(self.ui_scale, 0.75, 2.0))
        if not isinstance(self.particles, ParticleQuality):
            try:
                self.particles = ParticleQuality(str(self.particles))
            except ValueError:
                self.particles = ParticleQuality.HIGH


@dataclass(slots=True)
class GameplaySettings:
    mode: GameMode = GameMode.SOLO
    difficulty: Difficulty = Difficulty.NORMAL
    target_score: int = DEFAULT_TARGET_SCORE
    rally_speedup: bool = True
    english_enabled: bool = True
    demo_idle_seconds: int = 45  # attract-mode inactivity timeout
    #: FOCUS runs one player's hands at once, so it opens with an explainer.
    #: Set once the player has dismissed it; stored here rather than in the
    #: stats file because it is a UI preference, not a gameplay record.
    focus_intro_seen: bool = False

    def validate(self) -> None:
        self.target_score = int(_clamp(self.target_score, 1, 21))
        self.demo_idle_seconds = int(_clamp(self.demo_idle_seconds, 0, 600))
        self.focus_intro_seen = bool(self.focus_intro_seen)
        if not isinstance(self.mode, GameMode):
            try:
                self.mode = GameMode(str(self.mode))
            except ValueError:
                self.mode = GameMode.SOLO
        if not isinstance(self.difficulty, Difficulty):
            try:
                self.difficulty = Difficulty(str(self.difficulty))
            except ValueError:
                self.difficulty = Difficulty.NORMAL


@dataclass(slots=True)
class Settings:
    version: int = SETTINGS_VERSION
    audio: AudioSettings = field(default_factory=AudioSettings)
    video: VideoSettings = field(default_factory=VideoSettings)
    gameplay: GameplaySettings = field(default_factory=GameplaySettings)

    def validate(self) -> None:
        self.audio.validate()
        self.video.validate()
        self.gameplay.validate()
        self.version = SETTINGS_VERSION

    # -- serialisation ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["video"]["particles"] = self.video.particles.value
        data["gameplay"]["mode"] = self.gameplay.mode.value
        data["gameplay"]["difficulty"] = self.gameplay.difficulty.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        """Build settings from plain data, tolerating unknown/missing keys."""
        settings = cls()
        if not isinstance(data, dict):
            return settings
        _merge(settings.audio, data.get("audio"))
        _merge_video(settings.video, data.get("video"))
        _merge_gameplay(settings.gameplay, data.get("gameplay"))
        version = data.get("version")
        settings.version = int(version) if isinstance(version, int) else SETTINGS_VERSION
        settings.validate()
        return settings


def _merge(target: Any, data: Any) -> None:
    """Copy recognised scalar keys from ``data`` onto a slotted dataclass."""
    if not isinstance(data, dict):
        return
    names = {f.name for f in fields(target)}
    for key, value in data.items():
        if key in names:
            setattr(target, key, value)


def _merge_video(target: VideoSettings, data: Any) -> None:
    if not isinstance(data, dict):
        return
    known = {f.name for f in fields(target)}
    for key, value in data.items():
        if key not in known:
            continue
        if key == "particles":
            try:
                target.particles = ParticleQuality(str(value))
            except ValueError:
                continue
        else:
            setattr(target, key, value)


def _merge_gameplay(target: GameplaySettings, data: Any) -> None:
    if not isinstance(data, dict):
        return
    known = {f.name for f in fields(target)}
    for key, value in data.items():
        if key not in known:
            continue
        if key == "mode":
            try:
                target.mode = GameMode(str(value))
            except ValueError:
                continue
        elif key == "difficulty":
            try:
                target.difficulty = Difficulty(str(value))
            except ValueError:
                continue
        else:
            setattr(target, key, value)
