import json
from typing import Any

from app.persistence.models import ArtifactKind, NewArtifact
from app.timing import BeatPoint, TempoMap, TempoPoint
from app.transcription import DrumEvent, DrumInstrument

# Floats are written with json's shortest round-trip repr, so every
# sourceTime reads back bit-identical (see test_persistence_serialization).


def event_to_dict(event: DrumEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "time": event.time,
        "instrument": event.instrument.value,
        "velocity": event.velocity,
        "confidence": event.confidence,
        "provenance": event.provenance,
        "measure": event.measure,
        "beat": event.beat,
        "subdivision": event.subdivision,
    }


def event_from_dict(data: dict[str, Any]) -> DrumEvent:
    return DrumEvent(
        id=data["id"],
        time=data["time"],
        instrument=DrumInstrument(data["instrument"]),
        velocity=data.get("velocity"),
        confidence=data.get("confidence"),
        provenance=data.get("provenance"),
        measure=data.get("measure"),
        beat=data.get("beat"),
        subdivision=data.get("subdivision"),
    )


def beat_to_dict(beat: BeatPoint) -> dict[str, Any]:
    return {
        "source_time": beat.source_time,
        "measure": beat.measure,
        "beat": beat.beat,
        "is_downbeat": beat.is_downbeat,
        "confidence": beat.confidence,
    }


def beat_from_dict(data: dict[str, Any]) -> BeatPoint:
    return BeatPoint(
        source_time=data["source_time"],
        measure=data["measure"],
        beat=data["beat"],
        is_downbeat=data["is_downbeat"],
        confidence=data.get("confidence"),
    )


def tempo_map_to_dict(tempo_map: TempoMap) -> dict[str, Any]:
    return {"points": [{"source_time": p.source_time, "bpm": p.bpm} for p in tempo_map.points]}


def tempo_map_from_dict(data: dict[str, Any]) -> TempoMap:
    return TempoMap(points=tuple(TempoPoint(source_time=p["source_time"], bpm=p["bpm"]) for p in data["points"]))


def events_to_json_bytes(events: list[DrumEvent]) -> bytes:
    return json.dumps([event_to_dict(event) for event in events]).encode("utf-8")


def events_from_json_bytes(data: bytes) -> list[DrumEvent]:
    return [event_from_dict(item) for item in json.loads(data.decode("utf-8"))]


def artifact_to_dict(artifact: NewArtifact) -> dict[str, Any]:
    return {
        "kind": artifact.kind.value,
        "storage_key": artifact.storage_key,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
    }


def artifact_from_dict(data: dict[str, Any]) -> NewArtifact:
    return NewArtifact(
        kind=ArtifactKind(data["kind"]),
        storage_key=data["storage_key"],
        size_bytes=data["size_bytes"],
        sha256=data["sha256"],
    )
