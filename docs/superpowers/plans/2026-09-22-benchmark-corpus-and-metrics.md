# Benchmark Corpus and Metrics Harness (V1-012 + V1-013) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable, synthetic, labelled transcription-accuracy benchmark corpus (GitHub issue #45 / V1-012) and an automated per-instrument precision/recall/F1 metrics harness that records DrumScript's real measured baseline against it (issue #46 / V1-013) — the "measure before you change anything" foundation the rest of Epic 3 (#47-#49) builds on.

**Architecture:** Reuses the existing `backend/tests/fixtures/diagnostic_songs.py` pattern (synthetic, deterministic, copyright-safe audio built from known `ExpectedHit(time, instrument)` ground truth) rather than inventing a parallel format. A new sibling fixture module, `backend/tests/fixtures/benchmark_corpus.py`, adds 6 songs covering every `DrumInstrument` and several distinct groove styles, reusing `diagnostic_songs.py`'s `DiagnosticSong`/`ExpectedHit`/`render_events` directly. A new production module, `backend/app/benchmark.py`, matches a transcriber's real output against a song's ground truth (greedy nearest-time matching, per instrument, within a documented tolerance) and reports precision/recall/F1 per instrument plus the raw false-positive/false-negative events for inspection. A final test actually runs the real, already-installed `DrumScriptTranscriber` against the corpus and records its baseline numbers as a regression floor.

**Tech Stack:** Python 3.13, pytest, numpy/soundfile (already dependencies). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-22-transcription-engine-2-0-design.md` (sections "#45 — Benchmark corpus" and "#46 — Metrics harness"), GitHub issues #45 and #46, `CLAUDE.md`'s Transcription rules ("Use labelled/controlled fixtures and per-instrument metrics", "Preserve raw engine output for diagnostics").

## Global Constraints

- All benchmark audio is synthetic and generated at test time from known event times — no committed binary audio, no real/copyrighted recordings (matches `diagnostic_songs.py`'s existing guarantee).
- Ground-truth format is `ExpectedHit(time, instrument)` — reused from `diagnostic_songs.py`, not reinvented.
- Matching timing tolerance is a named, documented constant: `DEFAULT_MATCH_TOLERANCE_SECONDS = 0.05` (±50ms).
- `backend/tests/fixtures/diagnostic_songs.py`'s existing 4 timing-diagnostic fixtures and their consumers are untouched except for the one rename in Task 1.
- Backend tests run via `cd backend && uv run pytest ...` (Python >=3.13, pytest). No new dependencies.
- Do not modify `drumscript`/`DrumScriptTranscriber`'s classification logic in this plan — this plan only measures it.

---

## File Structure

- Modify `backend/tests/fixtures/diagnostic_songs.py` — promote `_steady_rock_beat` to public `steady_rock_beat` (now used by a second module).
- Modify `backend/tests/fixtures/README.md` — document the promoted helper's new visibility and add a new corpus table.
- Create `backend/tests/fixtures/benchmark_corpus.py` — the 6-song transcription-accuracy corpus.
- Create `backend/tests/test_benchmark_corpus.py` — corpus completeness/validity tests.
- Create `backend/app/benchmark.py` — `InstrumentMetrics`, `BenchmarkResult`, `evaluate_transcriber`, `evaluate_corpus`.
- Create `backend/tests/test_benchmark.py` — fast unit tests for the matching/metrics algorithm using fake transcribers.
- Create `backend/tests/test_transcription_benchmark.py` — the slower real-`DrumScriptTranscriber` baseline-recording test.

---

### Task 1: Promote `_steady_rock_beat` to a public, shared helper

**Files:**
- Modify: `backend/tests/fixtures/diagnostic_songs.py:106-134` (rename + its 4 call sites at lines 141, 169, 193, 249)
- Modify: `backend/tests/fixtures/README.md:53` (the one prose reference to the old name)
- Test: `backend/tests/test_diagnostic_songs.py` (existing suite, unchanged — provides regression coverage)

**Interfaces:**
- Consumes: nothing new.
- Produces: `steady_rock_beat(start_time: float, tempo_bpm: float, num_measures: int) -> list[ExpectedHit]` (same signature and behavior as today's `_steady_rock_beat`, just without the leading underscore) — Task 2's `benchmark_corpus.py` imports this.

- [ ] **Step 1: Rename the function and its call sites**

In `backend/tests/fixtures/diagnostic_songs.py`, rename `_steady_rock_beat` to `steady_rock_beat` at its definition (line 106) and at all 4 call sites (lines 141, 169, 193, 249) — a pure find-replace of the identifier, no behavior change. No docstring exists to update (the function has none today; leave it that way, consistent with the file's other builder functions).

In `backend/tests/fixtures/README.md`, change the sentence at line 53 from:

```
1. Add a `_build_<name>()` function returning a `DiagnosticSong`, using
   `_steady_rock_beat(...)` or building `ExpectedHit`s directly.
```

to:

```
1. Add a `_build_<name>()` function returning a `DiagnosticSong`, using
   `steady_rock_beat(...)` or building `ExpectedHit`s directly.
```

- [ ] **Step 2: Run the existing diagnostic-songs test suite to confirm no regression**

Run: `cd backend && uv run pytest tests/test_diagnostic_songs.py -v`
Expected: all tests PASS, identically to before the rename (this is a pure identifier rename with no behavior change; the existing suite exercises `steady_rock_beat` indirectly through `list_diagnostic_songs()`/`get_diagnostic_song()`, which is sufficient regression coverage — no new test is needed for a rename).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/fixtures/diagnostic_songs.py backend/tests/fixtures/README.md
git commit -m "refactor: promote steady_rock_beat to a public, shared fixture helper"
```

---

### Task 2: Build the 6-song benchmark corpus

**Files:**
- Create: `backend/tests/fixtures/benchmark_corpus.py`
- Modify: `backend/tests/fixtures/README.md` (append a new section documenting the corpus)
- Test: `backend/tests/test_benchmark_corpus.py`

**Interfaces:**
- Consumes: `DiagnosticSong`, `ExpectedHit`, `steady_rock_beat` from `tests.fixtures.diagnostic_songs` (Task 1's public name); `DrumInstrument` from `app.transcription`.
- Produces: `list_benchmark_songs() -> list[DiagnosticSong]` and `get_benchmark_song(key: str) -> DiagnosticSong` (same API shape as `diagnostic_songs.py`'s equivalents) — Task 3's tests and Task 4's baseline test both consume these.

- [ ] **Step 1: Write the failing corpus-validity tests**

Create `backend/tests/test_benchmark_corpus.py`:

```python
import pytest

from app.transcription import DrumInstrument
from tests.fixtures.benchmark_corpus import (
    get_benchmark_song,
    list_benchmark_songs,
)


def test_list_benchmark_songs_returns_six_songs():
    songs = list_benchmark_songs()

    assert len(songs) == 6


def test_list_benchmark_songs_has_unique_keys():
    songs = list_benchmark_songs()

    keys = [song.key for song in songs]
    assert len(keys) == len(set(keys))


def test_get_benchmark_song_raises_key_error_for_unknown_key():
    with pytest.raises(KeyError, match="Unknown benchmark song fixture"):
        get_benchmark_song("does_not_exist")


def test_get_benchmark_song_returns_the_matching_song():
    song = get_benchmark_song("straight_rock")

    assert song.key == "straight_rock"


def test_every_expected_hit_time_is_within_the_songs_duration():
    for song in list_benchmark_songs():
        for hit in song.expected_hits:
            assert 0.0 <= hit.time < song.duration_seconds, (
                f"{song.key}: hit at {hit.time}s exceeds duration {song.duration_seconds}s"
            )


def test_every_expected_hit_time_is_non_negative():
    for song in list_benchmark_songs():
        for hit in song.expected_hits:
            assert hit.time >= 0.0


def test_every_song_has_at_least_one_expected_hit():
    for song in list_benchmark_songs():
        assert len(song.expected_hits) > 0, f"{song.key} has no expected hits"


def test_corpus_covers_every_drum_instrument_at_least_once():
    covered_instruments = {
        hit.instrument for song in list_benchmark_songs() for hit in song.expected_hits
    }

    assert covered_instruments == set(DrumInstrument)


def test_full_kit_mixed_song_alone_covers_every_drum_instrument():
    song = get_benchmark_song("full_kit_mixed")

    covered_instruments = {hit.instrument for hit in song.expected_hits}
    assert covered_instruments == set(DrumInstrument)


def test_generate_audio_produces_nonempty_audio_for_every_song():
    for song in list_benchmark_songs():
        audio = song.generate_audio()
        assert len(audio) > 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_benchmark_corpus.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.fixtures.benchmark_corpus'` (the module doesn't exist yet).

- [ ] **Step 3: Implement the 6-song corpus**

Create `backend/tests/fixtures/benchmark_corpus.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_benchmark_corpus.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Document the corpus in the fixtures README**

Append to `backend/tests/fixtures/README.md` (after the existing "Adding a new fixture" section, at the end of the file):

```markdown

---

# Transcription-accuracy benchmark corpus

Synthetic fixtures used by EPIC 3 (Transcription Engine 2.0, #30) to
measure `DrumTranscriber` accuracy per instrument - a different purpose
from the diagnostic songs above (which target *timing* edge cases, not
classification accuracy). Same underlying `DiagnosticSong`/`ExpectedHit`
machinery, imported from `diagnostic_songs.py` rather than duplicated;
lives in its own module, `benchmark_corpus.py`, because it's a distinct
consumer with its own six songs.

## Usage

```python
from tests.fixtures.benchmark_corpus import get_benchmark_song, list_benchmark_songs
```

Same API shape as `diagnostic_songs.py`'s `get_diagnostic_song`/
`list_diagnostic_songs`.

## Songs

| key | groove style | instruments exercised |
|---|---|---|
| `straight_rock` | steady quarter-note kick/snare backbeat, closed hi-hat eighths | kick, snare, hihat_closed |
| `syncopated_funk` | off-beat kick (1, &2, &3), open hi-hat accent | kick, snare, hihat_closed, hihat_open |
| `double_kick` | fast (160 BPM) eighth-note kick pattern | kick, snare, hihat_closed |
| `tom_fill_crash` | descending tom fill resolving on crash+kick | tom_high, tom_mid, tom_low, crash, kick |
| `ride_groove` | ride-cymbal-driven groove instead of hi-hat | ride, kick, snare |
| `full_kit_mixed` | verse + ride chorus + tom fill, touching every instrument in one song | all 9 `DrumInstrument` values |

Timing match tolerance for comparing a transcriber's output against this
corpus's ground truth is `DEFAULT_MATCH_TOLERANCE_SECONDS` (±50ms) in
`app/benchmark.py`.
```

- [ ] **Step 6: Commit**

```bash
git add backend/tests/fixtures/benchmark_corpus.py backend/tests/test_benchmark_corpus.py backend/tests/fixtures/README.md
git commit -m "feat: add the 6-song transcription-accuracy benchmark corpus"
```

---

### Task 3: Build the metrics harness

**Files:**
- Create: `backend/app/benchmark.py`
- Test: `backend/tests/test_benchmark.py`

**Interfaces:**
- Consumes: `DiagnosticSong`, `ExpectedHit` from `tests.fixtures.diagnostic_songs`; `DrumEvent`, `DrumInstrument`, `DrumTranscriber` from `app.transcription`.
- Produces: `DEFAULT_MATCH_TOLERANCE_SECONDS: float`, `InstrumentMetrics` (dataclass), `BenchmarkResult` (dataclass), `evaluate_transcriber(transcriber, song, tolerance_seconds=DEFAULT_MATCH_TOLERANCE_SECONDS) -> BenchmarkResult`, `evaluate_corpus(transcriber, songs, tolerance_seconds=DEFAULT_MATCH_TOLERANCE_SECONDS) -> tuple[BenchmarkResult, ...]` — Task 4's real-DrumScript test, and later #49's post-processing work, both consume these directly.

- [ ] **Step 1: Write the failing unit tests**

Create `backend/tests/test_benchmark.py`:

```python
import pytest

from app.benchmark import DEFAULT_MATCH_TOLERANCE_SECONDS, evaluate_corpus, evaluate_transcriber
from app.transcription import DrumEvent, DrumInstrument
from tests.fixtures.diagnostic_songs import DiagnosticSong, ExpectedHit


def _song(expected_hits: list[ExpectedHit], duration_seconds: float = 2.0) -> DiagnosticSong:
    return DiagnosticSong(
        key="test_song",
        description="test fixture",
        tempo_bpm=120.0,
        downbeat_offset_seconds=0.0,
        duration_seconds=duration_seconds,
        expected_hits=tuple(expected_hits),
    )


class FakeTranscriber:
    def __init__(self, events: list[DrumEvent]):
        self._events = events

    def transcribe(self, audio_path):
        return self._events


def test_evaluate_transcriber_counts_an_exact_time_match_as_a_true_positive():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.KICK)])
    transcriber = FakeTranscriber(
        [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.KICK)]
    )

    result = evaluate_transcriber(transcriber, song)

    kick_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.KICK)
    assert kick_metrics.true_positives == 1
    assert kick_metrics.false_positives == 0
    assert kick_metrics.false_negatives == 0
    assert kick_metrics.precision == 1.0
    assert kick_metrics.recall == 1.0
    assert kick_metrics.f1 == 1.0


def test_evaluate_transcriber_matches_within_tolerance():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.SNARE)])
    transcriber = FakeTranscriber(
        [DrumEvent(id="e1", time=1.0 + DEFAULT_MATCH_TOLERANCE_SECONDS, instrument=DrumInstrument.SNARE)]
    )

    result = evaluate_transcriber(transcriber, song)

    snare_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.SNARE)
    assert snare_metrics.true_positives == 1
    assert snare_metrics.false_positives == 0
    assert snare_metrics.false_negatives == 0


def test_evaluate_transcriber_does_not_match_beyond_tolerance():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.SNARE)])
    transcriber = FakeTranscriber(
        [
            DrumEvent(
                id="e1",
                time=1.0 + DEFAULT_MATCH_TOLERANCE_SECONDS + 0.01,
                instrument=DrumInstrument.SNARE,
            )
        ]
    )

    result = evaluate_transcriber(transcriber, song)

    snare_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.SNARE)
    assert snare_metrics.true_positives == 0
    assert snare_metrics.false_positives == 1
    assert snare_metrics.false_negatives == 1


def test_evaluate_transcriber_counts_an_unmatched_prediction_as_a_false_positive():
    song = _song([])
    transcriber = FakeTranscriber(
        [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.CRASH)]
    )

    result = evaluate_transcriber(transcriber, song)

    crash_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.CRASH)
    assert crash_metrics.false_positives == 1
    assert crash_metrics.precision == 0.0
    assert result.unmatched_predicted == (DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.CRASH),)


def test_evaluate_transcriber_counts_an_unmatched_expected_hit_as_a_false_negative():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.RIDE)])
    transcriber = FakeTranscriber([])

    result = evaluate_transcriber(transcriber, song)

    ride_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.RIDE)
    assert ride_metrics.false_negatives == 1
    assert ride_metrics.recall == 0.0
    assert result.unmatched_expected == (ExpectedHit(time=1.0, instrument=DrumInstrument.RIDE),)


def test_evaluate_transcriber_does_not_match_across_different_instruments():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.TOM_LOW)])
    transcriber = FakeTranscriber(
        [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.TOM_HIGH)]
    )

    result = evaluate_transcriber(transcriber, song)

    tom_low_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.TOM_LOW)
    tom_high_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.TOM_HIGH)
    assert tom_low_metrics.false_negatives == 1
    assert tom_high_metrics.false_positives == 1


def test_evaluate_transcriber_matches_the_closest_of_two_duplicate_predictions():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.HIHAT_CLOSED)])
    transcriber = FakeTranscriber(
        [
            DrumEvent(id="e1", time=1.03, instrument=DrumInstrument.HIHAT_CLOSED),
            DrumEvent(id="e2", time=1.01, instrument=DrumInstrument.HIHAT_CLOSED),
        ]
    )

    result = evaluate_transcriber(transcriber, song)

    hihat_metrics = next(
        m for m in result.per_instrument if m.instrument == DrumInstrument.HIHAT_CLOSED
    )
    assert hihat_metrics.true_positives == 1
    assert hihat_metrics.false_positives == 1
    assert result.unmatched_predicted == (
        DrumEvent(id="e2", time=1.03, instrument=DrumInstrument.HIHAT_CLOSED),
    )


def test_evaluate_corpus_returns_one_result_per_song_in_order():
    songs = [_song([]), _song([])]
    songs[0] = DiagnosticSong(**{**songs[0].__dict__, "key": "first"})
    songs[1] = DiagnosticSong(**{**songs[1].__dict__, "key": "second"})
    transcriber = FakeTranscriber([])

    results = evaluate_corpus(transcriber, songs)

    assert [r.song_key for r in results] == ["first", "second"]


def test_evaluate_transcriber_f1_is_zero_when_both_precision_and_recall_are_zero():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.KICK)])
    transcriber = FakeTranscriber(
        [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.SNARE)]
    )

    result = evaluate_transcriber(transcriber, song)

    kick_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.KICK)
    assert kick_metrics.precision == 0.0
    assert kick_metrics.recall == 0.0
    assert kick_metrics.f1 == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_benchmark.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.benchmark'`.

- [ ] **Step 3: Implement the metrics harness**

Create `backend/app/benchmark.py`:

```python
import dataclasses
import tempfile
from pathlib import Path
from typing import Sequence

from app.transcription import DrumEvent, DrumInstrument, DrumTranscriber
from tests.fixtures.diagnostic_songs import DiagnosticSong, ExpectedHit

DEFAULT_MATCH_TOLERANCE_SECONDS = 0.05


@dataclasses.dataclass(frozen=True)
class InstrumentMetrics:
    instrument: DrumInstrument
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float


@dataclasses.dataclass(frozen=True)
class BenchmarkResult:
    song_key: str
    per_instrument: tuple[InstrumentMetrics, ...]
    unmatched_predicted: tuple[DrumEvent, ...]
    unmatched_expected: tuple[ExpectedHit, ...]


def _match_instrument(
    predicted: list[DrumEvent],
    expected: list[ExpectedHit],
    tolerance_seconds: float,
) -> tuple[int, list[DrumEvent], list[ExpectedHit]]:
    """Greedy nearest-time matching within a single instrument: each
    predicted event (processed in time order) is matched to its closest
    still-unmatched expected hit within tolerance_seconds. Simple and
    auditable rather than an optimal assignment algorithm - sufficient for
    this corpus's sparse (tens of hits) songs. Returns
    (true_positive_count, unmatched_predicted, unmatched_expected)."""
    remaining_expected = list(expected)
    unmatched_predicted: list[DrumEvent] = []
    true_positives = 0

    for event in sorted(predicted, key=lambda e: e.time):
        best_index = None
        best_distance = None
        for index, hit in enumerate(remaining_expected):
            distance = abs(event.time - hit.time)
            if distance <= tolerance_seconds and (best_distance is None or distance < best_distance):
                best_index = index
                best_distance = distance

        if best_index is None:
            unmatched_predicted.append(event)
        else:
            remaining_expected.pop(best_index)
            true_positives += 1

    return true_positives, unmatched_predicted, remaining_expected


def evaluate_transcriber(
    transcriber: DrumTranscriber,
    song: DiagnosticSong,
    tolerance_seconds: float = DEFAULT_MATCH_TOLERANCE_SECONDS,
) -> BenchmarkResult:
    """Synthesizes song's audio, runs it through transcriber, and scores
    the result against song's ground truth per instrument."""
    with tempfile.TemporaryDirectory() as scratch_dir:
        audio_path = Path(scratch_dir) / f"{song.key}.wav"
        song.write_wav(audio_path)
        predicted_events = transcriber.transcribe(audio_path)

    per_instrument: list[InstrumentMetrics] = []
    all_unmatched_predicted: list[DrumEvent] = []
    all_unmatched_expected: list[ExpectedHit] = []

    for instrument in DrumInstrument:
        predicted_for_instrument = [e for e in predicted_events if e.instrument == instrument]
        expected_for_instrument = [h for h in song.expected_hits if h.instrument == instrument]

        true_positives, unmatched_predicted, unmatched_expected = _match_instrument(
            predicted_for_instrument, expected_for_instrument, tolerance_seconds
        )
        false_positives = len(unmatched_predicted)
        false_negatives = len(unmatched_expected)

        precision = (
            true_positives / (true_positives + false_positives)
            if (true_positives + false_positives) > 0
            else 0.0
        )
        recall = (
            true_positives / (true_positives + false_negatives)
            if (true_positives + false_negatives) > 0
            else 0.0
        )
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        per_instrument.append(
            InstrumentMetrics(
                instrument=instrument,
                true_positives=true_positives,
                false_positives=false_positives,
                false_negatives=false_negatives,
                precision=precision,
                recall=recall,
                f1=f1,
            )
        )
        all_unmatched_predicted.extend(unmatched_predicted)
        all_unmatched_expected.extend(unmatched_expected)

    return BenchmarkResult(
        song_key=song.key,
        per_instrument=tuple(per_instrument),
        unmatched_predicted=tuple(sorted(all_unmatched_predicted, key=lambda e: e.time)),
        unmatched_expected=tuple(sorted(all_unmatched_expected, key=lambda h: h.time)),
    )


def evaluate_corpus(
    transcriber: DrumTranscriber,
    songs: Sequence[DiagnosticSong],
    tolerance_seconds: float = DEFAULT_MATCH_TOLERANCE_SECONDS,
) -> tuple[BenchmarkResult, ...]:
    return tuple(evaluate_transcriber(transcriber, song, tolerance_seconds) for song in songs)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_benchmark.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmark.py backend/tests/test_benchmark.py
git commit -m "feat: add the per-instrument precision/recall/F1 metrics harness"
```

---

### Task 4: Record DrumScript's real baseline against the corpus

**Files:**
- Create: `backend/tests/test_transcription_benchmark.py`

**Interfaces:**
- Consumes: `evaluate_corpus` from `app.benchmark` (Task 3); `list_benchmark_songs` from `tests.fixtures.benchmark_corpus` (Task 2); `DrumScriptTranscriber` from `app.drumscript_transcriber` (existing, unmodified).
- Produces: a checked-in regression floor for DrumScript's real corpus-wide F1 — later issues (#49) read this file's recorded baseline to judge whether a post-processing change is an improvement.

This task is **calibration-based**, not pure TDD: the exact baseline numbers cannot be known until DrumScript is actually run against the real corpus (no one can hand-compute what a rule-based physics classifier does on synthesized sine-wave/noise-burst audio it was never tuned against). Follow this exact procedure — it is fully mechanical, not a judgment call.

- [ ] **Step 1: Write a throwaway script to observe DrumScript's real numbers**

Create a scratch file `backend/tests/_observe_baseline.py` (temporary — deleted in Step 4, never committed):

```python
from app.benchmark import evaluate_corpus
from app.drumscript_transcriber import DrumScriptTranscriber
from tests.fixtures.benchmark_corpus import list_benchmark_songs

results = evaluate_corpus(DrumScriptTranscriber(), list_benchmark_songs())

total_tp = total_fp = total_fn = 0
for result in results:
    print(f"\n=== {result.song_key} ===")
    for m in result.per_instrument:
        if m.true_positives or m.false_positives or m.false_negatives:
            print(
                f"  {m.instrument.value}: TP={m.true_positives} FP={m.false_positives} "
                f"FN={m.false_negatives} P={m.precision:.2f} R={m.recall:.2f} F1={m.f1:.2f}"
            )
        total_tp += m.true_positives
        total_fp += m.false_positives
        total_fn += m.false_negatives

precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
print(f"\n=== CORPUS-WIDE ===\nP={precision:.4f} R={recall:.4f} F1={f1:.4f}")
```

- [ ] **Step 2: Run it once to observe DrumScript's real, current numbers**

Run: `cd backend && uv run python -m tests._observe_baseline`

This runs the real `DrumScriptTranscriber` (a real subprocess into `backend/drumscript_runner`'s venv) against all 6 corpus songs. Record the printed corpus-wide F1 value — call it `OBSERVED_F1` for the next step. (Typical runtime: a few seconds per song; if any song times out or errors, that itself is a finding — report it in DONE_WITH_CONCERNS rather than silently working around it, since `DrumScriptTranscriber` already raises `TranscriptionError` on real failures and this task must not swallow that.)

- [ ] **Step 3: Write the baseline-recording test using the observed value**

Create `backend/tests/test_transcription_benchmark.py`, substituting the `OBSERVED_F1` value you recorded in Step 2 for the literal `<OBSERVED_F1>` placeholder below (e.g. if you observed `0.4231`, write `0.4231`):

```python
"""Records DrumScript's real, measured baseline accuracy against the
Epic 3 benchmark corpus (backend/tests/fixtures/benchmark_corpus.py).

This is a regression floor, not a target: the corpus-wide F1 value below
was the actual measured result of running the real DrumScriptTranscriber
against the corpus at the time this test was written (see
docs/superpowers/plans/2026-09-22-benchmark-corpus-and-metrics.md, Task 4
for the exact procedure used to obtain it). If a future change to
DrumScript, the corpus, or post-processing legitimately changes this
number, update BASELINE_CORPUS_F1 deliberately (with a comment explaining
why) rather than loosening the margin below to make a regression pass.

This test is slower than the rest of the suite (real audio synthesis +
a real DrumScript subprocess call per song) - kept in its own file so it
can be selected or skipped independently if that proves necessary.
"""

from app.benchmark import evaluate_corpus
from app.drumscript_transcriber import DrumScriptTranscriber
from tests.fixtures.benchmark_corpus import list_benchmark_songs

# The real, measured corpus-wide F1 at the time this test was written -
# see the module docstring above for how this number was obtained.
BASELINE_CORPUS_F1 = <OBSERVED_F1>
REGRESSION_MARGIN = 0.05


def _corpus_wide_f1(results):
    total_tp = total_fp = total_fn = 0
    for result in results:
        for metrics in result.per_instrument:
            total_tp += metrics.true_positives
            total_fp += metrics.false_positives
            total_fn += metrics.false_negatives

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    return 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0


def test_drumscript_meets_its_recorded_baseline_on_the_benchmark_corpus():
    results = evaluate_corpus(DrumScriptTranscriber(), list_benchmark_songs())

    f1 = _corpus_wide_f1(results)

    assert f1 >= BASELINE_CORPUS_F1 - REGRESSION_MARGIN, (
        f"DrumScript's corpus-wide F1 ({f1:.4f}) dropped more than "
        f"{REGRESSION_MARGIN} below its recorded baseline "
        f"({BASELINE_CORPUS_F1}) - see this file's docstring."
    )


def test_evaluate_corpus_returns_a_result_for_every_benchmark_song():
    results = evaluate_corpus(DrumScriptTranscriber(), list_benchmark_songs())

    assert {r.song_key for r in results} == {s.key for s in list_benchmark_songs()}
```

- [ ] **Step 4: Delete the throwaway observation script and run the real test**

```bash
rm backend/tests/_observe_baseline.py
```

Run: `cd backend && uv run pytest tests/test_transcription_benchmark.py -v`
Expected: both tests PASS (the baseline test passes by construction, since `BASELINE_CORPUS_F1` was set from this exact same measurement in Step 2 — this run confirms the value was transcribed correctly and the test is stable, not flaky, on a second real run).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run pytest -v`
Expected: all tests PASS (this task's real-subprocess test included), no `_observe_baseline.py` file remaining (`git status` should show it was never staged).

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_transcription_benchmark.py
git commit -m "test: record DrumScript's real measured baseline on the benchmark corpus"
```

---

## Self-Review Notes

- **Spec coverage:** #45's acceptance criteria (documented ground-truth format, documented timing tolerance, multiple groove styles, repeatable) are met by Task 2 (reuses the already-documented `ExpectedHit` format, 6 distinct grooves, deterministic generation) and Task 3 (`DEFAULT_MATCH_TOLERANCE_SECONDS` is a named, docstring-explained constant). #46's acceptance criteria (automatic metrics, inspectable FP/FN, explicit tolerance, recorded baseline) are met by Task 3 (`BenchmarkResult.unmatched_predicted`/`unmatched_expected`) and Task 4 (the checked-in baseline test).
- **Placeholder scan:** the only literal placeholder is `<OBSERVED_F1>` in Task 4, which is not a "TBD" — it's a value that is mechanically impossible to know before running real code against a real external classifier, and the task gives the exact, complete procedure to obtain it (Steps 1-2) before it's used (Step 3). Every other step has complete, runnable code.
- **Type consistency:** `evaluate_transcriber`/`evaluate_corpus`'s signatures are identical between Task 3's implementation and Task 4's usage (`evaluate_corpus(transcriber, songs)`, positional). `DiagnosticSong`/`ExpectedHit`/`steady_rock_beat` names match between Task 1's rename and Tasks 2-3's imports.
