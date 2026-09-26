import tempfile
from collections import Counter
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from app.audio_mix import mix_stems
from app.beat_detection import BeatDetectionError
from app.beat_regularization import regularize_beats, typical_beat_period
from app.timing import BeatPoint

DEFAULT_BEATS_PER_MEASURE = 4
_CHECKPOINT = "final0"

Tracker = Callable[[Path], tuple[np.ndarray, np.ndarray]]


class BeatThisBeatDetector:
    """Beat and downbeat tracking with the Beat This! model (CPJKU, MIT
    licensed code and weights). Beats are the tracker's own source-time
    detections, not a grid built from one tempo, so they follow the
    recording's tempo drift. It listens to the full mix, rebuilt from both
    stems: the model was trained on mixes, and on a drums-only stem it
    misjudged a shuffle's pulse and most downbeats (docs/tempo-evaluation.md)."""

    def __init__(self, tracker: Tracker | None = None) -> None:
        self._tracker = tracker

    def detect(self, drums_path: Path, accompaniment_path: Path) -> list[BeatPoint]:
        try:
            with tempfile.TemporaryDirectory(prefix="beats-") as scratch:
                mix = mix_stems(drums_path, accompaniment_path, Path(scratch) / "mix.wav")
                beat_times, downbeat_times = self._get_tracker()(mix)
        except Exception as error:  # noqa: BLE001 - wrap any decode/model failure
            raise BeatDetectionError(f"Failed to detect beats: {error}") from error
        return beat_points_from_tracker(regularize_beats(list(beat_times)), list(downbeat_times))

    def _get_tracker(self) -> Tracker:
        if self._tracker is None:
            # Imported lazily: loading torch and the checkpoint is slow and
            # only the worker's map_tempo stage needs it.
            from beat_this.inference import File2Beats

            file2beats = File2Beats(checkpoint_path=_CHECKPOINT, device="cpu", dbn=False)
            self._tracker = lambda path: file2beats(str(path))
        return self._tracker


def beat_points_from_tracker(
    beat_times: Sequence[float],
    downbeat_times: Sequence[float],
    beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE,
) -> list[BeatPoint]:
    """Numbers tracked beats into fixed-length measures. The measure phase
    (which beat is beat 1) comes from the detected downbeats, by majority
    vote so one misplaced downbeat can't shift the whole song. Beats before
    the first downbeat are a pickup at the end of measure 1. The meter
    itself stays fixed at beats_per_measure (see TECHNICAL_DEBT.md, "Meter
    is hardcoded 4/4")."""
    phase = _downbeat_phase(beat_times, downbeat_times, beats_per_measure)
    offset = 1 if phase > 0 else 0
    beats: list[BeatPoint] = []
    for index, time in enumerate(beat_times):
        position = index - phase
        beat = position % beats_per_measure + 1
        beats.append(
            BeatPoint(
                source_time=float(time),
                measure=position // beats_per_measure + 1 + offset,
                beat=beat,
                is_downbeat=beat == 1,
            )
        )
    return beats


def _downbeat_phase(beat_times: Sequence[float], downbeat_times: Sequence[float], beats_per_measure: int) -> int:
    if len(beat_times) == 0 or len(downbeat_times) == 0:
        return 0
    times = np.asarray(beat_times, dtype=float)
    votes = Counter(int(np.argmin(np.abs(times - downbeat))) % beats_per_measure for downbeat in downbeat_times)
    top = max(votes.values())
    return min(phase for phase, count in votes.items() if count == top)


def tempo_from_beats(beats: Sequence[BeatPoint]) -> float:
    """The song's typical tempo in BPM (see typical_beat_period)."""
    return 60.0 / typical_beat_period([beat.source_time for beat in beats])
