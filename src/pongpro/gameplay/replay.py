"""Match recording and playback.

Every match is continuously recorded at the fixed simulation rate (120 Hz) so
the results screen can offer *"Watch replay"* without any special-case code in
the gameplay itself: we simply capture the state that was going to be rendered
anyway.

Storage format (JSON, versioned)::

    { "version": 1, "seed": 1234, "mode": "solo", ...,
      "frames": [[t_ms, bx, by, bvx, bvy, p1y, p2y, s1, s2, rally, phase], ...] }

Coordinates are stored as *tenths of a pixel* integers to keep a 3-minute match
around ~1 MB instead of ~4 MB, and to guarantee that a replay round-trips
exactly (no float formatting drift).
"""

from __future__ import annotations

import math
import time
from typing import Any, NamedTuple

SCALE = 10  # tenths of a pixel
REPLAY_VERSION = 1
MAX_FRAMES = 120 * 60 * 15  # 15 minutes at 120 Hz, hard safety cap


class Frame(NamedTuple):
    """One decoded simulation snapshot."""

    t: float  # seconds since recording start
    bx: float
    by: float
    bvx: float
    bvy: float
    p1y: float
    p2y: float
    s1: int
    s2: int
    rally: int
    phase: int  # MatchPhase ordinal, kept numeric for compactness

    @property
    def ball_speed(self) -> float:
        return math.hypot(self.bvx, self.bvy)


class ReplayRecorder:
    """Ring-free append-only capture of fixed-step snapshots."""

    __slots__ = ("_frames", "metadata", "_started")

    def __init__(self) -> None:
        self._frames: list[list[int]] = []
        self.metadata: dict[str, Any] = {}
        self._started = False

    def start(self, metadata: dict[str, Any]) -> None:
        self._frames.clear()
        self.metadata = dict(metadata)
        self._started = True

    @property
    def active(self) -> bool:
        return self._started

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    def capture(
        self, t: float,
        bx: float, by: float, bvx: float, bvy: float,
        p1y: float, p2y: float,
        s1: int, s2: int, rally: int, phase: int,
    ) -> None:
        if not self._started or len(self._frames) >= MAX_FRAMES:
            return
        self._frames.append([
            int(t * 1000.0),
            int(round(bx * SCALE)),
            int(round(by * SCALE)),
            int(round(bvx * SCALE)),
            int(round(bvy * SCALE)),
            int(round(p1y * SCALE)),
            int(round(p2y * SCALE)),
            int(s1),
            int(s2),
            int(rally),
            int(phase),
        ])

    def finish(self, *, score: tuple[int, int], winner: int | None,
               duration: float) -> dict[str, Any]:
        self._started = False
        payload = dict(self.metadata)
        payload.update({
            "version": REPLAY_VERSION,
            "created_unix": int(time.time()),
            "final_score": [int(score[0]), int(score[1])],
            "winner": -1 if winner is None else int(winner),
            "duration": round(float(duration), 3),
            "frames": self._frames,
        })
        return payload

    def frames(self) -> list[list[int]]:
        return self._frames


class ReplayPlayer:
    """Read-side: decodes frames on demand and supports seek/scrub."""

    __slots__ = ("payload", "_count")

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        raw = payload.get("frames") or []
        self._count = len(raw)

    def __bool__(self) -> bool:
        return self._count > 0

    @property
    def frame_count(self) -> int:
        return self._count

    @property
    def duration(self) -> float:
        if self._count == 0:
            return 0.0
        return float(self.raw(self._count - 1)[0]) / 1000.0

    @property
    def fps(self) -> float:
        return float(self.payload.get("fps", 120)) or 120.0

    @property
    def final_score(self) -> tuple[int, int]:
        score = self.payload.get("final_score") or [0, 0]
        return (int(score[0]), int(score[1]))

    @property
    def winner(self) -> int:
        value = self.payload.get("winner", -1)
        return int(value)

    @property
    def label(self) -> str:
        return str(self.payload.get("label", "REPLAY"))

    def raw(self, index: int) -> list[int]:
        index = max(0, min(self._count - 1, index))
        return self.payload["frames"][index]

    def at(self, index: int) -> Frame:
        f = self.raw(index)
        return Frame(
            t=f[0] / 1000.0,
            bx=f[1] / SCALE, by=f[2] / SCALE,
            bvx=f[3] / SCALE, bvy=f[4] / SCALE,
            p1y=f[5] / SCALE, p2y=f[6] / SCALE,
            s1=f[7], s2=f[8], rally=f[9], phase=f[10],
        )

    def index_at_time(self, seconds: float) -> int:
        """Map a time in seconds to the nearest recorded frame index."""
        if self._count == 0:
            return 0
        index = int(seconds * self.fps)
        return max(0, min(self._count - 1, index))
