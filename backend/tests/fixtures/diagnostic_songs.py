import dataclasses
from typing import Sequence

import numpy as np

from app.transcription import DrumInstrument

SAMPLE_RATE = 22050

_DECAY_TIME_CONSTANTS: dict[DrumInstrument, float] = {
    DrumInstrument.KICK: 0.15,
    DrumInstrument.SNARE: 0.15,
    DrumInstrument.HIHAT_CLOSED: 0.03,
    DrumInstrument.HIHAT_OPEN: 0.25,
    DrumInstrument.CRASH: 1.0,
    DrumInstrument.RIDE: 0.4,
    DrumInstrument.TOM_LOW: 0.2,
    DrumInstrument.TOM_MID: 0.2,
    DrumInstrument.TOM_HIGH: 0.2,
}

_TONAL_FREQUENCIES_HZ: dict[DrumInstrument, float] = {
    DrumInstrument.KICK: 60.0,
    DrumInstrument.TOM_LOW: 120.0,
    DrumInstrument.TOM_MID: 180.0,
    DrumInstrument.TOM_HIGH: 240.0,
}

_NOISE_INSTRUMENTS = {
    DrumInstrument.SNARE,
    DrumInstrument.HIHAT_CLOSED,
    DrumInstrument.HIHAT_OPEN,
    DrumInstrument.CRASH,
    DrumInstrument.RIDE,
}


@dataclasses.dataclass(frozen=True)
class ExpectedHit:
    time: float
    instrument: DrumInstrument


def _synthesize_hit(
    instrument: DrumInstrument, sample_rate: int, rng: np.random.Generator
) -> np.ndarray:
    decay = _DECAY_TIME_CONSTANTS[instrument]
    length = int(round(decay * 4 * sample_rate))
    t = np.arange(length) / sample_rate
    envelope = np.exp(-t / decay)

    if instrument in _NOISE_INSTRUMENTS:
        waveform = rng.standard_normal(length)
    else:
        frequency = _TONAL_FREQUENCIES_HZ[instrument]
        waveform = np.sin(2 * np.pi * frequency * t)

    return waveform * envelope


def render_events(
    hits: Sequence[ExpectedHit],
    duration_seconds: float,
    sample_rate: int = SAMPLE_RATE,
    noise_seed: int = 20260920,
) -> np.ndarray:
    rng = np.random.default_rng(noise_seed)
    total_samples = int(round(duration_seconds * sample_rate))
    audio = np.zeros(total_samples, dtype=np.float64)

    for hit in hits:
        waveform = _synthesize_hit(hit.instrument, sample_rate, rng)
        start = int(round(hit.time * sample_rate))
        if start >= total_samples:
            continue
        end = min(start + len(waveform), total_samples)
        audio[start:end] += waveform[: end - start]

    peak = np.max(np.abs(audio)) if audio.size else 0.0
    if peak > 1.0:
        audio = audio / peak

    return audio.astype(np.float32)
