import pytest

from app.beat_mapping import quantize_events
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
