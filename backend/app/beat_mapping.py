import dataclasses

from app.transcription import DrumEvent

DEFAULT_BEATS_PER_MEASURE = 4
DEFAULT_SUBDIVISIONS_PER_BEAT = 4


def quantize_events(
    events: list[DrumEvent],
    bpm: float,
    beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE,
    subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT,
) -> list[DrumEvent]:
    seconds_per_beat = 60.0 / bpm
    seconds_per_subdivision = seconds_per_beat / subdivisions_per_beat

    quantized: list[DrumEvent] = []
    for event in events:
        total_subdivisions = round(event.time / seconds_per_subdivision)
        beat_index = total_subdivisions // subdivisions_per_beat
        subdivision = total_subdivisions % subdivisions_per_beat
        measure = beat_index // beats_per_measure + 1
        beat_in_measure = beat_index % beats_per_measure + 1

        quantized.append(
            dataclasses.replace(
                event,
                measure=measure,
                beat=beat_in_measure,
                subdivision=subdivision,
            )
        )

    return quantized


def musical_position_to_seconds(
    measure: int,
    beat: int,
    subdivision: int,
    bpm: float,
    beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE,
    subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT,
) -> float:
    """The exact inverse of quantize_events's grid math: turns a musical
    position back into a source-audio second, so it can be compared against
    the original event.time for diagnostics."""
    seconds_per_beat = 60.0 / bpm
    seconds_per_subdivision = seconds_per_beat / subdivisions_per_beat

    beat_index = (measure - 1) * beats_per_measure + (beat - 1)
    total_subdivisions = beat_index * subdivisions_per_beat + subdivision

    return total_subdivisions * seconds_per_subdivision
