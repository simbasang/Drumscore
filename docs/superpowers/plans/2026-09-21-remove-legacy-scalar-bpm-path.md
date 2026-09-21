# Remove Legacy Scalar-BPM Timing Path (V1-011) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the last production path that reconstructs musical timing from a single scalar BPM, so every consumer of tempo-mapped events is provably driven by real detected beat anchors (`BeatPoint`/`TempoMap`), closing out GitHub issue #44 (V1-011) and Epic 2.

**Architecture:** `backend/app/job_processor.py`'s `run_tempo_mapping` currently falls back to `quantize_events(events, bpm)` (a constant-BPM grid anchored at t=0) whenever `beat_detector.detect()` raises `BeatDetectionError` or returns fewer than 2 `BeatPoint`s. `backend/app/diagnostics.py`'s `build_event_diagnostics` has the same fallback via `musical_position_to_seconds`. Both fallbacks are dead-end compatibility code left over from the V1-010 migration (`docs/superpowers/plans/2026-09-21-beat-anchored-quantization.md`), explicitly flagged in a `job_processor.py` comment as "#44/V1-011's job". This plan removes both fallbacks: a job that can't get at least 2 real beat anchors now fails explicitly (`JobStatus.FAILED` with a clear error) instead of silently degrading to inaccurate constant-tempo timing, and the now-dead `quantize_events`/`musical_position_to_seconds` functions are deleted along with their tests. `TempoMap.constant(bpm)` and the `tempo_bpm` field stay — they're still informational display data (shown in the UI, returned in the analysis/diagnostics API responses) — but their docstrings/comments are updated to stop describing them as a "legacy pipeline" since that pipeline no longer exists.

**Tech Stack:** Python 3.13, FastAPI, pytest (backend only — no frontend files are touched, confirmed by grep: `frontend/lib/notation/timeline.ts` has no scalar-BPM/legacy-grid references left after V1-010).

**Spec:** GitHub issue #44 (V1-011 — Remove legacy scalar-BPM timing path), `docs/ARCHITECTURE_V1.md` (Migration section: "remove legacy scalar-BPM/grid code only after tests prove the new path owns all consumers"), `PROJECT.md` (Epic 2 exit gate), `TECHNICAL_DEBT.md` ("Playback playhead used a constant-tempo approximation... resolved in V1-010" — the frontend half of this same migration).

## Global Constraints

- Source audio time is authoritative; every `DrumEvent` keeps its immutable `time`. (`CLAUDE.md`)
- No production consumer may reconstruct musical timing from a single scalar BPM after this change. (Issue #44 acceptance criteria)
- Diagnose before fixing; do not patch symptoms; preserve source timestamps; add regression coverage. (`CLAUDE.md`)
- Backend tests run via `uv run pytest` from `backend/` (pytest + pytest-cov, Python >=3.13, per `backend/pyproject.toml`). No new dependencies.
- Keep changes scoped to #44 — do not touch `LibrosaBeatDetector`'s internal double tempo-estimation call or any Epic 3+ concerns.

---

## File Structure

- Modify `backend/app/job_processor.py` — `run_tempo_mapping` fails the job instead of falling back to a constant grid.
- Modify `backend/app/beat_mapping.py` — delete `quantize_events` and `musical_position_to_seconds`; update a stale docstring reference.
- Modify `backend/app/diagnostics.py` — `build_event_diagnostics` requires real `beats`, always reconstructs via `beat_anchored_position_to_seconds`.
- Modify `backend/app/api/jobs.py` — `get_job_diagnostics` guards on `job.beats is None` too.
- Modify `backend/app/timing.py` — `TempoMap.constant` docstring no longer calls itself a "legacy pipeline bridge".
- Modify `backend/tests/test_job_processor.py` — replace the two "falls back to the legacy grid" tests with "marks job failed" tests; rename the "alongside_the_legacy_scalar_bpm" test.
- Modify `backend/tests/test_beat_mapping.py` — delete tests for the removed functions.
- Modify `backend/tests/test_diagnostics.py` — rewrite every test to build fixtures via `quantize_events_with_beats` + a `beats` list instead of `quantize_events`/bpm; delete the no-beats-fallback test.
- Modify `backend/tests/test_jobs_api.py` — add one regression test locking in the new API-level guard.

---

### Task 1: Fail the job when beat detection can't produce a usable beat grid

**Files:**
- Modify: `backend/tests/test_job_processor.py:353-393` (the two fallback tests) and `:270` (rename)
- Modify: `backend/app/job_processor.py:7-8` (import) and `:102-166` (`run_tempo_mapping`)
- Test: `backend/tests/test_job_processor.py`

**Interfaces:**
- Consumes: existing `BeatDetectionError` (from `app.beat_detection`), existing `FakeFailingBeatDetector`/`FakeSingleBeatDetector` fixtures already defined at `backend/tests/test_job_processor.py:234-241`.
- Produces: `run_tempo_mapping(...)` signature is unchanged; on beat-detection failure or an insufficient beat count it now calls `store.update(job_id, status=JobStatus.FAILED, error=<str>)` and returns, instead of ever setting `beats=None` with `status=JobStatus.TEMPO_MAPPED`.

- [ ] **Step 1: Replace the two fallback tests with failure tests, and drop the "legacy" name from the tempo-map test**

In `backend/tests/test_job_processor.py`, replace the test at line 270 (`test_run_tempo_mapping_populates_tempo_map_alongside_the_legacy_scalar_bpm`) — rename only, body unchanged:

```python
def test_run_tempo_mapping_populates_tempo_map_alongside_tempo_bpm(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeSuccessfulBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.tempo_bpm == 120.0
    assert updated.tempo_map is not None
    assert updated.tempo_map.bpm_at(0.0) == 120.0
    assert updated.tempo_map.points == (TempoPoint(source_time=0.0, bpm=120.0),)
```

Replace both tests at lines 353-392 (`test_run_tempo_mapping_falls_back_to_the_legacy_grid_when_beat_detection_fails` and `test_run_tempo_mapping_falls_back_to_the_legacy_grid_with_fewer_than_two_beats`) with:

```python
def test_run_tempo_mapping_marks_job_failed_when_beat_detection_fails(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeFailingBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "no onsets detected"


def test_run_tempo_mapping_marks_job_failed_when_fewer_than_two_beats_detected(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeSingleBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "Beat detection found only 1 beat(s); tempo mapping requires at least 2"
```

- [ ] **Step 2: Run the tests to verify the new/renamed ones fail**

Run: `cd backend && uv run pytest tests/test_job_processor.py -v`
Expected: `test_run_tempo_mapping_populates_tempo_map_alongside_tempo_bpm` fails with a collection/name error is NOT expected (it's a pure rename, should still pass against old code) — but `test_run_tempo_mapping_marks_job_failed_when_beat_detection_fails` and `test_run_tempo_mapping_marks_job_failed_when_fewer_than_two_beats_detected` FAIL, because the current implementation still sets `status=JobStatus.TEMPO_MAPPED` with `beats=None` in both cases instead of `FAILED`.

- [ ] **Step 3: Implement the fix in `run_tempo_mapping`**

In `backend/app/job_processor.py`, change the import at line 8 from:

```python
from app.beat_mapping import quantize_events, quantize_events_with_beats
```

to:

```python
from app.beat_mapping import quantize_events_with_beats
```

Replace the body of `run_tempo_mapping` (lines 102-166) with:

```python
def run_tempo_mapping(
    job_id: str,
    drums_path: Path,
    events: list[DrumEvent],
    store: JobStore,
    tempo_estimator: TempoEstimator,
    beat_detector: BeatDetector,
) -> None:
    store.update(job_id, status=JobStatus.MAPPING_TEMPO)

    try:
        bpm = tempo_estimator.estimate(drums_path)
    except TempoEstimationError as error:
        store.update(job_id, status=JobStatus.FAILED, error=str(error))
        return
    except Exception as error:  # noqa: BLE001 - guarantee the job reaches a terminal state
        store.update(job_id, status=JobStatus.FAILED, error=f"Unexpected error: {error}")
        return

    try:
        beats = beat_detector.detect(drums_path)
    except BeatDetectionError as error:
        store.update(job_id, status=JobStatus.FAILED, error=str(error))
        return
    except Exception as error:  # noqa: BLE001 - guarantee the job reaches a terminal state
        store.update(job_id, status=JobStatus.FAILED, error=f"Unexpected error: {error}")
        return

    if len(beats) < 2:
        store.update(
            job_id,
            status=JobStatus.FAILED,
            error=f"Beat detection found only {len(beats)} beat(s); tempo mapping requires at least 2",
        )
        return

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
                dataclasses.replace(event, measure=event.measure + shift)
                for event in quantized_events
            ]

    store.update(
        job_id,
        status=JobStatus.TEMPO_MAPPED,
        tempo_bpm=bpm,
        tempo_map=TempoMap.constant(bpm),
        beats=beats,
        events=quantized_events,
    )
```

(Only the beat-detection block, the `len(beats) < 2` check, and the trimmed measure-shift comment changed; the rest is byte-for-byte identical to today.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_job_processor.py -v`
Expected: all tests in the file PASS, including the two new failure tests and the renamed tempo-map test.

- [ ] **Step 5: Commit**

```bash
git add backend/app/job_processor.py backend/tests/test_job_processor.py
git commit -m "fix: fail the job instead of falling back to constant-grid quantization"
```

---

### Task 2: Delete the dead legacy quantization functions

**Files:**
- Modify: `backend/app/beat_mapping.py:1-56` (delete `quantize_events`, `musical_position_to_seconds`), `:130-135` (docstring)
- Modify: `backend/tests/test_beat_mapping.py:1-114` (delete their tests/imports), `:125-126` (comment)
- Test: `backend/tests/test_beat_mapping.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `beat_mapping.py` now exports only `quantize_events_with_beats`, `beat_anchored_position_to_seconds`, `DEFAULT_BEATS_PER_MEASURE`, `DEFAULT_SUBDIVISIONS_PER_BEAT` (plus the private `_beat_period`/`_locate`/`_absolute_beat_index` helpers). No other production file imports `quantize_events` or `musical_position_to_seconds` after Task 3 lands (verified by grep in the investigation for this plan — the only remaining production caller was `diagnostics.py`, handled in Task 3).

- [ ] **Step 1: Delete the tests for the functions being removed**

In `backend/tests/test_beat_mapping.py`, remove:
- The `import` of `musical_position_to_seconds` and `quantize_events` from the top-of-file import block (lines 3-8) — keep `beat_anchored_position_to_seconds` and `quantize_events_with_beats`.
- Every test from `test_quantize_events_assigns_measure_beat_subdivision_at_120bpm` through `test_musical_position_to_seconds_supports_different_tempo` (lines 17-113 inclusive — all `test_quantize_events_*` and `test_musical_position_to_seconds_*` tests, i.e. everything between the file's imports and the `_beat` helper).

The file's import block becomes:

```python
import pytest

from app.beat_mapping import (
    beat_anchored_position_to_seconds,
    quantize_events_with_beats,
)
from app.timing import BeatPoint
from app.transcription import DrumEvent, DrumInstrument


def _event(time: float) -> DrumEvent:
    return DrumEvent(id="e", time=time, instrument=DrumInstrument.KICK)


def _beat(time: float, measure: int, beat: int, is_downbeat: bool | None = None) -> BeatPoint:
```

i.e. everything from `import pytest` down through `_event` stays, then it jumps straight to the `_beat` helper (previously at line 116) with nothing in between.

Also update the comment directly above `CONSTANT_TEMPO_BEATS` (previously lines 125-126), since it referenced the now-deleted `quantize_events`:

```python
# Evenly spaced beats starting at t=0 - equivalent to a constant 120bpm
# grid, letting these fixtures double-check beat-anchored quantization
# against known-good numbers.
CONSTANT_TEMPO_BEATS = [
```

- [ ] **Step 2: Run the tests to confirm the remaining ones still pass**

Run: `cd backend && uv run pytest tests/test_beat_mapping.py -v`
Expected: all remaining tests PASS (they don't reference the deleted functions, so nothing should break yet — the implementation still has the dead code at this point).

- [ ] **Step 3: Delete the dead functions from the implementation**

In `backend/app/beat_mapping.py`, delete `quantize_events` (lines 10-36) and `musical_position_to_seconds` (lines 39-56) entirely, so the file starts:

```python
import dataclasses

from app.timing import BeatPoint
from app.transcription import DrumEvent

DEFAULT_BEATS_PER_MEASURE = 4
DEFAULT_SUBDIVISIONS_PER_BEAT = 4


def _beat_period(beats: list[BeatPoint], index: int) -> float:
```

(`_beat_period` and everything below it, through `beat_anchored_position_to_seconds`, is unchanged.)

Update `beat_anchored_position_to_seconds`'s docstring (currently ending with a stale reference to the just-deleted function) to:

```python
def beat_anchored_position_to_seconds(
    beats: list[BeatPoint],
    measure: int,
    beat: int,
    subdivision: int,
    beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE,
    subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT,
) -> float:
    """The exact inverse of quantize_events_with_beats: reconstructs the
    real-world time a musical position corresponds to, using the same
    local beat anchors quantization used. Used to compute quantization
    error (reconstructed time - event.time) for diagnostics."""
```

- [ ] **Step 4: Run the full backend test suite to confirm nothing else referenced the deleted functions**

Run: `cd backend && uv run pytest -v`
Expected: all tests PASS. (If anything fails with `ImportError: cannot import name 'quantize_events'`, that caller needs updating — but the investigation for this plan found only `job_processor.py` (fixed in Task 1) and `diagnostics.py`/`test_diagnostics.py` (fixed in Task 3) as callers, so this should be clean once Task 3 also lands. If this step is run before Task 3, `test_diagnostics.py` and `app/diagnostics.py` failing to import is expected — proceed to Task 3.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/beat_mapping.py backend/tests/test_beat_mapping.py
git commit -m "refactor: delete the dead constant-grid quantization functions"
```

---

### Task 3: Make event diagnostics require real beat anchors

**Files:**
- Modify: `backend/app/diagnostics.py` (whole file)
- Modify: `backend/tests/test_diagnostics.py` (whole file)
- Test: `backend/tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `quantize_events_with_beats`, `beat_anchored_position_to_seconds` from `app.beat_mapping` (Task 2's surviving exports); `BeatPoint` from `app.timing`.
- Produces: `build_event_diagnostics(raw_events, quantized_events, tempo_bpm, beats, beats_per_measure=..., subdivisions_per_beat=...) -> list[EventDiagnostic]` — `beats: list[BeatPoint]` is now a required positional-or-keyword parameter (previously `beats: list[BeatPoint] | None = None`). `EventDiagnostic`'s fields are unchanged. Task 4's `api/jobs.py` call site passes `beats=job.beats`.

- [ ] **Step 1: Rewrite the failing test file to use beat-anchored fixtures**

Replace the entire contents of `backend/tests/test_diagnostics.py` with:

```python
import pytest

from app.beat_mapping import quantize_events_with_beats
from app.diagnostics import build_event_diagnostics
from app.timing import BeatPoint
from app.transcription import DrumEvent, DrumInstrument


def _beat(time: float, measure: int, beat: int) -> BeatPoint:
    return BeatPoint(source_time=time, measure=measure, beat=beat, is_downbeat=beat == 1)


# Evenly spaced beats starting at t=0 - equivalent to a constant 120bpm
# grid, so expected quantized_time/error values below are easy to reason
# about by hand.
CONSTANT_TEMPO_BEATS = [
    _beat(0.0, 1, 1),
    _beat(0.5, 1, 2),
    _beat(1.0, 1, 3),
    _beat(1.5, 1, 4),
    _beat(2.0, 2, 1),
]

OFFSET_BEATS = [
    BeatPoint(source_time=2.5, measure=1, beat=1, is_downbeat=True),
    BeatPoint(source_time=3.0, measure=1, beat=2, is_downbeat=False),
    BeatPoint(source_time=3.5, measure=1, beat=3, is_downbeat=False),
]


def test_build_event_diagnostics_traces_each_quantized_event_back_to_its_raw_source():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert diagnostics[0].event_id == "e1"
    assert diagnostics[0].source_time == 0.13
    assert diagnostics[0].instrument == DrumInstrument.SNARE


def test_build_event_diagnostics_reports_the_quantization_error_in_seconds():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    # 0.13s quantizes to subdivision 1 (0.125s) on the 120bpm-equivalent grid.
    assert diagnostics[0].quantized_time == pytest.approx(0.125)
    assert diagnostics[0].quantization_error_seconds == pytest.approx(0.125 - 0.13)


def test_build_event_diagnostics_reports_zero_error_for_perfectly_grid_aligned_hits():
    raw_events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert diagnostics[0].quantization_error_seconds == pytest.approx(0.0, abs=1e-9)


def test_build_event_diagnostics_preserves_order_and_count():
    raw_events = [
        DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK),
        DrumEvent(id="e2", time=0.5, instrument=DrumInstrument.SNARE),
    ]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert [d.event_id for d in diagnostics] == ["e1", "e2"]


def test_build_event_diagnostics_passes_through_velocity_and_confidence():
    raw_events = [
        DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK, velocity=0.8, confidence=0.9)
    ]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert diagnostics[0].velocity == 0.8
    assert diagnostics[0].confidence == 0.9


def test_build_event_diagnostics_leaves_quantized_fields_none_when_no_matching_quantized_event():
    raw_events = [DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK)]

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events=[], tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert diagnostics[0].measure is None
    assert diagnostics[0].quantized_time is None
    assert diagnostics[0].quantization_error_seconds is None


def test_build_event_diagnostics_does_not_mutate_its_inputs():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)
    raw_events_before = list(raw_events)
    quantized_events_before = list(quantized_events)

    build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert raw_events == raw_events_before
    assert quantized_events == quantized_events_before


def test_build_event_diagnostics_reconstructs_quantized_time_using_beat_anchors():
    raw_events = [DrumEvent(id="e1", time=2.5, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events_with_beats(raw_events, OFFSET_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=OFFSET_BEATS
    )

    # An event exactly at the first real beat (2.5s) must reconstruct back
    # to exactly 2.5s via the beat-anchored inverse - a t=0-anchored
    # reconstruction would instead return 0.0s, since it would assume
    # measure 1 beat 1 is at t=0.
    assert diagnostics[0].quantized_time == pytest.approx(2.5)
    assert diagnostics[0].quantization_error_seconds == pytest.approx(0.0, abs=1e-9)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_diagnostics.py -v`
Expected: FAIL — either a collection error (`build_event_diagnostics() missing 1 required positional argument: 'beats'` won't happen yet since `beats` still defaults to `None` in the current implementation) or, more likely, tests pass by coincidence for the `CONSTANT_TEMPO_BEATS` cases (current code already supports a `beats` kwarg) — the real signal is that this step's job is just to confirm the file is syntactically valid and importable before changing production code. Confirm no `ImportError`/`AttributeError` at collection time.

- [ ] **Step 3: Implement the fix in `diagnostics.py`**

Replace the entire contents of `backend/app/diagnostics.py` with:

```python
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
                tempo_bpm=tempo_bpm,
                measure=measure,
                beat=beat,
                subdivision=subdivision,
                quantized_time=quantized_time,
                quantization_error_seconds=quantization_error_seconds,
            )
        )

    return diagnostics
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_diagnostics.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/diagnostics.py backend/tests/test_diagnostics.py
git commit -m "refactor: require real beat anchors for event diagnostics"
```

---

### Task 4: Guard the diagnostics API on missing beats, and clean up stale docstrings

**Files:**
- Modify: `backend/app/api/jobs.py:371-377`
- Modify: `backend/app/timing.py:68-74`
- Modify: `backend/tests/test_jobs_api.py` (add one test)
- Test: `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `build_event_diagnostics` now requires `beats: list[BeatPoint]` (Task 3); `store.update(job_id, **changes)` (existing `JobStore` API, unchanged).
- Produces: `GET /api/jobs/{job_id}/diagnostics` returns 409 if `job.beats` is `None`, in addition to the existing checks — this closes the type gap left by `build_event_diagnostics`'s `beats` parameter no longer accepting `None`.

- [ ] **Step 1: Write the failing regression test**

Add to `backend/tests/test_jobs_api.py`, after `test_get_diagnostics_returns_409_when_job_not_yet_tempo_mapped` (around line 280):

```python
def test_get_diagnostics_returns_409_when_beats_missing_even_though_tempo_bpm_is_set(
    isolated_dependencies,
):
    store = isolated_dependencies
    job_id = _create_job_through_to_tempo_mapped()
    store.update(job_id, beats=None)

    response = client.get(f"/api/jobs/{job_id}/diagnostics")

    assert response.status_code == 409
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_jobs_api.py::test_get_diagnostics_returns_409_when_beats_missing_even_though_tempo_bpm_is_set -v`
Expected: FAIL — the endpoint currently calls `build_event_diagnostics(..., beats=None)`, which either 500s (TypeError from `beat_anchored_position_to_seconds` inside, since Task 3 removed the `None`-tolerant branch) rather than returning a clean 409.

- [ ] **Step 3: Implement the guard**

In `backend/app/api/jobs.py`, change the check inside `get_job_diagnostics` (currently at line 371):

```python
    if job.raw_events is None or job.events is None or job.tempo_bpm is None:
```

to:

```python
    if (
        job.raw_events is None
        or job.events is None
        or job.tempo_bpm is None
        or job.beats is None
    ):
```

The call at line 377 (`build_event_diagnostics(job.raw_events, job.events, job.tempo_bpm, beats=job.beats)`) is unchanged — it's now guaranteed `job.beats` is non-`None` by the guard above.

- [ ] **Step 4: Run the test to verify it passes, then run the full API test file**

Run: `cd backend && uv run pytest tests/test_jobs_api.py -v`
Expected: all tests PASS, including the new one.

- [ ] **Step 5: Clean up the stale `TempoMap.constant` docstring**

In `backend/app/timing.py`, replace the `constant` classmethod's docstring (lines 68-74):

```python
    @classmethod
    def constant(cls, bpm: float) -> "TempoMap":
        """A single-point TempoMap anchored at t=0 - the bridge
        representation for the legacy scalar-BPM pipeline, used until real
        tempo-change detection (TECHNICAL_DEBT.md, "Tempo estimation
        disagrees with DrumScript's own estimate") replaces it."""
        return cls(points=(TempoPoint(source_time=0.0, bpm=bpm),))
```

with:

```python
    @classmethod
    def constant(cls, bpm: float) -> "TempoMap":
        """A single-point TempoMap holding one estimated tempo value for
        the whole song - informational display/diagnostics metadata only.
        Quantization never reads this; it always uses detected beat anchors
        (see app.beat_mapping.quantize_events_with_beats). Real
        tempo-change detection (TECHNICAL_DEBT.md, "Tempo estimation
        disagrees with DrumScript's own estimate") would replace this with
        a true multi-point TempoMap."""
        return cls(points=(TempoPoint(source_time=0.0, bpm=bpm),))
```

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && uv run pytest -v`
Expected: all tests PASS (this is the final confirmation that Tasks 1-4 together leave the whole suite green).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/jobs.py backend/app/timing.py backend/tests/test_jobs_api.py
git commit -m "fix: guard diagnostics endpoint against missing beats; clean up stale docstring"
```

---

### Task 5: Verify, then push and open the PR

**Files:** none (verification + git/GitHub only)

- [ ] **Step 1: Run the full backend suite with coverage**

Run: `cd backend && uv run pytest --cov=app -v`
Expected: all tests PASS.

- [ ] **Step 2: Grep-verify no production code still references the deleted functions or the "legacy" framing**

Run: `cd backend && grep -rn "quantize_events(" app/ ; grep -rn "musical_position_to_seconds" app/`
Expected: no matches in `app/` (only `quantize_events_with_beats` should match the first grep, if anything).

- [ ] **Step 3: Confirm no frontend files changed**

Run: `git diff --stat main -- frontend/`
Expected: empty output — this issue is backend-only.

- [ ] **Step 4: Push the branch and open the PR**

```bash
git push -u origin v1-011_remove-legacy-scalar-bpm
gh pr create --title "V1-011: Remove legacy scalar-BPM timing path" --body "$(cat <<'EOF'
## Summary
- `run_tempo_mapping` no longer falls back to constant-grid quantization when beat detection fails or finds fewer than 2 beats - the job now fails explicitly with a clear error instead of silently reconstructing timing from one BPM.
- Deleted the now-dead `quantize_events`/`musical_position_to_seconds` constant-grid functions from `beat_mapping.py`.
- `build_event_diagnostics` now requires real `beats` and always reconstructs `quantized_time` via `beat_anchored_position_to_seconds`; the diagnostics API endpoint gained a matching `job.beats is None` guard.
- Cleaned up docstrings/comments that described `TempoMap.constant`/the measure-shift logic as bridging a "legacy scalar-BPM pipeline", since that pipeline is now gone. `tempo_bpm`/`TempoMap.constant` remain as informational display metadata only - they no longer drive any quantization math.

Closes #44. Closes Epic 2 (#29): every timing consumer is now driven by `TempoMap`/`BeatPoint`, satisfying the exit gate.

## Test plan
- [x] `cd backend && uv run pytest --cov=app -v` - full suite green
- [x] New regression tests: job fails (not silently degrades) when beat detection fails or finds <2 beats; diagnostics API 409s if `beats` is ever missing despite `tempo_bpm` being set
- [x] Grep-verified no remaining production references to the deleted functions
- [x] No frontend files touched

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Report to the user and stop**

Summarize the change, link the PR, and wait for merge confirmation per this repo's standing workflow (`docs/superpowers/plans` convention + `feedback-branch-cleanup`/`project-drumscore-issue-workflow` memory) — do not proceed to #44's follow-ups or any other issue until the user confirms the PR is merged.

---

## Self-Review Notes

- **Spec coverage:** "No production consumer reconstructs timing from one BPM" → Task 1 (job_processor) + Task 3 (diagnostics) remove the two remaining call sites. "compatibility code is removed/deprecated intentionally" → Task 2 deletes it outright (not just deprecated) with an explicit commit documenting why. "tests and docs use TempoMap/BeatPoint" → Tasks 1-4 rewrite every affected test to build fixtures from `BeatPoint`s; Task 4 updates the one stale docstring. "Epic 2 exit gate passes" → verified by Task 5's full-suite run; no behavior change to the beats-present success path (already beat-anchored since V1-010).
- **Placeholder scan:** no TBD/TODO markers; every step has literal code or an exact shell command.
- **Type consistency:** `build_event_diagnostics(raw_events, quantized_events, tempo_bpm, beats, beats_per_measure=..., subdivisions_per_beat=...)` signature is identical across Task 3's implementation and every call site touched in Task 3/4 (`beats=` passed as keyword everywhere, matching the existing call convention in `api/jobs.py`).
