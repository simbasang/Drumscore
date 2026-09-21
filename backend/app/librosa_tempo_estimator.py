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
            tempo = _correct_pulse_error(tempo, np.asarray(onset_times))
        except Exception as error:
            raise TempoEstimationError(f"Failed to estimate tempo: {error}") from error

        return tempo


# Ratios covering both octave errors (0.5x/2x) and simple-vs-compound
# pulse-level errors (2/3x/1.5x, e.g. TECHNICAL_DEBT.md's 123-vs-184.6
# case: 123 * 1.5 ~= 184.6) - the same class of mistake (the beat
# tracker locked onto a plausible but wrong periodicity), scored by the
# same phase-fit heuristic. Ascending order matters for the stable
# tie-break explained below.
_CANDIDATE_RATIOS: tuple[float, ...] = (0.5, 2.0 / 3.0, 1.0, 1.5, 2.0)


def _correct_pulse_error(tempo: float, onset_times: np.ndarray) -> float:
    """Beat trackers commonly report a plausible but wrong multiple of the
    true tempo - not just an octave (half/double) but also a simple-vs-
    compound pulse-level mistake (2/3x or 1.5x). Prefer whichever candidate
    best fits the actual onset positions, since the raw beat-tracker
    estimate alone can't distinguish between them."""
    if onset_times.size == 0:
        return tempo

    # Slowest first: onsets landing exactly on a coarse grid also land
    # exactly on every finer multiple of it, so ties are common. Ordering
    # candidates slowest-to-fastest makes min()'s stable tie-break prefer
    # the slower tempo whenever two candidates fit equally well.
    candidates = [
        tempo * ratio for ratio in _CANDIDATE_RATIOS if _MIN_BPM <= tempo * ratio <= _MAX_BPM
    ]

    def phase_error(bpm: float) -> float:
        beat_period = 60.0 / bpm
        phase = (onset_times % beat_period) / beat_period
        distance_to_nearest_beat = np.minimum(phase, 1 - phase)
        return float(np.mean(distance_to_nearest_beat))

    return min(candidates, key=phase_error)
