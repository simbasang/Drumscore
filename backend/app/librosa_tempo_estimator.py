from pathlib import Path

import librosa
import numpy as np

from app.tempo_estimation import TempoEstimationError

_MIN_BPM = 40.0
_MAX_BPM = 300.0


class LibrosaTempoEstimator:
    def estimate(self, audio_path: Path) -> float:
        try:
            y, sr = librosa.load(str(audio_path), sr=None, mono=True)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            tempo = float(np.asarray(tempo).reshape(-1)[0])
            onset_times = librosa.onset.onset_detect(y=y, sr=sr, units="time")
            tempo = _correct_octave_error(tempo, np.asarray(onset_times))
        except Exception as error:
            raise TempoEstimationError(f"Failed to estimate tempo: {error}") from error

        return tempo


def _correct_octave_error(tempo: float, onset_times: np.ndarray) -> float:
    """Beat trackers commonly report half or double the true tempo (an
    octave error). Prefer whichever of tempo, tempo*2, or tempo/2 best
    fits the actual onset positions, since the raw beat-tracker estimate
    alone can't distinguish between them."""
    if onset_times.size == 0:
        return tempo

    # Slowest first: onsets landing exactly on a coarse grid also land
    # exactly on every finer multiple of it, so ties are common. Ordering
    # candidates slowest-to-fastest makes min()'s stable tie-break prefer
    # the slower tempo whenever two candidates fit equally well.
    candidates = []
    if tempo / 2 >= _MIN_BPM:
        candidates.append(tempo / 2)
    candidates.append(tempo)
    if tempo * 2 <= _MAX_BPM:
        candidates.append(tempo * 2)

    def phase_error(bpm: float) -> float:
        beat_period = 60.0 / bpm
        phase = (onset_times % beat_period) / beat_period
        distance_to_nearest_beat = np.minimum(phase, 1 - phase)
        return float(np.mean(distance_to_nearest_beat))

    return min(candidates, key=phase_error)
