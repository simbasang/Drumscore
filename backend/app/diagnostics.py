import dataclasses

from app.beat_mapping import (
    DEFAULT_BEATS_PER_MEASURE,
    DEFAULT_SUBDIVISIONS_PER_BEAT,
    beat_anchored_position_to_seconds,
)
from app.timing import BeatPoint
from app.transcription import DrumEvent, DrumInstrument


@dataclasses.dataclass(frozen=True)
class EventDiagnostic:
    event_id: str
    instrument: DrumInstrument
    source_time: float
    velocity: float | None
    confidence: float | None
    provenance: str | None
    tempo_bpm: float
    measure: int | None
    beat: int | None
    subdivision: int | None
    quantized_time: float | None
    quantization_error_seconds: float | None


def build_event_diagnostics(
    raw_events: list[DrumEvent],
    quantized_events: list[DrumEvent],
    tempo_bpm: float,
    beats: list[BeatPoint],
    beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE,
    subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT,
) -> list[EventDiagnostic]:
    """Pairs each raw transcriber event with its quantized counterpart (by
    shared id) and reports how far quantization moved it from its original
    source timestamp, reconstructed via the same real beat anchors
    quantization used. Read-only: never mutates its inputs or the
    pipeline's stored events."""
    quantized_by_id = {event.id: event for event in quantized_events}
    diagnostics: list[EventDiagnostic] = []

    for raw_event in raw_events:
        quantized = quantized_by_id.get(raw_event.id)
        measure = beat = subdivision = None
        quantized_time = None
        quantization_error_seconds = None

        if quantized is not None and quantized.measure is not None:
            measure = quantized.measure
            beat = quantized.beat
            subdivision = quantized.subdivision
            quantized_time = beat_anchored_position_to_seconds(
                beats, measure, beat, subdivision, beats_per_measure, subdivisions_per_beat
            )
            quantization_error_seconds = quantized_time - raw_event.time

        diagnostics.append(
            EventDiagnostic(
                event_id=raw_event.id,
                instrument=raw_event.instrument,
                source_time=raw_event.time,
                velocity=raw_event.velocity,
                confidence=raw_event.confidence,
                provenance=raw_event.provenance,
                tempo_bpm=tempo_bpm,
                measure=measure,
                beat=beat,
                subdivision=subdivision,
                quantized_time=quantized_time,
                quantization_error_seconds=quantization_error_seconds,
            )
        )

    return diagnostics
