"""Procedural audio: synthesise every sound effect and the music loop with NumPy.

Why synthesise instead of shipping .wav files?

* zero binary assets -> tiny PyInstaller bundle, no licensing questions,
* sounds can be parameterised at runtime (the paddle "pong" rises in pitch as
  the rally gets longer),
* guaranteed to work even if the assets folder is missing/corrupt.

All generation is done once at start-up and cached as ``pygame.Sound`` objects.
"""

from __future__ import annotations

import logging
import math

import numpy as np

log = logging.getLogger(__name__)

# Stereo interleaved int16 frames: shape (n, 2).
Samples = np.ndarray


def _time(n: int, rate: int) -> np.ndarray:
    return np.arange(n, dtype=np.float64) / float(rate)


def _envelope(n: int, attack: float, decay: float, rate: int) -> np.ndarray:
    """Linear attack + exponential decay, both normalised to sample counts."""
    a = max(1, int(attack * rate))
    env = np.empty(n, dtype=np.float64)
    if a >= n:
        env[:] = np.linspace(0.0, 1.0, n, endpoint=False)
        return env
    env[:a] = np.linspace(0.0, 1.0, a, endpoint=False)
    rest = n - a
    k = math.log(0.0005) / max(1e-6, decay * rate)
    env[a:] = np.exp(k * np.arange(rest, dtype=np.float64))
    return env


def _osc(kind: str, freq: np.ndarray | float, n: int, rate: int) -> np.ndarray:
    t = _time(n, rate)
    f = np.full(n, freq, dtype=np.float64) if np.isscalar(freq) else freq
    phase = np.cumsum(2.0 * np.pi * f / rate)
    if kind == "sine":
        return np.sin(phase)
    if kind == "square":
        return np.sign(np.sin(phase) + 1e-12)
    if kind == "saw":
        return 2.0 * ((phase / (2.0 * np.pi)) % 1.0) - 1.0
    if kind == "triangle":
        return 2.0 * np.abs(2.0 * ((phase / (2.0 * np.pi)) % 1.0) - 1.0) - 1.0
    raise ValueError(f"unknown wave {kind!r}")


def _sweep(f0: float, f1: float, n: int, rate: int, curve: float = 0.5) -> np.ndarray:
    """Frequency ramp from f0 to f1 following ``curve`` (0.5 == linear-ish)."""
    progress = np.linspace(0.0, 1.0, n) ** curve
    return f0 + (f1 - f0) * progress


def _to_stereo(mono: np.ndarray) -> Samples:
    mono = np.clip(mono, -1.0, 1.0)
    pcm = (mono * 32767.0).astype(np.int16)
    return np.repeat(pcm[:, None], 2, axis=1)


# --------------------------------------------------------------------------
# Individual SFX
# --------------------------------------------------------------------------
def make_paddle_hit(rate: int, pitch: float = 1.0) -> Samples:
    """Short square blip - the classic 'pong'."""
    dur = 0.075
    n = int(dur * rate)
    f = _sweep(760.0 * pitch, 300.0 * pitch, n, rate, curve=0.35)
    sig = 0.55 * _osc("square", f, n, rate)
    sig += 0.30 * _osc("sine", f * 2.0, n, rate)
    sig *= _envelope(n, 0.002, 0.035, rate)
    return _to_stereo(sig)


def make_wall_hit(rate: int) -> Samples:
    dur = 0.055
    n = int(dur * rate)
    f = _sweep(420.0, 240.0, n, rate, curve=0.4)
    sig = 0.5 * _osc("triangle", f, n, rate)
    sig *= _envelope(n, 0.001, 0.025, rate)
    return _to_stereo(sig)


def make_goal(rate: int, positive: bool) -> Samples:
    """Descending (conceded) or ascending (scored) two-note motif."""
    dur = 0.42
    n = int(dur * rate)
    t = _time(n, rate)
    notes = (330.0, 494.0, 660.0) if positive else (520.0, 390.0, 260.0)
    sig = np.zeros(n, dtype=np.float64)
    seg = n // len(notes)
    for i, freq in enumerate(notes):
        start, end = i * seg, (i + 1) * seg if i < len(notes) - 1 else n
        m = end - start
        if m <= 0:
            continue
        local = _osc("square", freq, m, rate) * _envelope(m, 0.004, 0.10, rate)
        sig[start:end] = local * 0.45
    # little noise burst tail for weight
    burst = np.random.default_rng(7).standard_normal(n) * _envelope(n, 0.001, 0.05, rate)
    sig += 0.10 * burst
    sig *= 1.0 - np.linspace(0.0, 0.15, n)
    del t
    return _to_stereo(sig)


def make_ui(rate: int, kind: str) -> Samples:
    table = {
        "move": (660.0, 0.035, "sine", 0.35),
        "select": (880.0, 0.075, "sine", 0.45),
        "back": (440.0, 0.07, "triangle", 0.4),
        "deny": (180.0, 0.11, "square", 0.30),
    }
    freq, dur, wave, vol = table.get(kind, table["move"])
    n = int(dur * rate)
    f = _sweep(freq * 1.25 if kind == "select" else freq, freq, n, rate, 0.4)
    sig = vol * _osc(wave, f, n, rate)
    sig *= _envelope(n, 0.002, 0.04, rate)
    return _to_stereo(sig)


def make_countdown(rate: int, final: bool) -> Samples:
    dur = 0.16 if final else 0.10
    n = int(dur * rate)
    freq = 880.0 if final else 520.0
    sig = 0.45 * _osc("square", freq, n, rate)
    sig += 0.15 * _osc("sine", freq * 2, n, rate)
    sig *= _envelope(n, 0.003, 0.09 if final else 0.05, rate)
    return _to_stereo(sig)


def make_fanfare(rate: int, won: bool) -> Samples:
    """End-of-match jingle."""
    seq = [(0.0, 392.0), (0.14, 523.25), (0.28, 659.25), (0.42, 783.99)] if won else [
        (0.0, 440.0), (0.16, 349.23), (0.32, 261.63), (0.48, 196.0)]
    dur = 0.85
    n = int(dur * rate)
    sig = np.zeros(n, dtype=np.float64)
    for offset, freq in seq:
        start = int(offset * rate)
        m = min(n - start, int(0.24 * rate))
        if m <= 0:
            continue
        tone = 0.40 * _osc("square", freq, m, rate)
        tone += 0.18 * _osc("sine", freq * 2, m, rate)
        tone *= _envelope(m, 0.006, 0.14, rate)
        sig[start:start + m] += tone
    if won:
        # sparkle arpeggio on top
        for i in range(6):
            start = int((0.5 + i * 0.045) * rate)
            m = min(n - start, int(0.06 * rate))
            if m <= 0:
                continue
            sig[start:start + m] += 0.16 * _envelope(m, 0.002, 0.03, rate) * _osc(
                "sine", 1046.5 * (1.0 + 0.02 * i), m, rate)
    sig *= 0.9
    return _to_stereo(sig)


def make_music_loop(rate: int, seconds: float = 8.0) -> Samples:
    """A calm 120 BPM chiptune loop: bass, arpeggio, hats.

    Deterministic (fixed RNG seed) so the soundtrack is identical each run.
    """
    bpm = 120.0
    beat = 60.0 / bpm
    n = int(seconds * rate)
    t = _time(n, rate)
    sig = np.zeros(n, dtype=np.float64)

    # i - VI - III - VII progression in A minor (A2 = 110 Hz root)
    roots = [110.0, 87.31, 130.81, 98.0]
    beat_per_chord = 4

    def add(freq: float, start_s: float, dur_s: float, vol: float, wave: str = "square") -> None:
        start = int(start_s * rate)
        m = min(n - start, int(dur_s * rate))
        if m <= 0 or start < 0:
            return
        tone = vol * _osc(wave, freq, m, rate)
        tone *= _envelope(m, 0.008, max(0.05, dur_s * 0.7), rate)
        sig[start:start + m] += tone

    total_beats = int(seconds / beat)
    for b in range(total_beats):
        time_s = b * beat
        chord = roots[(b // beat_per_chord) % len(roots)]
        step = (b // beat_per_chord) % len(roots)
        del step
        # bass on every beat
        add(chord, time_s, beat * 0.9, 0.22, "triangle")
        # arpeggio eighths
        for eighth in range(2):
            s = time_s + eighth * beat * 0.5
            arp_ratio = (1.0, 1.5, 2.0, 2.5)[(b * 2 + eighth) % 4]
            add(chord * arp_ratio, s, beat * 0.45, 0.11, "square")

    # hats: filtered noise on off-beats
    rng = np.random.default_rng(1337)
    for b in range(total_beats):
        start = int((b * beat + beat * 0.5) * rate)
        m = min(n - start, int(0.05 * rate))
        if m <= 0:
            continue
        noise = rng.standard_normal(m) * _envelope(m, 0.001, 0.012, rate)
        sig[start:start + m] += 0.055 * noise

    # gentle sidechain-ish duck so it breathes with the beat
    duck = 0.85 + 0.15 * np.sin(2.0 * np.pi * (t / beat))
    sig *= duck
    sig /= max(1e-6, float(np.max(np.abs(sig)))) / 0.85
    return _to_stereo(sig)
