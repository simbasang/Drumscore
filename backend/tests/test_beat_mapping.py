import pytest

from app.beat_mapping import musical_position_to_seconds, quantize_events
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
