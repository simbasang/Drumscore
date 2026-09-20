# Diagnostic Song Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small, deterministic, synthetic drum-song fixture corpus (steady 4/4, intro silence/count-in, dense 16th-note fills, timing variation) with documented ground-truth metadata, so later EPIC 1 diagnostic/timing work has reproducible, copyright-safe inputs to test against.

**Architecture:** A pure-Python fixture module (`backend/tests/fixtures/diagnostic_songs.py`) synthesizes mono audio in-memory from a list of `(time, instrument)` ground-truth hits using simple deterministic waveforms per `DrumInstrument` (sine bursts for tonal drums, seeded noise bursts for cymbals/snare/hi-hat). Each fixture is exposed as a `DiagnosticSong` dataclass carrying its own ground truth (`tempo_bpm`, `downbeat_offset_seconds`, `expected_hits`) plus `generate_audio()`/`write_wav()` methods. Nothing binary is ever committed to the repo — every fixture is regenerated at test time from code, which is what keeps the corpus copyright-safe and small by construction.

**Tech Stack:** Python 3.13, numpy, soundfile, pytest (all already backend dev dependencies — see `backend/pyproject.toml`).

**Spec:** GitHub issue #34 (V1-001), part of EPIC 1 (#28). Related project docs: `PROJECT.md` §4/§17.1 ("audio timestamps are the source of truth"), `TECHNICAL_DEBT.md` ("Quantization grid isn't phase-aligned to the beat" — the entry `intro_count_in` is specifically built to exercise).

## Global Constraints

- No real/copyrighted audio may be committed — fixtures are pure synthesis, generated at test time, never written to the repo as binary files.
- Every fixture must preserve exact ground-truth hit times (no rounding to a notation grid) — mirrors the project's "source audio timeline is the source of truth" rule.
- Follow existing backend test conventions: flat `test_*.py` files under `backend/tests/`, pytest with AAA-shaped tests (arrange/act/assert), no test framework other than pytest.
- Keep changes scoped to this issue only — do not touch `beat_mapping.py`, `librosa_tempo_estimator.py`, or any pipeline code; this issue only adds fixtures.

---

### Task 1: Core fixture module — data model, synthesis, and the `steady_4_4` + `intro_count_in` fixtures

**Files:**
- Create: `backend/tests/fixtures/diagnostic_songs.py`
- Test: `backend/tests/test_diagnostic_songs.py`

**Interfaces:**
- Consumes: `app.transcription.DrumInstrument` (existing enum: `KICK`, `SNARE`, `HIHAT_CLOSED`, `HIHAT_OPEN`, `CRASH`, `RIDE`, `TOM_LOW`, `TOM_MID`, `TOM_HIGH`).
- Produces (used by Task 2 and by future issues):
  - `ExpectedHit(time: float, instrument: DrumInstrument)` frozen dataclass.
  - `DiagnosticSong` frozen dataclass with fields `key: str`, `description: str`, `tempo_bpm: float`, `downbeat_offset_seconds: float`, `duration_seconds: float`, `expected_hits: tuple[ExpectedHit, ...]`, `sample_rate: int = 22050`, and methods `generate_audio() -> np.ndarray` and `write_wav(path: Path) -> Path`.
  - `render_events(hits: Sequence[ExpectedHit], duration_seconds: float, sample_rate: int = 22050, noise_seed: int = 20260920) -> np.ndarray`.
  - `_steady_rock_beat(start_time: float, tempo_bpm: float, num_measures: int) -> list[ExpectedHit]` (private helper, reused by Task 2's builders).
  - `list_diagnostic_songs() -> list[DiagnosticSong]`, `get_diagnostic_song(key: str) -> DiagnosticSong` (raises `KeyError` for unknown key).

- [ ] **Step 1: Write the failing tests for `render_events`**

Create `backend/tests/test_diagnostic_songs.py` with:

```python
import numpy as np
import pytest

from app.transcription import DrumInstrument
from tests.fixtures.diagnostic_songs import ExpectedHit, render_events


def test_render_events_is_silent_before_a_hits_onset():
    hits = [ExpectedHit(time=1.0, instrument=DrumInstrument.KICK)]

    audio = render_events(hits, duration_seconds=2.0, sample_rate=22050)

    onset_sample = int(1.0 * 22050)
    assert np.all(audio[: onset_sample - 1] == 0.0)


def test_render_events_produces_a_nonzero_onset_at_the_hit_time():
    hits = [ExpectedHit(time=1.0, instrument=DrumInstrument.KICK)]

    audio = render_events(hits, duration_seconds=2.0, sample_rate=22050)

    onset_sample = int(1.0 * 22050)
    window = audio[onset_sample : onset_sample + 200]
    assert np.max(np.abs(window)) > 0.0


def test_render_events_matches_declared_duration_and_sample_rate():
    audio = render_events([], duration_seconds=1.5, sample_rate=22050)

    assert len(audio) == int(round(1.5 * 22050))


def test_render_events_is_deterministic_across_calls():
    hits = [
        ExpectedHit(time=0.1, instrument=DrumInstrument.SNARE),
        ExpectedHit(time=0.2, instrument=DrumInstrument.HIHAT_CLOSED),
    ]

    first = render_events(hits, duration_seconds=1.0, sample_rate=22050)
    second = render_events(hits, duration_seconds=1.0, sample_rate=22050)

    np.testing.assert_array_equal(first, second)


def test_render_events_stays_within_the_minus_one_to_one_range():
    hits = [
        ExpectedHit(time=t, instrument=DrumInstrument.CRASH) for t in (0.0, 0.05, 0.1, 0.15)
    ]

    audio = render_events(hits, duration_seconds=1.0, sample_rate=22050)

    assert np.max(np.abs(audio)) <= 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_diagnostic_songs.py -v`
Expected: FAIL / collection error — `tests.fixtures.diagnostic_songs` does not exist yet.

- [ ] **Step 3: Implement `ExpectedHit` and `render_events` in `diagnostic_songs.py`**

Create `backend/tests/fixtures/diagnostic_songs.py`:

```python
import dataclasses
from pathlib import Path
from typing import Sequence

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
```

Create empty `backend/tests/fixtures/__init__.py` (needed so `tests/fixtures` resolves as a package alongside the namespace-package `tests` directory).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_diagnostic_songs.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/fixtures/__init__.py backend/tests/fixtures/diagnostic_songs.py backend/tests/test_diagnostic_songs.py
git commit -m "feat: add deterministic drum-event audio synthesis for diagnostic fixtures"
```

- [ ] **Step 6: Write the failing tests for `DiagnosticSong`, `_steady_rock_beat`, and the `steady_4_4`/`intro_count_in` fixtures**

Append to `backend/tests/test_diagnostic_songs.py`:

```python
import soundfile as sf

from tests.fixtures.diagnostic_songs import (
    DiagnosticSong,
    get_diagnostic_song,
    list_diagnostic_songs,
)


def test_diagnostic_song_generate_audio_matches_declared_duration():
    song = DiagnosticSong(
        key="test",
        description="test fixture",
        tempo_bpm=120.0,
        downbeat_offset_seconds=0.0,
        duration_seconds=1.0,
        expected_hits=(ExpectedHit(time=0.0, instrument=DrumInstrument.KICK),),
    )

    audio = song.generate_audio()

    assert len(audio) == int(round(1.0 * song.sample_rate))


def test_diagnostic_song_write_wav_produces_a_readable_file_of_matching_length(tmp_path):
    song = DiagnosticSong(
        key="test",
        description="test fixture",
        tempo_bpm=120.0,
        downbeat_offset_seconds=0.0,
        duration_seconds=1.0,
        expected_hits=(ExpectedHit(time=0.0, instrument=DrumInstrument.KICK),),
    )
    wav_path = tmp_path / "song.wav"

    song.write_wav(wav_path)
    audio, sample_rate = sf.read(str(wav_path))

    assert sample_rate == song.sample_rate
    assert len(audio) == len(song.generate_audio())


def test_get_diagnostic_song_raises_for_an_unknown_key():
    with pytest.raises(KeyError):
        get_diagnostic_song("not_a_real_fixture")


def test_steady_4_4_has_its_first_downbeat_at_time_zero():
    song = get_diagnostic_song("steady_4_4")

    assert song.downbeat_offset_seconds == 0.0
    assert song.expected_hits[0].time == 0.0
    assert song.tempo_bpm == 120.0


def test_steady_4_4_expected_hits_are_sorted_and_within_duration():
    song = get_diagnostic_song("steady_4_4")

    times = [hit.time for hit in song.expected_hits]

    assert times == sorted(times)
    assert all(0.0 <= t < song.duration_seconds for t in times)


def test_intro_count_in_places_the_first_downbeat_after_a_count_in():
    song = get_diagnostic_song("intro_count_in")

    assert song.downbeat_offset_seconds > 0.0
    assert song.expected_hits[0].time == pytest.approx(0.5)
    assert any(
        hit.time == pytest.approx(song.downbeat_offset_seconds)
        and hit.instrument == DrumInstrument.KICK
        for hit in song.expected_hits
    )


def test_list_diagnostic_songs_includes_steady_4_4_and_intro_count_in():
    keys = {song.key for song in list_diagnostic_songs()}

    assert {"steady_4_4", "intro_count_in"}.issubset(keys)
```

- [ ] **Step 7: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_diagnostic_songs.py -v`
Expected: FAIL — `DiagnosticSong`, `get_diagnostic_song`, `list_diagnostic_songs`, `_steady_rock_beat` don't exist yet.

- [ ] **Step 8: Implement `DiagnosticSong`, `_steady_rock_beat`, and the two fixture builders**

Append to `backend/tests/fixtures/diagnostic_songs.py`:

```python
from typing import Callable


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


def _steady_rock_beat(
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
    hits = _steady_rock_beat(start_time=0.0, tempo_bpm=tempo_bpm, num_measures=num_measures)

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
    groove_hits = _steady_rock_beat(
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


_BUILDERS: dict[str, Callable[[], DiagnosticSong]] = {
    "steady_4_4": _build_steady_4_4,
    "intro_count_in": _build_intro_count_in,
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
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_diagnostic_songs.py -v`
Expected: PASS (all tests so far).

- [ ] **Step 10: Commit**

```bash
git add backend/tests/fixtures/diagnostic_songs.py backend/tests/test_diagnostic_songs.py
git commit -m "feat: add steady_4_4 and intro_count_in diagnostic song fixtures"
```

---

### Task 2: `dense_fill` and `timing_variation` fixtures, corpus-level tests, and documentation

**Files:**
- Modify: `backend/tests/fixtures/diagnostic_songs.py`
- Modify: `backend/tests/test_diagnostic_songs.py`
- Create: `backend/tests/fixtures/README.md`

**Interfaces:**
- Consumes: everything from Task 1 (`ExpectedHit`, `DiagnosticSong`, `_steady_rock_beat`, `render_events`, `_BUILDERS`, `list_diagnostic_songs`, `get_diagnostic_song`).
- Produces: two more registered fixture keys, `"dense_fill"` and `"timing_variation"`, completing the required set `{"steady_4_4", "intro_count_in", "dense_fill", "timing_variation"}`.

- [ ] **Step 1: Write the failing tests for `dense_fill` and `timing_variation`**

Append to `backend/tests/test_diagnostic_songs.py`:

```python
REQUIRED_KEYS = {"steady_4_4", "intro_count_in", "dense_fill", "timing_variation"}


def test_list_diagnostic_songs_covers_all_required_timing_cases():
    keys = {song.key for song in list_diagnostic_songs()}

    assert keys == REQUIRED_KEYS


@pytest.mark.parametrize("key", sorted(REQUIRED_KEYS))
def test_every_fixture_expected_hits_are_sorted_and_within_duration(key):
    song = get_diagnostic_song(key)

    times = [hit.time for hit in song.expected_hits]

    assert times == sorted(times)
    assert all(0.0 <= t < song.duration_seconds for t in times)


@pytest.mark.parametrize("key", sorted(REQUIRED_KEYS))
def test_every_fixture_generates_deterministic_audio(key):
    song = get_diagnostic_song(key)

    first = song.generate_audio()
    second = song.generate_audio()

    np.testing.assert_array_equal(first, second)


def test_dense_fill_has_a_measure_with_more_hits_than_the_groove_measures():
    song = get_diagnostic_song("dense_fill")
    seconds_per_beat = 60.0 / song.tempo_bpm
    measure_seconds = 4 * seconds_per_beat

    hits_per_measure: dict[int, int] = {}
    for hit in song.expected_hits:
        measure_index = int(hit.time // measure_seconds)
        hits_per_measure[measure_index] = hits_per_measure.get(measure_index, 0) + 1

    groove_measure_counts = [hits_per_measure[0], hits_per_measure[1]]
    fill_measure_count = hits_per_measure[2]

    assert fill_measure_count > max(groove_measure_counts)


def test_timing_variation_deviates_from_a_perfect_grid():
    song = get_diagnostic_song("timing_variation")
    seconds_per_sixteenth = (60.0 / song.tempo_bpm) / 4

    on_grid_hits = sum(
        1
        for hit in song.expected_hits
        if abs((hit.time / seconds_per_sixteenth) - round(hit.time / seconds_per_sixteenth))
        < 1e-6
    )

    assert on_grid_hits < len(song.expected_hits)


def test_timing_variation_has_the_same_instrument_sequence_as_steady_4_4():
    steady = get_diagnostic_song("steady_4_4")
    varied = get_diagnostic_song("timing_variation")

    assert [h.instrument for h in steady.expected_hits] == [
        h.instrument for h in varied.expected_hits
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_diagnostic_songs.py -v`
Expected: FAIL — `"dense_fill"` and `"timing_variation"` are unknown keys.

- [ ] **Step 3: Implement the `dense_fill` and `timing_variation` builders**

Append to `backend/tests/fixtures/diagnostic_songs.py`, replacing the `_BUILDERS` dict:

```python
def _build_dense_fill() -> DiagnosticSong:
    tempo_bpm = 120.0
    seconds_per_beat = 60.0 / tempo_bpm
    groove_measures = 2
    groove_hits = _steady_rock_beat(
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
    base_hits = _steady_rock_beat(start_time=0.0, tempo_bpm=tempo_bpm, num_measures=num_measures)

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
        expected_hits=tuple(jittered_hits),
    )


_BUILDERS: dict[str, Callable[[], DiagnosticSong]] = {
    "steady_4_4": _build_steady_4_4,
    "intro_count_in": _build_intro_count_in,
    "dense_fill": _build_dense_fill,
    "timing_variation": _build_timing_variation,
}
```

Note: `timing_variation`'s `expected_hits` intentionally is NOT re-sorted after
jittering — `_steady_rock_beat` already returns hits close to time order and the
jitter is small (+/-20ms) relative to the 125ms 16th-note grid at 120 BPM, so
order is preserved in practice; the "sorted and within duration" test in Step 1
still checks this holds.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_diagnostic_songs.py -v`
Expected: PASS (all tests). If `test_every_fixture_expected_hits_are_sorted_and_within_duration`
fails for `timing_variation` because jitter reordered two adjacent hits, change
`expected_hits=tuple(jittered_hits)` to
`expected_hits=tuple(sorted(jittered_hits, key=lambda h: h.time))` in
`_build_timing_variation` and re-run.

- [ ] **Step 5: Write the documentation**

Create `backend/tests/fixtures/README.md`:

```markdown
# Diagnostic song fixtures

Small, deterministic, synthetic drum-track fixtures used by EPIC 1
(Instrumentation & Stabilization, #28) to reproduce timing-related issues
without depending on real (copyrighted) recordings.

## Why synthetic

Every fixture's audio is generated at test time by `diagnostic_songs.py`
from known event times - nothing is committed as a binary audio asset.
This keeps the corpus:

- **deterministic**: same seed in, same waveform out, every run.
- **copyright-safe**: no real recordings are used or distributed.
- **small**: fixtures are seconds long and exist only in memory or in a
  test's `tmp_path` while a test runs.

## Usage

    from tests.fixtures.diagnostic_songs import get_diagnostic_song

    song = get_diagnostic_song("intro_count_in")
    audio = song.generate_audio()          # np.ndarray, mono, song.sample_rate Hz
    song.write_wav(tmp_path / "song.wav")  # for tests that need a real audio file

    song.tempo_bpm                # ground-truth tempo
    song.downbeat_offset_seconds  # ground-truth offset of measure 1 / beat 1
    song.expected_hits            # tuple[ExpectedHit], ground truth (time, instrument)

`list_diagnostic_songs()` returns every fixture; `get_diagnostic_song(key)`
raises `KeyError` for an unknown key.

## Fixtures

| key | timing case | tempo | downbeat offset | what it targets |
|---|---|---|---|---|
| `steady_4_4` | steady 4/4 | 120 BPM | 0.0s | Baseline: constant-tempo rock beat, first downbeat at t=0. |
| `intro_count_in` | intro silence / count-in | 120 BPM | 2.5s | 0.5s silence plus a 1-measure hi-hat count-in before the first real downbeat - exercises the fixed-grid phase-alignment gap in `quantize_events` (see `TECHNICAL_DEBT.md`, "Quantization grid isn't phase-aligned to the beat"). |
| `dense_fill` | dense 16ths / fills | 120 BPM | 0.0s | Two measures of groove, then a full measure of straight 16th-note snare/tom fill resolving on a crash+kick downbeat - exercises dense event rates and simultaneous-hit grouping. |
| `timing_variation` | timing variation | 120 BPM | 0.0s | Same groove as `steady_4_4`, every hit shifted by a deterministic +/-20ms seeded jitter - simulates a live, non-quantized performance. |

Every fixture's `expected_hits` is the ground truth: exact `(time,
instrument)` pairs the synthesized audio was built from. Consumers (tempo
estimation, quantization, transcription-diagnostics tests) compare pipeline
output against this ground truth instead of a real recording's unknown,
unverifiable transcription.

## Adding a new fixture

1. Add a `_build_<name>()` function returning a `DiagnosticSong`, using
   `_steady_rock_beat(...)` or building `ExpectedHit`s directly.
2. Register it in `_BUILDERS` in `diagnostic_songs.py`.
3. Document it in the table above.
```

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && uv run pytest -v`
Expected: PASS, no regressions in any pre-existing test file.

- [ ] **Step 7: Run lint/type checks if configured**

Run: `cd backend && uv run ruff check .` (skip if `ruff` is not a dev dependency —
check `backend/pyproject.toml`'s `[dependency-groups].dev` first; if absent,
there is no backend linter configured and this step is a no-op).

- [ ] **Step 8: Commit**

```bash
git add backend/tests/fixtures/diagnostic_songs.py backend/tests/fixtures/README.md backend/tests/test_diagnostic_songs.py
git commit -m "feat: add dense_fill and timing_variation fixtures with corpus docs"
```

---

## Self-Review Notes

- **Spec coverage:** all 4 acceptance criteria from issue #34 map to concrete tasks: fixtures cover the 4 listed timing cases (Task 1 + Task 2 builders), expected metadata is documented (README table + dataclass fields), tests reference fixtures deterministically (`get_diagnostic_song(key)` + determinism tests), no large/copyright-problematic assets committed (pure synthesis, nothing binary committed - documented explicitly in the README's "Why synthetic" section).
- **`docs/ARCHITECTURE_V1.md` referenced by the issue's "Working rules" does not exist in the repository yet** (verified: not on disk, not in git history on any branch). Proceeding using `PROJECT.md`, `TECHNICAL_DEBT.md`, and `docs/status/2026-09-20-current-app-state.md` (the de facto current-architecture writeup) instead, since this task only adds test fixtures and touches no architectural surface. Flagging this gap in the final summary rather than authoring that doc, since creating it is out of scope for V1-001.
