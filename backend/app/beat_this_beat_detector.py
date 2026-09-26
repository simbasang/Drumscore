from collections import Counter
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from app.beat_detection import BeatDetectionError
from app.timing import BeatPoint

DEFAULT_BEATS_PER_MEASURE = 4
_CHECKPOINT = "final0"

# Beat This! reports beats on a 50 fps frame grid, so a single inter-beat
# interval is quantized to 20 ms (at ~115 BPM that is a ~4 BPM step).
# Measuring over spans of this many beats shrinks the step accordingly.
_TEMPO_SPAN_BEATS = 4

Tracker = Callable[[Path], tuple[np.ndarray, np.ndarray]]


class BeatThisBeatDetector:
    """Beat and downbeat tracking with the Beat This! model (CPJKU, MIT
    licensed code and weights). Beats are the tracker's own source-time
    detections, not a grid built from one tempo, so they follow the
    recording's tempo drift. Meant for the full mix: the model was trained
    on mixes and its downbeats are unreliable on a drums-only stem."""

    def __init__(self, tracker: Tracker | None = None) -> None:
        self._tracker = tracker

    def detect(self, audio_path: Path) -> list[BeatPoint]:
        try:
            beat_times, downbeat_times = self._get_tracker()(audio_path)
        except Exception as error:  # noqa: BLE001 - wrap any decode/model failure
            raise BeatDetectionError(f"Failed to detect beats: {error}") from error
        return beat_points_from_tracker(list(beat_times), list(downbeat_times))

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
    """The song's typical tempo: the median beat period over spans of
    several beats (single intervals for short sequences). The median keeps
    a missed or extra beat from skewing it."""
    if len(beats) < 2:
        raise ValueError(f"Tempo needs at least 2 beats, got {len(beats)}")
    times = np.array([beat.source_time for beat in beats])
    span = _TEMPO_SPAN_BEATS if len(times) > _TEMPO_SPAN_BEATS else 1
    periods = (times[span:] - times[:-span]) / span
    return float(60.0 / np.median(periods))
