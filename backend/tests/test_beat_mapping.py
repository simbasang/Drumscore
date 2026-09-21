import pytest

from app.beat_mapping import (
    beat_anchored_position_to_seconds,
    quantize_events_with_beats,
)
from app.timing import BeatPoint
from app.transcription import DrumEvent, DrumInstrument


def _event(time: float) -> DrumEvent:
    return DrumEvent(id="e", time=time, instrument=DrumInstrument.KICK)


def _beat(time: float, measure: int, beat: int, is_downbeat: bool | None = None) -> BeatPoint:
    return BeatPoint(
        source_time=time,
        measure=measure,
        beat=beat,
        is_downbeat=is_downbeat if is_downbeat is not None else beat == 1,
    )


# Evenly spaced beats starting at t=0 - equivalent to a constant 120bpm
# grid, letting these fixtures double-check beat-anchored quantization
# against known-good numbers.
CONSTANT_TEMPO_BEATS = [
    _beat(0.0, 1, 1),
    _beat(0.5, 1, 2),
    _beat(1.0, 1, 3),
    _beat(1.5, 1, 4),
    _beat(2.0, 2, 1),
    _beat(2.5, 2, 2),
]

# The exact scenario #40's detector produces: the first real beat is NOT
# at t=0.
OFFSET_BEATS = [
    _beat(2.5, 1, 1),
    _beat(3.0, 1, 2),
    _beat(3.5, 1, 3),
    _beat(4.0, 1, 4),
    _beat(4.5, 2, 1),
]

# A tempo change partway through: the first interval is 0.5s, the rest
# are 0.6s.
VARIABLE_TEMPO_BEATS = [
    _beat(0.0, 1, 1),
    _beat(0.5, 1, 2),
    _beat(1.1, 1, 3),
    _beat(1.7, 1, 4),
]


def test_quantize_events_with_beats_matches_the_constant_grid_case():
    events = [_event(0.13)]

    quantized = quantize_events_with_beats(events, CONSTANT_TEMPO_BEATS)

    assert quantized[0].measure == 1
    assert quantized[0].beat == 1
    assert quantized[0].subdivision == 1


def test_quantize_events_with_beats_preserves_original_time():
    events = [_event(1.23456)]

    quantized = quantize_events_with_beats(events, CONSTANT_TEMPO_BEATS)

    assert quantized[0].time == 1.23456


def test_quantize_events_with_beats_anchors_to_the_first_beats_real_time_not_zero():
    # The whole point of this epic: an event exactly at the first real
    # beat's time must quantize to beat 1, not to whatever a t=0-anchored
    # grid would have computed for that same absolute time.
    events = [_event(2.5)]

    quantized = quantize_events_with_beats(events, OFFSET_BEATS)

    assert quantized[0].measure == 1
    assert quantized[0].beat == 1
    assert quantized[0].subdivision == 0


def test_quantize_events_with_beats_uses_the_local_interval_during_a_tempo_change():
    # 1.4s falls inside the SECOND interval (1.1 -> 1.7, 0.6s long), not
    # the first (0.0 -> 0.5, 0.5s long). Using the wrong (global/first)
    # interval would produce a different subdivision.
    events = [_event(1.4)]

    quantized = quantize_events_with_beats(events, VARIABLE_TEMPO_BEATS)

    assert quantized[0].measure == 1
    assert quantized[0].beat == 3
    assert quantized[0].subdivision == 2


def test_quantize_events_with_beats_extrapolates_before_the_first_beat_point():
    # 2.25 is half a beat (0.25s, given the first 0.5s interval) before
    # the first detected beat. No special-casing - the same offset
    # arithmetic that works for in-range events also works here.
    events = [_event(2.25)]

    quantized = quantize_events_with_beats(events, OFFSET_BEATS)

    assert quantized[0].measure == 0
    assert quantized[0].beat == 4
    assert quantized[0].subdivision == 2


def test_quantize_events_with_beats_snaps_off_grid_human_timing_to_the_nearest_subdivision():
    # 0.14 is close to but not exactly on subdivision 1 (0.125s into the
    # first beat) - simulates humanized/slightly-off timing.
    events = [_event(0.14)]

    quantized = quantize_events_with_beats(events, CONSTANT_TEMPO_BEATS)

    assert quantized[0].subdivision == 1


def test_quantize_events_with_beats_raises_with_fewer_than_two_beats():
    with pytest.raises(ValueError, match="at least two"):
        quantize_events_with_beats([_event(0.0)], [CONSTANT_TEMPO_BEATS[0]])


def test_beat_anchored_position_to_seconds_round_trips_a_variable_tempo_position():
    # Same position produced by the tempo-change test above (measure 1,
    # beat 3, subdivision 2) must reconstruct back to exactly 1.4s.
    time = beat_anchored_position_to_seconds(VARIABLE_TEMPO_BEATS, measure=1, beat=3, subdivision=2)

    assert time == pytest.approx(1.4)


def test_beat_anchored_position_to_seconds_round_trips_an_extrapolated_before_first_position():
    time = beat_anchored_position_to_seconds(OFFSET_BEATS, measure=0, beat=4, subdivision=2)

    assert time == pytest.approx(2.25)


def test_beat_anchored_position_to_seconds_raises_with_fewer_than_two_beats():
    with pytest.raises(ValueError, match="at least two"):
        beat_anchored_position_to_seconds([CONSTANT_TEMPO_BEATS[0]], measure=1, beat=1, subdivision=0)
