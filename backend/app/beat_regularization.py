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
    Walks the detections at the song's typical period (allowed to drift
    slowly), keeps the detection nearest each expected beat, drops extra
    detections (spurious beats, double-time or triplet sections) and fills
    skipped beats by evenly dividing the gap up to the next detection.
    Kept detections keep their exact source times."""
    if len(beat_times) < 3:
        return list(beat_times)
    typical = typical_beat_period(beat_times)
    detections = [float(t) for t in beat_times]

    result = [detections[0]]
    real_intervals: list[float] = []
    period = typical
    index = 1
    while index < len(detections):
        last = result[-1]
        in_window = [
            i
            for i in range(index, len(detections))
            if (1 - _TOLERANCE) * period <= detections[i] - last <= (1 + _TOLERANCE) * period
        ]
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
