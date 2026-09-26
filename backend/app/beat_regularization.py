from typing import Sequence

import numpy as np

# How far (as a fraction of the local beat period) a detection may sit
# from where the next beat is expected and still count as that beat.
# Double-time offbeats (0.5) and triplet positions (0.33/0.67) fall
# outside it.
_TOLERANCE = 0.3
# How far the local period may wander from the song's typical period, so
# a run of double-time detections can't drag the tracking to another
# metrical level.
_MAX_DRIFT = 0.25
_LOCAL_WINDOW = 8
# Consecutive steady intervals that make a detection a trustworthy anchor.
_ANCHOR_RUN = 4
# Beat trackers report beats on a frame grid (Beat This!: 20 ms); spans of
# several beats keep that quantization out of the typical period.
_PERIOD_SPAN_BEATS = 4


def typical_beat_period(beat_times: Sequence[float]) -> float:
    """The median beat period over spans of several beats (single
    intervals for short sequences), robust to a missed or extra beat."""
    if len(beat_times) < 2:
        raise ValueError(f"Tempo needs at least 2 beats, got {len(beat_times)}")
    times = np.asarray(beat_times, dtype=float)
    span = _PERIOD_SPAN_BEATS if len(times) > _PERIOD_SPAN_BEATS else 1
    return float(np.median((times[span:] - times[:-span]) / span))


def regularize_beats(beat_times: Sequence[float]) -> list[float]:
    """Turns a tracker's beat detections into exactly one entry per beat,
    which beat numbering, quantization and the metronome all assume.
    Starts from a stable anchor (the first run of beats at the song's
    typical period, so an intro tracked in double time or a spurious first
    detection can't set the phase) and walks outward in both directions:
    keeps the detection nearest each expected beat, drops extra detections
    (spurious beats, double-time or triplet sections) and fills skipped
    beats by evenly dividing the gap up to the next detection. Kept
    detections keep their exact source times."""
    if len(beat_times) < 3:
        return list(beat_times)
    typical = typical_beat_period(beat_times)
    detections = [float(t) for t in beat_times]
    anchor = _stable_anchor(detections, typical)

    forward = _walk(detections[anchor:], typical)
    backward = _walk([-t for t in reversed(detections[: anchor + 1])], typical)
    return [-t for t in reversed(backward[1:])] + forward


def _stable_anchor(detections: list[float], typical: float) -> int:
    """Index of the first detection that starts _ANCHOR_RUN consecutive
    intervals within tolerance of the typical period (0 if none does)."""
    intervals = np.diff(detections)
    steady = np.abs(intervals / typical - 1) <= _TOLERANCE
    for index in range(len(steady) - _ANCHOR_RUN + 1):
        if steady[index : index + _ANCHOR_RUN].all():
            return index
    return 0


def _walk(detections: list[float], typical: float) -> list[float]:
    """One entry per beat, walking forward from detections[0]."""
    result = [detections[0]]
    real_intervals: list[float] = []
    period = typical
    index = 1
    while index < len(detections):
        last = result[-1]
        in_window = []
        for i in range(index, len(detections)):
            gap = detections[i] - last
            if gap > (1 + _TOLERANCE) * period:
                break
            if gap >= (1 - _TOLERANCE) * period:
                in_window.append(i)
        if in_window:
            chosen = min(in_window, key=lambda i: abs(detections[i] - last - period))
            real_intervals.append(detections[chosen] - last)
            result.append(detections[chosen])
            index = chosen + 1
        else:
            later = [i for i in range(index, len(detections)) if detections[i] - last > (1 + _TOLERANCE) * period]
            if not later:
                break
            chosen = later[0]
            gap = detections[chosen] - last
            count = max(1, round(gap / period))
            result.extend(last + gap * step / count for step in range(1, count))
            result.append(detections[chosen])
            index = chosen + 1
        recent = real_intervals[-_LOCAL_WINDOW:]
        if recent:
            period = float(
                np.clip(np.median(recent), typical * (1 - _MAX_DRIFT), typical * (1 + _MAX_DRIFT))
            )
    return result
