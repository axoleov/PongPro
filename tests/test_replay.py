"""Replay recorder/player: fidelity, seeking, serialisation contract."""

from __future__ import annotations

import json
import unittest

from pongpro.gameplay.replay import (
    REPLAY_VERSION,
    Frame,
    ReplayPlayer,
    ReplayRecorder,
)


class RecorderTests(unittest.TestCase):
    def test_capture_then_finish_payload(self) -> None:
        recorder = ReplayRecorder()
        recorder.start({"label": "TEST", "seed": 42, "fps": 120})
        self.assertTrue(recorder.active)

        recorder.capture(0.0, 640.0, 360.0, 430.0, 0.0, 300.0, 400.0, 0, 0, 0, 0)
        recorder.capture(1 / 120, 643.6, 360.5, 430.0, 10.0, 301.0, 399.0,
                         1, 0, 2, 2)

        payload = recorder.finish(score=(5, 3), winner=0, duration=12.5)
        self.assertEqual(payload["version"], REPLAY_VERSION)
        self.assertEqual(payload["final_score"], [5, 3])
        self.assertEqual(payload["winner"], 0)
        self.assertEqual(payload["seed"], 42)
        self.assertEqual(len(payload["frames"]), 2)

    def test_inactive_recorder_ignores_captures(self) -> None:
        recorder = ReplayRecorder()
        recorder.capture(0.0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0)
        self.assertEqual(recorder.frame_count, 0)

    def test_coordinates_survive_tenths_round_trip(self) -> None:
        recorder = ReplayRecorder()
        recorder.start({})
        recorder.capture(0.5, 123.4, 567.8, -430.0, 99.9, 111.1, 222.2,
                         2, 3, 7, 2)
        payload = recorder.finish(score=(1, 1), winner=1, duration=1.0)
        player = ReplayPlayer(payload)
        frame = player.at(0)
        self.assertAlmostEqual(frame.bx, 123.4, delta=0.11)
        self.assertAlmostEqual(frame.by, 567.8, delta=0.11)
        self.assertAlmostEqual(frame.bvx, -430.0, delta=0.11)
        self.assertAlmostEqual(frame.p1y, 111.1, delta=0.11)
        self.assertAlmostEqual(frame.p2y, 222.2, delta=0.11)
        self.assertEqual((frame.s1, frame.s2), (2, 3))
        self.assertEqual(frame.rally, 7)

    def test_round_trip_through_json(self) -> None:
        recorder = ReplayRecorder()
        recorder.start({"label": "JSON"})
        for i in range(50):
            recorder.capture(i / 120, 640 + i, 360 - i, 430, 0, 300, 400,
                             1, 0, i, 2)
        payload = recorder.finish(score=(1, 0), winner=0, duration=0.5)

        text = json.dumps(payload, separators=(",", ":"))
        player = ReplayPlayer(json.loads(text))
        self.assertEqual(player.frame_count, 50)
        # Frame times are stored in whole milliseconds.
        self.assertAlmostEqual(player.duration, 49 / 120, delta=0.001)
        self.assertEqual(player.at(49).by, 360 - 49)

    def test_recorder_stops_at_safety_cap(self) -> None:
        from pongpro.gameplay.replay import MAX_FRAMES

        recorder = ReplayRecorder()
        recorder.start({})
        for i in range(MAX_FRAMES + 50):
            recorder.capture(i / 120, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        self.assertEqual(recorder.frame_count, MAX_FRAMES)


class PlayerTests(unittest.TestCase):
    def setUp(self) -> None:
        recorder = ReplayRecorder()
        recorder.start({"label": "PLAYER TEST", "fps": 100})
        for i in range(100):
            recorder.capture(i / 100, 500 + i, 300, 100, 0, 200, 400,
                             i // 50, 0, i, 2)
        self.player = ReplayPlayer(
            recorder.finish(score=(2, 1), winner=0, duration=1.0))

    def test_duration_and_score(self) -> None:
        self.assertAlmostEqual(self.player.duration, 0.99, delta=1e-6)
        self.assertEqual(self.player.final_score, (2, 1))
        self.assertEqual(self.player.winner, 0)
        self.assertEqual(self.player.fps, 100)

    def test_index_at_time_is_clamped(self) -> None:
        self.assertEqual(self.player.index_at_time(-5.0), 0)
        self.assertEqual(self.player.index_at_time(100.0), 99)
        self.assertEqual(self.player.index_at_time(0.5), 50)

    def test_at_clamps_out_of_range(self) -> None:
        self.assertEqual(self.player.at(-10).bx, 500.0)
        self.assertEqual(self.player.at(10_000).bx, 599.0)

    def test_frame_is_a_named_tuple(self) -> None:
        frame = self.player.at(0)
        self.assertIsInstance(frame, Frame)
        self.assertEqual(frame.ball_speed, 100.0)

    def test_empty_payload_is_falsy(self) -> None:
        self.assertFalse(ReplayPlayer({"frames": []}))
        self.assertEqual(ReplayPlayer({"frames": []}).frame_count, 0)
        self.assertEqual(ReplayPlayer({"frames": []}).duration, 0.0)


if __name__ == "__main__":
    unittest.main()
