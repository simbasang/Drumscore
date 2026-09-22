from typing import Callable

from app.transcription import DrumInstrument
from tests.fixtures.diagnostic_songs import DiagnosticSong, ExpectedHit, steady_rock_beat


def _build_straight_rock() -> DiagnosticSong:
    tempo_bpm = 120.0
    num_measures = 4
    seconds_per_beat = 60.0 / tempo_bpm
    hits = steady_rock_beat(start_time=0.0, tempo_bpm=tempo_bpm, num_measures=num_measures)

    return DiagnosticSong(
        key="straight_rock",
        description=(
            "Steady quarter-note kick/snare backbeat with closed hi-hat "
            "eighths - the benchmark's baseline groove."
        ),
        tempo_bpm=tempo_bpm,
        downbeat_offset_seconds=0.0,
        duration_seconds=num_measures * 4 * seconds_per_beat + 1.0,
        expected_hits=tuple(sorted(hits, key=lambda h: h.time)),
    )


def _build_syncopated_funk() -> DiagnosticSong:
    tempo_bpm = 100.0
    num_measures = 4
    seconds_per_beat = 60.0 / tempo_bpm
    seconds_per_eighth = seconds_per_beat / 2

    hits: list[ExpectedHit] = []
    for measure in range(num_measures):
        measure_start = measure * 4 * seconds_per_beat
        for eighth in range(8):
            time = measure_start + eighth * seconds_per_eighth
            if eighth == 7:
                hits.append(ExpectedHit(time=time, instrument=DrumInstrument.HIHAT_OPEN))
            else:
                hits.append(ExpectedHit(time=time, instrument=DrumInstrument.HIHAT_CLOSED))
        # Kick on beat 1 (eighth 0), the "and" of beat 2 (eighth 3), and
        # the "and" of beat 3 (eighth 5) - classic syncopated funk kick.
        for eighth in (0, 3, 5):
            hits.append(
                ExpectedHit(
                    time=measure_start + eighth * seconds_per_eighth,
                    instrument=DrumInstrument.KICK,
                )
            )
        # Backbeat snare on beats 2 and 4 (eighths 2 and 6).
        for eighth in (2, 6):
            hits.append(
                ExpectedHit(
                    time=measure_start + eighth * seconds_per_eighth,
                    instrument=DrumInstrument.SNARE,
                )
            )

    return DiagnosticSong(
        key="syncopated_funk",
        description=(
            "Syncopated funk kick pattern (1, &2, &3) against a backbeat "
            "snare, with an open hi-hat accent on the '&' of beat 4 each "
            "measure instead of closed."
        ),
        tempo_bpm=tempo_bpm,
        downbeat_offset_seconds=0.0,
        duration_seconds=num_measures * 4 * seconds_per_beat + 1.0,
        expected_hits=tuple(sorted(hits, key=lambda h: h.time)),
    )


def _build_double_kick() -> DiagnosticSong:
    tempo_bpm = 160.0
    num_measures = 3
    seconds_per_beat = 60.0 / tempo_bpm
    seconds_per_eighth = seconds_per_beat / 2

    hits: list[ExpectedHit] = []
    for measure in range(num_measures):
        measure_start = measure * 4 * seconds_per_beat
        # Kick on every eighth note - the "double kick" pulse.
        for eighth in range(8):
            hits.append(
                ExpectedHit(
                    time=measure_start + eighth * seconds_per_eighth,
                    instrument=DrumInstrument.KICK,
                )
            )
        # Closed hi-hat on quarter notes only, for structure.
        for beat in range(4):
            hits.append(
                ExpectedHit(
                    time=measure_start + beat * seconds_per_beat,
                    instrument=DrumInstrument.HIHAT_CLOSED,
                )
            )
        # Backbeat snare on beats 2 and 4.
        for beat in (1, 3):
            hits.append(
                ExpectedHit(
                    time=measure_start + beat * seconds_per_beat,
                    instrument=DrumInstrument.SNARE,
                )
            )

    return DiagnosticSong(
        key="double_kick",
        description=(
            "Fast (160 BPM) relentless eighth-note kick pattern against a "
            "quarter-note hi-hat and backbeat snare - exercises dense "
            "same-instrument event rates at speed."
        ),
        tempo_bpm=tempo_bpm,
        downbeat_offset_seconds=0.0,
        duration_seconds=num_measures * 4 * seconds_per_beat + 1.0,
        expected_hits=tuple(sorted(hits, key=lambda h: h.time)),
    )


def _build_tom_fill_crash() -> DiagnosticSong:
    tempo_bpm = 130.0
    seconds_per_beat = 60.0 / tempo_bpm
    seconds_per_sixteenth = seconds_per_beat / 4

    # Measure 1: sparse kick pulse (beats 1 and 3) to establish tempo,
    # deliberately with no snare/hi-hat so this song isolates tom/crash
    # classification.
    hits: list[ExpectedHit] = [
        ExpectedHit(time=0.0, instrument=DrumInstrument.KICK),
        ExpectedHit(time=2 * seconds_per_beat, instrument=DrumInstrument.KICK),
    ]

    # Measure 2: an 8-sixteenth descending tom fill.
    fill_start = 4 * seconds_per_beat
    fill_instruments = [
        DrumInstrument.TOM_HIGH,
        DrumInstrument.TOM_HIGH,
        DrumInstrument.TOM_MID,
        DrumInstrument.TOM_MID,
        DrumInstrument.TOM_LOW,
        DrumInstrument.TOM_LOW,
        DrumInstrument.TOM_HIGH,
        DrumInstrument.TOM_MID,
    ]
    for i, instrument in enumerate(fill_instruments):
        hits.append(ExpectedHit(time=fill_start + i * seconds_per_sixteenth, instrument=instrument))

    # Measure 3 downbeat: crash + kick resolution.
    resolution_time = fill_start + 4 * seconds_per_beat
    hits.append(ExpectedHit(time=resolution_time, instrument=DrumInstrument.CRASH))
    hits.append(ExpectedHit(time=resolution_time, instrument=DrumInstrument.KICK))

    return DiagnosticSong(
        key="tom_fill_crash",
        description=(
            "A sparse kick pulse, then an 8-sixteenth descending tom fill "
            "resolving on a simultaneous crash+kick downbeat - isolates "
            "tom/crash classification without snare or hi-hat noise."
        ),
        tempo_bpm=tempo_bpm,
        downbeat_offset_seconds=0.0,
        duration_seconds=resolution_time + 1.5,
        expected_hits=tuple(sorted(hits, key=lambda h: h.time)),
    )


def _build_ride_groove() -> DiagnosticSong:
    tempo_bpm = 110.0
    num_measures = 4
    seconds_per_beat = 60.0 / tempo_bpm
    seconds_per_eighth = seconds_per_beat / 2

    hits: list[ExpectedHit] = []
    for measure in range(num_measures):
        measure_start = measure * 4 * seconds_per_beat
        for eighth in range(8):
            hits.append(
                ExpectedHit(
                    time=measure_start + eighth * seconds_per_eighth,
                    instrument=DrumInstrument.RIDE,
                )
            )
        for beat in (0, 2):
            hits.append(
                ExpectedHit(
                    time=measure_start + beat * seconds_per_beat, instrument=DrumInstrument.KICK
                )
            )
        for beat in (1, 3):
            hits.append(
                ExpectedHit(
                    time=measure_start + beat * seconds_per_beat, instrument=DrumInstrument.SNARE
                )
            )

    return DiagnosticSong(
        key="ride_groove",
        description=(
            "Ride-cymbal-driven groove (eighth-note ride instead of "
            "hi-hat) with kick on 1/3 and backbeat snare - a jazz/rock "
            "crossover feel exercising ride classification."
        ),
        tempo_bpm=tempo_bpm,
        downbeat_offset_seconds=0.0,
        duration_seconds=num_measures * 4 * seconds_per_beat + 1.0,
        expected_hits=tuple(sorted(hits, key=lambda h: h.time)),
    )


def _build_full_kit_mixed() -> DiagnosticSong:
    tempo_bpm = 115.0
    seconds_per_beat = 60.0 / tempo_bpm
    seconds_per_eighth = seconds_per_beat / 2
    seconds_per_sixteenth = seconds_per_beat / 4

    hits: list[ExpectedHit] = []

    # Measures 1-2: straight groove (kick/snare/closed hi-hat), with a
    # crash layered on the very first downbeat and one open hi-hat accent
    # in measure 2.
    for measure in range(2):
        measure_start = measure * 4 * seconds_per_beat
        for eighth in range(8):
            is_accent = measure == 1 and eighth == 7
            instrument = DrumInstrument.HIHAT_OPEN if is_accent else DrumInstrument.HIHAT_CLOSED
            hits.append(
                ExpectedHit(time=measure_start + eighth * seconds_per_eighth, instrument=instrument)
            )
        hits.append(ExpectedHit(time=measure_start, instrument=DrumInstrument.KICK))
        hits.append(
            ExpectedHit(time=measure_start + 2 * seconds_per_beat, instrument=DrumInstrument.KICK)
        )
        hits.append(
            ExpectedHit(time=measure_start + seconds_per_beat, instrument=DrumInstrument.SNARE)
        )
        hits.append(
            ExpectedHit(time=measure_start + 3 * seconds_per_beat, instrument=DrumInstrument.SNARE)
        )
    hits.append(ExpectedHit(time=0.0, instrument=DrumInstrument.CRASH))

    # Measure 3: switch to a ride-driven "chorus" feel.
    chorus_start = 2 * 4 * seconds_per_beat
    for eighth in range(8):
        hits.append(
            ExpectedHit(time=chorus_start + eighth * seconds_per_eighth, instrument=DrumInstrument.RIDE)
        )
    hits.append(ExpectedHit(time=chorus_start, instrument=DrumInstrument.KICK))
    hits.append(
        ExpectedHit(time=chorus_start + 2 * seconds_per_beat, instrument=DrumInstrument.KICK)
    )
    hits.append(ExpectedHit(time=chorus_start + seconds_per_beat, instrument=DrumInstrument.SNARE))
    hits.append(
        ExpectedHit(time=chorus_start + 3 * seconds_per_beat, instrument=DrumInstrument.SNARE)
    )

    # Measure 4: a short 3-sixteenth descending tom fill, resolving on a
    # simultaneous crash+kick downbeat.
    fill_start = 3 * 4 * seconds_per_beat
    fill_instruments = [DrumInstrument.TOM_HIGH, DrumInstrument.TOM_MID, DrumInstrument.TOM_LOW]
    for i, instrument in enumerate(fill_instruments):
        hits.append(ExpectedHit(time=fill_start + i * seconds_per_sixteenth, instrument=instrument))
    resolution_time = fill_start + 4 * seconds_per_beat
    hits.append(ExpectedHit(time=resolution_time, instrument=DrumInstrument.CRASH))
    hits.append(ExpectedHit(time=resolution_time, instrument=DrumInstrument.KICK))

    return DiagnosticSong(
        key="full_kit_mixed",
        description=(
            "A full-kit groove combining every DrumInstrument at least "
            "once - verse (kick/snare/hi-hat + downbeat crash), a "
            "ride-driven chorus, and a tom fill resolving on crash+kick - "
            "a realistic whole-song integration fixture for corpus-level "
            "metrics."
        ),
        tempo_bpm=tempo_bpm,
        downbeat_offset_seconds=0.0,
        duration_seconds=resolution_time + 1.5,
        expected_hits=tuple(sorted(hits, key=lambda h: h.time)),
    )


_BUILDERS: dict[str, Callable[[], DiagnosticSong]] = {
    "straight_rock": _build_straight_rock,
    "syncopated_funk": _build_syncopated_funk,
    "double_kick": _build_double_kick,
    "tom_fill_crash": _build_tom_fill_crash,
    "ride_groove": _build_ride_groove,
    "full_kit_mixed": _build_full_kit_mixed,
}


def list_benchmark_songs() -> list[DiagnosticSong]:
    return [builder() for builder in _BUILDERS.values()]


def get_benchmark_song(key: str) -> DiagnosticSong:
    try:
        return _BUILDERS[key]()
    except KeyError as error:
        raise KeyError(
            f"Unknown benchmark song fixture: {key!r}. Known keys: {sorted(_BUILDERS)}"
        ) from error
