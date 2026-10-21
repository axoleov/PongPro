"""Settings model: serialisation round-trips, validation and tolerance."""

from __future__ import annotations

import unittest

from pongpro.core.settings import (
    SETTINGS_VERSION,
    AudioSettings,
    Settings,
    VideoSettings,
)
from pongpro.core.constants import Difficulty, GameMode, ParticleQuality


class SettingsTests(unittest.TestCase):
    def test_defaults_validate(self) -> None:
        settings = Settings()
        settings.validate()
        self.assertEqual(settings.version, SETTINGS_VERSION)
        self.assertEqual(settings.gameplay.mode, GameMode.SOLO)
        self.assertEqual(settings.video.particles, ParticleQuality.HIGH)

    def test_round_trip_preserves_values(self) -> None:
        settings = Settings()
        settings.audio.master = 0.42
        settings.audio.muted = True
        settings.video.fullscreen = True
        settings.video.window_width = 1600
        settings.video.window_height = 900
        settings.video.particles = ParticleQuality.LOW
        settings.gameplay.mode = GameMode.AI_VS_AI
        settings.gameplay.difficulty = Difficulty.ELITE
        settings.gameplay.target_score = 11

        restored = Settings.from_dict(settings.to_dict())

        self.assertEqual(restored.audio.master, 0.42)
        self.assertTrue(restored.audio.muted)
        self.assertTrue(restored.video.fullscreen)
        self.assertEqual((restored.video.window_width,
                          restored.video.window_height), (1600, 900))
        self.assertEqual(restored.video.particles, ParticleQuality.LOW)
        self.assertEqual(restored.gameplay.mode, GameMode.AI_VS_AI)
        self.assertEqual(restored.gameplay.difficulty, Difficulty.ELITE)
        self.assertEqual(restored.gameplay.target_score, 11)

    def test_out_of_range_values_are_clamped(self) -> None:
        settings = Settings.from_dict({
            "audio": {"master": 5.0, "sfx": -3.0, "music": 0.5},
            "video": {"fps_cap": -60, "window_width": 99999,
                      "ui_scale": 12.0},
            "gameplay": {"target_score": 999},
        })
        self.assertEqual(settings.audio.master, 1.0)
        self.assertEqual(settings.audio.sfx, 0.0)
        self.assertEqual(settings.video.fps_cap, 0)
        self.assertEqual(settings.video.window_width, 7680)
        self.assertEqual(settings.video.ui_scale, 2.0)
        self.assertEqual(settings.gameplay.target_score, 21)

    def test_unknown_keys_are_ignored(self) -> None:
        """A settings file from a future version must not crash this build."""
        settings = Settings.from_dict({
            "version": 99,
            "audio": {"master": 0.5, "future_knob": 123},
            "video": {"ray_tracing": True},
            "gameplay": {"battle_royale": True},
            "extra_top_level": {"a": 1},
        })
        self.assertEqual(settings.audio.master, 0.5)
        self.assertFalse(hasattr(settings.video, "ray_tracing"))

    def test_invalid_enums_fall_back(self) -> None:
        settings = Settings.from_dict({
            "video": {"particles": "quantum"},
            "gameplay": {"mode": "split_screen", "difficulty": "nightmare"},
        })
        self.assertEqual(settings.video.particles, ParticleQuality.HIGH)
        self.assertEqual(settings.gameplay.mode, GameMode.SOLO)
        self.assertEqual(settings.gameplay.difficulty, Difficulty.NORMAL)

    def test_garbage_input_returns_defaults(self) -> None:
        for junk in (None, 42, "text", ["list"]):
            settings = Settings.from_dict(junk)  # type: ignore[arg-type]
            self.assertEqual(settings.version, SETTINGS_VERSION)

    def test_audio_validation_only_touches_own_fields(self) -> None:
        audio = AudioSettings(master=2.0, sfx=0.5, music=0.5)
        audio.validate()
        self.assertEqual(audio.master, 1.0)
        self.assertEqual(audio.sfx, 0.5)

    def test_video_validation_resizes(self) -> None:
        video = VideoSettings(window_width=1, window_height=1)
        video.validate()
        self.assertEqual(video.window_width, 640)
        self.assertEqual(video.window_height, 360)


if __name__ == "__main__":
    unittest.main()
