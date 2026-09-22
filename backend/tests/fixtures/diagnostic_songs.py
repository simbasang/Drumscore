import dataclasses
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
import soundfile as sf

from app.transcription import DrumInstrument

SAMPLE_RATE = 22050

_DECAY_TIME_CONSTANTS: dict[DrumInstrument, float] = {
    DrumInstrument.KICK: 0.15,
    DrumInstrument.SNARE: 0.15,
    DrumInstrument.HIHAT_CLOSED: 0.03,
    DrumInstrument.HIHAT_OPEN: 0.25,
    DrumInstrument.CRASH: 1.0,
    DrumInstrument.RIDE: 0.4,
    DrumInstrument.TOM_LOW: 0.2,
    DrumInstrument.TOM_MID: 0.2,
    DrumInstrument.TOM_HIGH: 0.2,
}

_TONAL_FREQUENCIES_HZ: dict[DrumInstrument, float] = {
    DrumInstrument.KICK: 60.0,
    DrumInstrument.TOM_LOW: 120.0,
    DrumInstrument.TOM_MID: 180.0,
    DrumInstrument.TOM_HIGH: 240.0,
}

_NOISE_INSTRUMENTS = {
    DrumInstrument.SNARE,
    DrumInstrument.HIHAT_CLOSED,
    DrumInstrument.HIHAT_OPEN,
    DrumInstrument.CRASH,
    DrumInstrument.RIDE,
}


@dataclasses.dataclass(frozen=True)
class ExpectedHit:
    time: float
    instrument: DrumInstrument


def _synthesize_hit(
    instrument: DrumInstrument, sample_rate: int, rng: np.random.Generator
) -> np.ndarray:
    decay = _DECAY_TIME_CONSTANTS[instrument]
    length = int(round(decay * 4 * sample_rate))
    t = np.arange(length) / sample_rate
    envelope = np.exp(-t / decay)

    if instrument in _NOISE_INSTRUMENTS:
        waveform = rng.standard_normal(length)
    else:
        frequency = _TONAL_FREQUENCIES_HZ[instrument]
        waveform = np.sin(2 * np.pi * frequency * t)

    return waveform * envelope


def render_events(
    hits: Sequence[ExpectedHit],
    duration_seconds: float,
    sample_rate: int = SAMPLE_RATE,
    noise_seed: int = 20260920,
) -> np.ndarray:
    rng = np.random.default_rng(noise_seed)
    total_samples = int(round(duration_seconds * sample_rate))
    audio = np.zeros(total_samples, dtype=np.float64)

    for hit in hits:
        waveform = _synthesize_hit(hit.instrument, sample_rate, rng)
        start = int(round(hit.time * sample_rate))
        if start >= total_samples:
            continue
        end = min(start + len(waveform), total_samples)
        audio[start:end] += waveform[: end - start]

    peak = np.max(np.abs(audio)) if audio.size else 0.0
    if peak > 1.0:
        audio = audio / peak

    return audio.astype(np.float32)


@dataclasses.dataclass(frozen=True)
class DiagnosticSong:
    key: str
    description: str
    tempo_bpm: float
    downbeat_offset_seconds: float
    duration_seconds: float
    expected_hits: tuple[ExpectedHit, ...]
    sample_rate: int = SAMPLE_RATE

    def generate_audio(self) -> np.ndarray:
        return render_events(self.expected_hits, self.duration_seconds, self.sample_rate)

    def write_wav(self, path: Path) -> Path:
        sf.write(str(path), self.generate_audio(), self.sample_rate)
        return path


def steady_rock_beat(
    start_time: float, tempo_bpm: float, num_measures: int
) -> list[ExpectedHit]:
    seconds_per_beat = 60.0 / tempo_bpm
    seconds_per_eighth = seconds_per_beat / 2

    hits: list[ExpectedHit] = []
    for measure in range(num_measures):
        measure_start = start_time + measure * 4 * seconds_per_beat
        for eighth in range(8):
            hits.append(
                ExpectedHit(
                    time=measure_start + eighth * seconds_per_eighth,
                    instrument=DrumInstrument.HIHAT_CLOSED,
                )
            )
        hits.append(ExpectedHit(time=measure_start, instrument=DrumInstrument.KICK))
        hits.append(
            ExpectedHit(time=measure_start + 2 * seconds_per_beat, instrument=DrumInstrument.KICK)
        )
        hits.append(
            ExpectedHit(time=measure_start + seconds_per_beat, instrument=DrumInstrument.SNARE)
        )
        hits.append(
            ExpectedHit(
                time=measure_start + 3 * seconds_per_beat, instrument=DrumInstrument.SNARE
            )
        )
    return hits


def _build_steady_4_4() -> DiagnosticSong:
    tempo_bpm = 120.0
    num_measures = 4
    seconds_per_beat = 60.0 / tempo_bpm
    hits = steady_rock_beat(start_time=0.0, tempo_bpm=tempo_bpm, num_measures=num_measures)

    return DiagnosticSong(
        key="steady_4_4",
        description=(
            "Constant 120 BPM rock beat with the first downbeat at t=0; the "
            "timing baseline every other fixture is compared against."
        ),
        tempo_bpm=tempo_bpm,
        downbeat_offset_seconds=0.0,
        duration_seconds=num_measures * 4 * seconds_per_beat + 1.0,
        expected_hits=tuple(sorted(hits, key=lambda h: h.time)),
    )


def _build_intro_count_in() -> DiagnosticSong:
    tempo_bpm = 120.0
    num_measures = 4
    seconds_per_beat = 60.0 / tempo_bpm
    lead_in_silence = 0.5

    count_in_hits = [
        ExpectedHit(
            time=lead_in_silence + beat * seconds_per_beat, instrument=DrumInstrument.HIHAT_CLOSED
        )
        for beat in range(4)
    ]
    downbeat_offset = lead_in_silence + 4 * seconds_per_beat
    groove_hits = steady_rock_beat(
        start_time=downbeat_offset, tempo_bpm=tempo_bpm, num_measures=num_measures
    )
    hits = count_in_hits + groove_hits

    return DiagnosticSong(
        key="intro_count_in",
        description=(
            "0.5s of silence plus a 1-measure hi-hat count-in before the first "
            "real downbeat, so measure 1 / beat 1 does NOT sit at t=0 - targets "
            "the fixed-grid phase-alignment gap in quantize_events (see "
            "TECHNICAL_DEBT.md, 'Quantization grid isn't phase-aligned to the beat')."
        ),
        tempo_bpm=tempo_bpm,
        downbeat_offset_seconds=downbeat_offset,
        duration_seconds=downbeat_offset + num_measures * 4 * seconds_per_beat + 1.0,
        expected_hits=tuple(sorted(hits, key=lambda h: h.time)),
    )


def _build_dense_fill() -> DiagnosticSong:
    tempo_bpm = 120.0
    seconds_per_beat = 60.0 / tempo_bpm
    groove_measures = 2
    groove_hits = steady_rock_beat(
        start_time=0.0, tempo_bpm=tempo_bpm, num_measures=groove_measures
    )

    fill_start = groove_measures * 4 * seconds_per_beat
    seconds_per_sixteenth = seconds_per_beat / 4
    fill_instruments = [
        DrumInstrument.SNARE,
        DrumInstrument.SNARE,
        DrumInstrument.TOM_HIGH,
        DrumInstrument.TOM_HIGH,
        DrumInstrument.TOM_MID,
        DrumInstrument.TOM_MID,
        DrumInstrument.TOM_LOW,
        DrumInstrument.TOM_LOW,
        DrumInstrument.SNARE,
        DrumInstrument.SNARE,
        DrumInstrument.TOM_HIGH,
        DrumInstrument.TOM_HIGH,
        DrumInstrument.TOM_MID,
        DrumInstrument.TOM_MID,
        DrumInstrument.TOM_LOW,
        DrumInstrument.TOM_LOW,
    ]
    fill_hits = [
        ExpectedHit(time=fill_start + i * seconds_per_sixteenth, instrument=instrument)
        for i, instrument in enumerate(fill_instruments)
    ]

    resolution_time = fill_start + 4 * seconds_per_beat
    resolution_hits = [
        ExpectedHit(time=resolution_time, instrument=DrumInstrument.CRASH),
        ExpectedHit(time=resolution_time, instrument=DrumInstrument.KICK),
    ]

    hits = groove_hits + fill_hits + resolution_hits

    return DiagnosticSong(
        key="dense_fill",
        description=(
            "Two measures of steady groove followed by a full measure of "
            "straight 16th-note snare/tom fill and a crash+kick downbeat "
            "resolution - exercises dense same-slot event rates and "
            "simultaneous hit grouping."
        ),
        tempo_bpm=tempo_bpm,
        downbeat_offset_seconds=0.0,
        duration_seconds=resolution_time + 1.5,
        expected_hits=tuple(sorted(hits, key=lambda h: h.time)),
    )


def _build_timing_variation() -> DiagnosticSong:
    tempo_bpm = 120.0
    num_measures = 4
    seconds_per_beat = 60.0 / tempo_bpm
    base_hits = steady_rock_beat(start_time=0.0, tempo_bpm=tempo_bpm, num_measures=num_measures)

    rng = np.random.default_rng(4200)
    max_jitter_seconds = 0.02
    jittered_hits = [
        ExpectedHit(
            time=max(0.0, hit.time + rng.uniform(-max_jitter_seconds, max_jitter_seconds)),
            instrument=hit.instrument,
        )
        for hit in base_hits
    ]

    return DiagnosticSong(
        key="timing_variation",
        description=(
            "Same groove/tempo as steady_4_4, but every hit carries a "
            "deterministic +/-20ms timing offset (seeded RNG) simulating a "
            "live, non-quantized performance instead of a perfectly "
            "metronomic grid."
        ),
        tempo_bpm=tempo_bpm,
        downbeat_offset_seconds=0.0,
        duration_seconds=num_measures * 4 * seconds_per_beat + 1.0,
        expected_hits=tuple(sorted(jittered_hits, key=lambda h: h.time)),
    )


_BUILDERS: dict[str, Callable[[], DiagnosticSong]] = {
    "steady_4_4": _build_steady_4_4,
    "intro_count_in": _build_intro_count_in,
    "dense_fill": _build_dense_fill,
    "timing_variation": _build_timing_variation,
}


def list_diagnostic_songs() -> list[DiagnosticSong]:
    return [builder() for builder in _BUILDERS.values()]


def get_diagnostic_song(key: str) -> DiagnosticSong:
    try:
        return _BUILDERS[key]()
    except KeyError as error:
        raise KeyError(
            f"Unknown diagnostic song fixture: {key!r}. Known keys: {sorted(_BUILDERS)}"
        ) from error
