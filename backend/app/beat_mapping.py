import dataclasses

from app.timing import BeatPoint
from app.transcription import DrumEvent

DEFAULT_BEATS_PER_MEASURE = 4
DEFAULT_SUBDIVISIONS_PER_BEAT = 4


def _beat_period(beats: list[BeatPoint], index: int) -> float:
    """The local beat duration around beats[index]: the interval to its
    next point, or (if index is the last one) the interval from its
    previous point. Assumes beats is gapless - each entry exactly one
    beat after the previous, matching what LibrosaBeatDetector actually
    produces."""
    if index < len(beats) - 1:
        return beats[index + 1].source_time - beats[index].source_time
    return beats[index].source_time - beats[index - 1].source_time


def _locate(beats: list[BeatPoint], time: float) -> int:
    """Index of the last beat point at or before time, or 0 if time
    precedes every point (extrapolation is handled by the caller via
    ordinary offset arithmetic, not by this function)."""
    index = 0
    for i, beat in enumerate(beats):
        if beat.source_time <= time:
            index = i
        else:
            break
    return index


def _absolute_beat_index(beat: BeatPoint, beats_per_measure: int) -> int:
    return (beat.measure - 1) * beats_per_measure + (beat.beat - 1)


def quantize_events_with_beats(
    events: list[DrumEvent],
    beats: list[BeatPoint],
    beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE,
    subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT,
) -> list[DrumEvent]:
    """Assigns measure/beat/subdivision using the LOCAL interval around
    the nearest real detected beat, instead of a single constant-BPM grid
    anchored at t=0 - see docs/ARCHITECTURE_V1.md's Timing model and
    docs/superpowers/plans/2026-09-21-beat-anchored-quantization.md for
    the worked examples this design is based on."""
    if len(beats) < 2:
        raise ValueError("quantize_events_with_beats requires at least two beats")

    quantized: list[DrumEvent] = []
    for event in events:
        i = _locate(beats, event.time)
        period = _beat_period(beats, i)
        subdivisions_from_i = round(
            (event.time - beats[i].source_time) / period * subdivisions_per_beat
        )
        beat_offset, subdivision = divmod(subdivisions_from_i, subdivisions_per_beat)

        absolute_index = _absolute_beat_index(beats[i], beats_per_measure) + beat_offset
        measure = absolute_index // beats_per_measure + 1
        beat_in_measure = absolute_index % beats_per_measure + 1

        quantized.append(
            dataclasses.replace(
                event, measure=measure, beat=beat_in_measure, subdivision=subdivision
            )
        )
    return quantized


def beat_anchored_position_to_seconds(
    beats: list[BeatPoint],
    measure: int,
    beat: int,
    subdivision: int,
    beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE,
    subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT,
) -> float:
    """The exact inverse of quantize_events_with_beats: reconstructs the
    real-world time a musical position corresponds to, using the same
    local beat anchors quantization used. Used to compute quantization
    error (reconstructed time - event.time) for diagnostics."""
    if len(beats) < 2:
        raise ValueError("beat_anchored_position_to_seconds requires at least two beats")

    target_absolute_index = (measure - 1) * beats_per_measure + (beat - 1)
    reference_absolute_index = _absolute_beat_index(beats[0], beats_per_measure)
    offset_from_first = target_absolute_index - reference_absolute_index

    ref = max(0, min(offset_from_first, len(beats) - 1))
    beat_delta = offset_from_first - ref
    period = _beat_period(beats, ref)

    return beats[ref].source_time + (beat_delta + subdivision / subdivisions_per_beat) * period
