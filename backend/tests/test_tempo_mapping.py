from pathlib import Path

import pytest

from app.pipeline.errors import InsufficientBeatsError
from app.pipeline.tempo_mapping import map_tempo
from app.tempo_estimation import TempoEstimationError
from app.timing import TempoMap
from app.transcription import DrumEvent, DrumInstrument
from tests.fakes import FOUR_BEATS, OFFSET_BEATS, FakeBeatDetector, FakeTempoEstimator

DRUMS = Path("drums.wav")


def test_map_tempo_returns_bpm_constant_tempo_map_and_beats():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    result = map_tempo(DRUMS, events, FakeTempoEstimator(128.0), FakeBeatDetector(FOUR_BEATS))

    assert result.tempo_bpm == 128.0
    assert result.tempo_map == TempoMap.constant(128.0)
    assert result.beats == FOUR_BEATS


def test_map_tempo_quantizes_against_real_beat_anchors():
    events = [DrumEvent(id="e1", time=2.5, instrument=DrumInstrument.KICK)]

    result = map_tempo(DRUMS, events, FakeTempoEstimator(), FakeBeatDetector(OFFSET_BEATS))

    assert (result.events[0].measure, result.events[0].beat, result.events[0].subdivision) == (1, 1, 0)
    assert result.events[0].time == 2.5


def test_map_tempo_shifts_measures_so_pre_first_beat_events_are_kept():
    events = [
        DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK),
        DrumEvent(id="e2", time=3.0, instrument=DrumInstrument.SNARE),
    ]

    result = map_tempo(DRUMS, events, FakeTempoEstimator(), FakeBeatDetector(OFFSET_BEATS))

    e1, e2 = result.events
    assert (e1.measure, e1.beat, e1.subdivision) == (1, 1, 0)
    assert (e2.measure, e2.beat, e2.subdivision) == (2, 2, 0)


def test_map_tempo_does_not_shift_when_measures_already_start_at_one():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    result = map_tempo(DRUMS, events, FakeTempoEstimator(), FakeBeatDetector(FOUR_BEATS))

    assert (result.events[0].measure, result.events[0].beat) == (1, 2)


def test_map_tempo_leaves_input_events_untouched():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    map_tempo(DRUMS, events, FakeTempoEstimator(), FakeBeatDetector(FOUR_BEATS))

    assert events[0].beat is None


def test_map_tempo_requires_two_beats():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    with pytest.raises(InsufficientBeatsError, match="found only 1 beat"):
        map_tempo(DRUMS, events, FakeTempoEstimator(), FakeBeatDetector(FOUR_BEATS[:1]))


def test_map_tempo_propagates_engine_errors():
    with pytest.raises(TempoEstimationError):
        map_tempo(DRUMS, [], FakeTempoEstimator(error=TempoEstimationError("no tempo")), FakeBeatDetector())


def test_map_tempo_handles_no_events():
    result = map_tempo(DRUMS, [], FakeTempoEstimator(), FakeBeatDetector())

    assert result.events == []
