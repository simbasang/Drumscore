import dataclasses
from dataclasses import dataclass
from pathlib import Path

from app.beat_detection import BeatDetector
from app.beat_mapping import quantize_events_with_beats
from app.beat_this_beat_detector import tempo_from_beats
from app.pipeline.errors import InsufficientBeatsError
from app.timing import BeatPoint, TempoMap
from app.transcription import DrumEvent


@dataclass(frozen=True)
class TempoMappingResult:
    tempo_bpm: float
    tempo_map: TempoMap
    beats: list[BeatPoint]
    events: list[DrumEvent]


def map_tempo(
    drums_path: Path,
    accompaniment_path: Path,
    events: list[DrumEvent],
    beat_detector: BeatDetector,
) -> TempoMappingResult:
    """Detects beats and assigns each event a musical position anchored to
    them. The reported tempo is derived from those same beats, so the
    pipeline has a single tempo source. Source timestamps are never
    changed."""
    beats = beat_detector.detect(drums_path, accompaniment_path)

    if len(beats) < 2:
        raise InsufficientBeatsError(
            f"Beat detection found only {len(beats)} beat(s); tempo mapping requires at least 2"
        )

    quantized_events = quantize_events_with_beats(events, beats)

    # quantize_events_with_beats legitimately produces measure <= 0 for events
    # before the first detected beat point (extrapolated via plain integer
    # arithmetic - documented, unit-tested behavior). The frontend's
    # buildMeasures is 1-based and silently drops any such event, so floor the
    # numbering at 1 with a uniform shift, which preserves relative spacing.
    if quantized_events:
        min_measure = min(event.measure for event in quantized_events)
        if min_measure < 1:
            shift = 1 - min_measure
            quantized_events = [
                dataclasses.replace(event, measure=event.measure + shift) for event in quantized_events
            ]

    bpm = tempo_from_beats(beats)
    return TempoMappingResult(tempo_bpm=bpm, tempo_map=TempoMap.constant(bpm), beats=beats, events=quantized_events)
