import pytest

from app.beat_mapping import (
    beat_anchored_position_to_seconds,
    musical_position_to_seconds,
    quantize_events,
    quantize_events_with_beats,
)
from app.timing import BeatPoint
from app.transcription import DrumEvent, DrumInstrument


def _event(time: float) -> DrumEvent:
    return DrumEvent(id="e", time=time, instrument=DrumInstrument.KICK)


@pytest.mark.parametrize(
    "time,expected_measure,expected_beat,expected_subdivision",
    [
        (0.0, 1, 1, 0),
        (0.125, 1, 1, 1),
        (0.25, 1, 1, 2),
        (0.375, 1, 1, 3),
        (0.5, 1, 2, 0),
        (1.5, 1, 4, 0),
        (2.0, 2, 1, 0),
        (2.125, 2, 1, 1),
    ],
)
def test_quantize_events_assigns_measure_beat_subdivision_at_120bpm(
    time, expected_measure, expected_beat, expected_subdivision
):
    events = [_event(time)]

    quantized = quantize_events(events, bpm=120.0)

    assert quantized[0].measure == expected_measure
    assert quantized[0].beat == expected_beat
    assert quantized[0].subdivision == expected_subdivision


def test_quantize_events_snaps_to_nearest_subdivision():
    # 120 BPM -> 0.125s per 16th-note subdivision. 0.13s is closer to
    # subdivision 1 (0.125s) than subdivision 2 (0.25s).
    events = [_event(0.13)]

    quantized = quantize_events(events, bpm=120.0)

    assert quantized[0].subdivision == 1


def test_quantize_events_preserves_original_time():
    events = [_event(1.23456)]

    quantized = quantize_events(events, bpm=120.0)

    assert quantized[0].time == 1.23456


def test_quantize_events_preserves_event_order_and_count():
    events = [_event(0.0), _event(0.5), _event(1.0)]

    quantized = quantize_events(events, bpm=120.0)

    assert [e.time for e in quantized] == [0.0, 0.5, 1.0]


def test_quantize_events_supports_different_tempo():
    # 60 BPM -> 1s per beat, 0.25s per 16th-note subdivision.
    events = [_event(1.25)]

    quantized = quantize_events(events, bpm=60.0)

    assert quantized[0].measure == 1
    assert quantized[0].beat == 2
    assert quantized[0].subdivision == 1


@pytest.mark.parametrize(
    "measure,beat,subdivision,expected_time",
    [
        (1, 1, 0, 0.0),
        (1, 1, 1, 0.125),
        (1, 1, 2, 0.25),
        (1, 1, 3, 0.375),
        (1, 2, 0, 0.5),
        (1, 4, 0, 1.5),
        (2, 1, 0, 2.0),
        (2, 1, 1, 2.125),
    ],
)
def test_musical_position_to_seconds_at_120bpm(measure, beat, subdivision, expected_time):
    time = musical_position_to_seconds(measure, beat, subdivision, bpm=120.0)

    assert time == pytest.approx(expected_time)


def test_musical_position_to_seconds_is_the_inverse_of_quantize_events_on_grid_aligned_times():
    grid_aligned_time = 1.5
    event = _event(grid_aligned_time)

    quantized = quantize_events([event], bpm=120.0)[0]
    reconstructed_time = musical_position_to_seconds(
        quantized.measure, quantized.beat, quantized.subdivision, bpm=120.0
    )

    assert reconstructed_time == pytest.approx(grid_aligned_time)


def test_musical_position_to_seconds_supports_different_tempo():
    time = musical_position_to_seconds(1, 2, 1, bpm=60.0)

    assert time == pytest.approx(1.25)


def _beat(time: float, measure: int, beat: int, is_downbeat: bool | None = None) -> BeatPoint:
    return BeatPoint(
        source_time=time,
        measure=measure,
        beat=beat,
        is_downbeat=is_downbeat if is_downbeat is not None else beat == 1,
    )


# Constant 120bpm grid starting at t=0 - lets these tests be compared
# directly against the equivalent quantize_events(..., bpm=120.0) cases.
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
