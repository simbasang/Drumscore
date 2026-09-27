"""Kick onsets from the low band of a drum stem.

DrumScript's classifier calls an onset a kick only when at least 32% of the
whole slice's spectrum lies below 150 Hz. On a real drum stem, hi-hats,
snare and cymbals ringing over the kick dilute that ratio, so most kicks
DrumScript's own onset detector finds are then discarded (measured in
docs/kick-detection-evaluation.md). This detector looks at the low band
alone: a kick is a sharp rise of energy between low_hz and high_hz,
whatever else sounds at the same time, whose low band outweighs the
150-1000 Hz band where a snare's body sits (snares otherwise trigger the
low-band rise too).
"""

from pathlib import Path
from typing import Protocol

import librosa
import numpy as np

_SAMPLE_RATE = 44100
# A 23 ms window: log flux peaks as soon as the window's leading edge
# reaches the kick, so a longer window reports kicks earlier (2048 samples:
# median -16 ms against MDB labels; 1024: -7 ms). Its 43 Hz bins still
# resolve the 30-150 Hz band.
_N_FFT = 1024
_HOP_LENGTH = 256
# Scales band magnitudes before log1p so that near-silence stays near 0
# (no flux) while real kicks rise by several log units.
_LOG_GAIN = 100.0
# Local-maximum and moving-average windows for peak picking, in frames
# (~35 ms and ~58 ms at 44.1 kHz / hop 256).
_PEAK_WINDOW_FRAMES = 6
_AVERAGE_WINDOW_FRAMES = 10
_MID_BAND_HZ = (150.0, 1000.0)
# The low/mid ratio is taken at the loudest of the frames just after the
# onset (~23 ms), where the attack has reached both bands.
_RATIO_FRAMES = 4


class KickDetector(Protocol):
    def detect(self, audio_path: Path) -> list[float]: ...


class LowBandKickDetector:
    def __init__(
        self,
        low_hz: float = 30.0,
        high_hz: float = 150.0,
        delta: float = 1.0,
        min_interval_seconds: float = 0.08,
        min_low_mid_ratio: float = 0.3,
    ) -> None:
        self._low_hz = low_hz
        self._high_hz = high_hz
        self._delta = delta
        self._min_interval_seconds = min_interval_seconds
        self._min_low_mid_ratio = min_low_mid_ratio

    def detect(self, audio_path: Path) -> list[float]:
        audio, _ = librosa.load(audio_path, sr=_SAMPLE_RATE, mono=True)
        peak = np.max(np.abs(audio)) if audio.size else 0.0
        if peak == 0.0:
            return []
        # Peak normalisation makes the absolute delta threshold gain-independent.
        audio = audio / peak

        spectrum = np.abs(librosa.stft(audio, n_fft=_N_FFT, hop_length=_HOP_LENGTH))
        frequencies = librosa.fft_frequencies(sr=_SAMPLE_RATE, n_fft=_N_FFT)
        low = spectrum[(frequencies >= self._low_hz) & (frequencies <= self._high_hz)].sum(axis=0)
        mid = spectrum[(frequencies > _MID_BAND_HZ[0]) & (frequencies <= _MID_BAND_HZ[1])].sum(axis=0)
        envelope = np.log1p(_LOG_GAIN * low)
        flux = np.maximum(0.0, np.diff(envelope, prepend=envelope[0]))

        peaks = librosa.util.peak_pick(
            flux,
            pre_max=_PEAK_WINDOW_FRAMES,
            post_max=_PEAK_WINDOW_FRAMES,
            pre_avg=_AVERAGE_WINDOW_FRAMES,
            post_avg=_AVERAGE_WINDOW_FRAMES,
            delta=self._delta,
            wait=int(self._min_interval_seconds * _SAMPLE_RATE / _HOP_LENGTH),
        )
        kicks = [
            frame
            for frame in peaks
            if low[frame : frame + _RATIO_FRAMES].max()
            >= self._min_low_mid_ratio * mid[frame : frame + _RATIO_FRAMES].max()
        ]
        times = librosa.frames_to_time(np.array(kicks, dtype=int), sr=_SAMPLE_RATE, hop_length=_HOP_LENGTH)
        return [float(time) for time in times]
