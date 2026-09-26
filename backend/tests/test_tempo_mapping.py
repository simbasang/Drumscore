from pathlib import Path

import pytest

from app.pipeline.errors import InsufficientBeatsError
from app.pipeline.tempo_mapping import map_tempo
from app.beat_detection import BeatDetectionError
from app.timing import TempoMap
from app.transcription import DrumEvent, DrumInstrument
from tests.fakes import FOUR_BEATS, OFFSET_BEATS, FakeBeatDetector

DRUMS = Path("drums.wav")
ACCOMPANIMENT = Path("accompaniment.wav")


def test_map_tempo_derives_tempo_bpm_from_the_detected_beats():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    result = map_tempo(DRUMS, ACCOMPANIMENT, events, FakeBeatDetector(FOUR_BEATS))

    assert result.tempo_bpm == pytest.approx(120.0)
    assert result.tempo_map == TempoMap.constant(result.tempo_bpm)
    assert result.beats == FOUR_BEATS


def test_map_tempo_gives_both_stems_to_the_beat_detector():
    detector = FakeBeatDetector()

    map_tempo(DRUMS, ACCOMPANIMENT, [], detector)

    assert detector.calls == [(DRUMS, ACCOMPANIMENT)]


def test_map_tempo_quantizes_against_real_beat_anchors():
    events = [DrumEvent(id="e1", time=2.5, instrument=DrumInstrument.KICK)]

    result = map_tempo(DRUMS, ACCOMPANIMENT, events, FakeBeatDetector(OFFSET_BEATS))

    assert (result.events[0].measure, result.events[0].beat, result.events[0].subdivision) == (1, 1, 0)
    assert result.events[0].time == 2.5


def test_map_tempo_shifts_measures_so_pre_first_beat_events_are_kept():
    events = [
        DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK),
        DrumEvent(id="e2", time=3.0, instrument=DrumInstrument.SNARE),
    ]

    result = map_tempo(DRUMS, ACCOMPANIMENT, events, FakeBeatDetector(OFFSET_BEATS))

    e1, e2 = result.events
    assert (e1.measure, e1.beat, e1.subdivision) == (1, 1, 0)
    assert (e2.measure, e2.beat, e2.subdivision) == (2, 2, 0)


def test_map_tempo_does_not_shift_when_measures_already_start_at_one():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    result = map_tempo(DRUMS, ACCOMPANIMENT, events, FakeBeatDetector(FOUR_BEATS))

    assert (result.events[0].measure, result.events[0].beat) == (1, 2)


def test_map_tempo_leaves_input_events_untouched():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    map_tempo(DRUMS, ACCOMPANIMENT, events, FakeBeatDetector(FOUR_BEATS))

    assert events[0].beat is None


def test_map_tempo_requires_two_beats():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    with pytest.raises(InsufficientBeatsError, match="found only 1 beat"):
        map_tempo(DRUMS, ACCOMPANIMENT, events, FakeBeatDetector(FOUR_BEATS[:1]))


def test_map_tempo_propagates_engine_errors():
    with pytest.raises(BeatDetectionError):
        map_tempo(DRUMS, ACCOMPANIMENT, [], FakeBeatDetector(error=BeatDetectionError("no beats")))


def test_map_tempo_handles_no_events():
    result = map_tempo(DRUMS, ACCOMPANIMENT, [], FakeBeatDetector())

    assert result.events == []
