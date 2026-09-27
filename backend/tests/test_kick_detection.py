from pathlib import Path

import numpy as np
import soundfile as sf

from app.kick_detection import LowBandKickDetector

SAMPLE_RATE = 44100
KICK_TIMES = [0.5, 1.0, 1.5, 2.0]


def _kick(duration: float = 0.25) -> np.ndarray:
    t = np.arange(int(duration * SAMPLE_RATE)) / SAMPLE_RATE
    return np.sin(2 * np.pi * 60 * t) * np.exp(-t / 0.06)


def _hat(duration: float = 0.05, seed: int = 0) -> np.ndarray:
    noise = np.random.default_rng(seed).standard_normal(int(duration * SAMPLE_RATE))
    high = np.diff(np.diff(noise, prepend=0.0), prepend=0.0)
    t = np.arange(len(high)) / SAMPLE_RATE
    return high / np.max(np.abs(high)) * np.exp(-t / 0.01)


def _snare(duration: float = 0.2, seed: int = 0) -> np.ndarray:
    t = np.arange(int(duration * SAMPLE_RATE)) / SAMPLE_RATE
    body = np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 330 * t)
    thump = 0.1 * np.sin(2 * np.pi * 110 * t)
    rattle = 0.3 * np.random.default_rng(seed).standard_normal(len(t))
    return (body + thump + rattle) * np.exp(-t / 0.05)


def _write(tmp_path: Path, hits: list[tuple[float, np.ndarray]], duration: float = 3.0, gain: float = 0.8) -> Path:
    audio = np.zeros(int(duration * SAMPLE_RATE))
    for time, sound in hits:
        start = int(time * SAMPLE_RATE)
        audio[start : start + len(sound)] += sound[: len(audio) - start]
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * gain
    path = tmp_path / "drums.wav"
    sf.write(path, audio, SAMPLE_RATE)
    return path


def _assert_found(detected: list[float], expected: list[float], tolerance: float = 0.02) -> None:
    assert len(detected) == len(expected), detected
    for found, wanted in zip(detected, expected):
        assert abs(found - wanted) <= tolerance, (found, wanted)


def test_detects_low_sine_bursts_at_their_onsets(tmp_path):
    path = _write(tmp_path, [(time, _kick()) for time in KICK_TIMES])

    result = LowBandKickDetector().detect(path)

    _assert_found(result, KICK_TIMES)


def test_ignores_high_frequency_noise_bursts(tmp_path):
    path = _write(tmp_path, [(0.25 * i, _hat(seed=i)) for i in range(1, 11)])

    result = LowBandKickDetector().detect(path)

    assert result == []


def test_detects_kicks_under_simultaneous_hats(tmp_path):
    hats = [(0.25 * i, _hat(seed=i) * 2.0) for i in range(1, 11)]
    path = _write(tmp_path, [(time, _kick()) for time in KICK_TIMES] + hats)

    result = LowBandKickDetector().detect(path)

    _assert_found(result, KICK_TIMES)


def test_is_gain_independent(tmp_path):
    hits = [(time, _kick()) for time in KICK_TIMES]
    loud = LowBandKickDetector().detect(_write(tmp_path, hits, gain=0.9))

    quiet = LowBandKickDetector().detect(_write(tmp_path, hits, gain=0.05))

    assert quiet == loud


def test_silence_returns_empty(tmp_path):
    path = _write(tmp_path, [])

    result = LowBandKickDetector().detect(path)

    assert result == []


def test_respects_min_interval(tmp_path):
    path = _write(tmp_path, [(1.0, _kick()), (1.03, _kick())])

    result = LowBandKickDetector(min_interval_seconds=0.08).detect(path)

    _assert_found(result, [1.0])


def test_rejects_bursts_dominated_by_mid_frequencies(tmp_path):
    path = _write(tmp_path, [(time, _snare(seed=i)) for i, time in enumerate(KICK_TIMES)])

    result = LowBandKickDetector().detect(path)

    assert result == []


def test_detects_mid_heavy_bursts_when_the_ratio_guard_is_off(tmp_path):
    path = _write(tmp_path, [(time, _snare(seed=i)) for i, time in enumerate(KICK_TIMES)])

    result = LowBandKickDetector(min_low_mid_ratio=0.0).detect(path)

    _assert_found(result, KICK_TIMES)


def test_detects_kick_and_snare_struck_together(tmp_path):
    path = _write(tmp_path, [(time, _kick() + _snare(duration=0.25, seed=i)) for i, time in enumerate(KICK_TIMES)])

    result = LowBandKickDetector().detect(path)

    _assert_found(result, KICK_TIMES)
