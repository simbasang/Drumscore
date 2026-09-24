import json

from app.persistence.models import ArtifactKind, NewArtifact
from app.persistence.serialization import (
    artifact_from_dict,
    artifact_to_dict,
    beat_from_dict,
    beat_to_dict,
    event_from_dict,
    event_to_dict,
    events_from_json_bytes,
    events_to_json_bytes,
    tempo_map_from_dict,
    tempo_map_to_dict,
)
from app.timing import BeatPoint, TempoMap, TempoPoint
from app.transcription import DrumEvent, DrumInstrument

AWKWARD_TIME = 0.1 + 0.2


def test_event_round_trips_every_field_through_json():
    event = DrumEvent(
        id="e1",
        time=AWKWARD_TIME,
        instrument=DrumInstrument.HIHAT_OPEN,
        velocity=0.8,
        confidence=0.5,
        provenance="drumscript",
        measure=3,
        beat=2,
        subdivision=1,
    )

    restored = event_from_dict(json.loads(json.dumps(event_to_dict(event))))

    assert restored == event
    assert restored.time == AWKWARD_TIME


def test_event_round_trips_optional_fields_as_none():
    event = DrumEvent(id="e2", time=1.5, instrument=DrumInstrument.KICK)

    restored = event_from_dict(json.loads(json.dumps(event_to_dict(event))))

    assert restored == event


def test_event_dict_stores_instrument_as_plain_string():
    event = DrumEvent(id="e3", time=2.0, instrument=DrumInstrument.SNARE)

    assert event_to_dict(event)["instrument"] == "snare"


def test_beat_round_trips_through_json():
    beat = BeatPoint(source_time=AWKWARD_TIME, measure=2, beat=4, is_downbeat=False, confidence=0.9)

    restored = beat_from_dict(json.loads(json.dumps(beat_to_dict(beat))))

    assert restored == beat


def test_tempo_map_round_trips_through_json():
    tempo_map = TempoMap(points=(TempoPoint(source_time=0.0, bpm=120.0), TempoPoint(source_time=30.5, bpm=128.25)))

    restored = tempo_map_from_dict(json.loads(json.dumps(tempo_map_to_dict(tempo_map))))

    assert restored == tempo_map


def test_events_json_bytes_round_trip_preserves_source_times():
    events = [
        DrumEvent(id="e1", time=AWKWARD_TIME, instrument=DrumInstrument.KICK),
        DrumEvent(id="e2", time=123.456789012345, instrument=DrumInstrument.RIDE, provenance="drumscript"),
    ]

    restored = events_from_json_bytes(events_to_json_bytes(events))

    assert restored == events


def test_artifact_descriptor_round_trips_through_json():
    artifact = NewArtifact(kind=ArtifactKind.DRUMS_STEM, storage_key="projects/p/j/drums.wav", size_bytes=10, sha256="ab")

    restored = artifact_from_dict(json.loads(json.dumps(artifact_to_dict(artifact))))

    assert restored == artifact
