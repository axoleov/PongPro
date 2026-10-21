"""Fixed-timestep accumulator: determinism, clamping and interpolation."""

from __future__ import annotations

import unittest

from pongpro.core.constants import FIXED_DT, MAX_FRAME_TIME, MAX_SUBSTEPS
from pongpro.core.timestep import FixedStepClock


class FixedStepClockTests(unittest.TestCase):
    def test_stable_frame_yields_one_step(self) -> None:
        clock = FixedStepClock()
        steps = clock.advance(FIXED_DT)
        self.assertEqual(steps, 1)
        self.assertAlmostEqual(clock.alpha, 0.0, places=6)

    def test_accumulates_fractional_time(self) -> None:
        clock = FixedStepClock()
        total = 0
        for _ in range(10):
            total += clock.advance(FIXED_DT * 0.5)
        # 10 * 0.5 ticks -> exactly 5 whole steps, remainder held in accumulator
        self.assertEqual(total, 5)
        self.assertAlmostEqual(clock.accumulator, 0.0, places=9)

    def test_alpha_stays_within_unit_interval(self) -> None:
        clock = FixedStepClock()
        for i in range(200):
            clock.advance(FIXED_DT * (0.37 + (i % 7) * 0.11))
            self.assertGreaterEqual(clock.alpha, 0.0)
            self.assertLessEqual(clock.alpha, 1.0)

    def test_huge_frame_is_clamped(self) -> None:
        """A 10-second hitch must not drain the whole budget (spiral of death)."""
        clock = FixedStepClock()
        steps = clock.advance(10.0)
        self.assertLessEqual(steps, MAX_SUBSTEPS)
        self.assertTrue(clock.was_clamped)
        self.assertLessEqual(clock.accumulator, MAX_FRAME_TIME)

    def test_substep_cap_drops_backlog(self) -> None:
        clock = FixedStepClock()
        steps = clock.advance(MAX_FRAME_TIME)
        self.assertLessEqual(steps, MAX_SUBSTEPS)
        self.assertGreater(clock.dropped_steps, 0)

    def test_never_negative_dt(self) -> None:
        clock = FixedStepClock()
        # A negative frame time is clamped to zero: no steps, no negative
        # accumulator, and the clock keeps working on the next real frame.
        self.assertEqual(clock.advance(-5.0), 0)
        self.assertGreaterEqual(clock.accumulator, 0.0)
        self.assertEqual(clock.advance(FIXED_DT), 1)

    def test_total_time_tracks_steps(self) -> None:
        clock = FixedStepClock()
        for _ in range(60):
            clock.advance(FIXED_DT)
        self.assertAlmostEqual(clock.total_simulated, 60 * FIXED_DT, places=9)
        self.assertEqual(clock.ticks, 60)

    def test_fps_ema_reports_realistic_value(self) -> None:
        clock = FixedStepClock()
        for _ in range(300):
            clock.advance(1.0 / 60.0)
        self.assertAlmostEqual(clock.measured_fps, 60.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
