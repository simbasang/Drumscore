from pathlib import Path

import librosa
import numpy as np

from app.beat_detection import BeatDetectionError
from app.librosa_tempo_estimator import LibrosaTempoEstimator
from app.tempo_estimation import TempoEstimationError
from app.timing import BeatPoint

DEFAULT_BEATS_PER_MEASURE = 4


class LibrosaBeatDetector:
    def __init__(self, beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE) -> None:
        self._beats_per_measure = beats_per_measure
        self._tempo_estimator = LibrosaTempoEstimator()

    def detect(self, audio_path: Path) -> list[BeatPoint]:
        try:
            bpm = self._tempo_estimator.estimate(audio_path)
            y, sr = librosa.load(str(audio_path), sr=None, mono=True)
            onset_times = librosa.onset.onset_detect(y=y, sr=sr, units="time")
        except TempoEstimationError as error:
            raise BeatDetectionError(f"Failed to detect beats: {error}") from error
        except Exception as error:  # noqa: BLE001 - wrap any decode/analysis failure
            raise BeatDetectionError(f"Failed to detect beats: {error}") from error

        onset_times = np.asarray(onset_times)
        if onset_times.size == 0:
            raise BeatDetectionError("No onsets detected; cannot determine beat phase")

        beat_period = 60.0 / bpm
        phase_offset = _estimate_phase_offset(beat_period, onset_times)
        first_beat_time = _snap_to_grid(float(onset_times[0]), phase_offset, beat_period)
        while first_beat_time < 0:
            first_beat_time += beat_period

        duration = len(y) / sr
        return _build_beat_grid(first_beat_time, beat_period, duration, self._beats_per_measure)


def _estimate_phase_offset(beat_period: float, onset_times: np.ndarray) -> float:
    """Circular mean of onset times modulo beat_period - robust to onsets
    that fall slightly off the grid (humanized timing, fills, noise), since
    no single onset can pull the estimate to a wildly wrong phase."""
    phases = (onset_times % beat_period) / beat_period * 2 * np.pi
    mean_angle = np.arctan2(np.mean(np.sin(phases)), np.mean(np.cos(phases)))
    phase_offset = (mean_angle / (2 * np.pi)) * beat_period
    return float(phase_offset % beat_period)


def _snap_to_grid(time: float, phase_offset: float, beat_period: float) -> float:
    """The beat-grid time (phase_offset + k * beat_period) nearest to time.
    The circular-mean phase alone only fixes the position within one cycle;
    this recovers the actual absolute anchor - e.g. whether there was 2
    seconds of silence before the beat grid starts."""
    k = round((time - phase_offset) / beat_period)
    return phase_offset + beat_period * k


def _build_beat_grid(
    first_beat_time: float,
    beat_period: float,
    duration: float,
    beats_per_measure: int,
) -> list[BeatPoint]:
    beats: list[BeatPoint] = []
    index = 0
    time = first_beat_time
    while time < duration:
        beat_in_measure = index % beats_per_measure
        beats.append(
            BeatPoint(
                source_time=time,
                measure=index // beats_per_measure + 1,
                beat=beat_in_measure + 1,
                is_downbeat=beat_in_measure == 0,
            )
        )
        index += 1
        time = first_beat_time + index * beat_period
    return beats
