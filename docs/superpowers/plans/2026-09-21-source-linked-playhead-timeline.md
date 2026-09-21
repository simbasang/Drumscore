# Source-Linked Playhead Timeline (V1-010) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the beat-anchored quantization built in V1-009 (`quantize_events_with_beats`, `beat_anchored_position_to_seconds`) into the live backend pipeline and diagnostics, and migrate the frontend playhead/score timeline off `computeSlotTimeSeconds`/scalar-BPM reconstruction onto each `DrumEvent`'s own immutable source timestamp — so rendered playhead position no longer accumulates constant-tempo-grid drift over a full song.

**Architecture:** Backend: `run_tempo_mapping` gains a `beat_detector` dependency; it detects real beats via `LibrosaBeatDetector`, quantizes events with `quantize_events_with_beats` when at least two beats are found, and falls back to the existing constant-grid `quantize_events` otherwise (the "introduce beside, migrate consumers, remove later" pattern `docs/ARCHITECTURE_V1.md`'s Migration section already established for V1-008/V1-009 — full legacy removal is V1-011/#44, not this issue). `diagnostics.py` mirrors the same fallback using `beat_anchored_position_to_seconds`. Frontend: `buildMeasures` (already the single place that groups `DrumEvent`s into rendered slots) additionally carries each slot's real source timestamps forward on `NoteSpec`; `DrumScore` builds its playhead timeline from those real timestamps instead of recomputing time from a measure/beat/subdivision/BPM formula, and stops requiring a `tempoBpm` prop entirely. `computeSlotTimeSeconds` (frontend-only, single consumer, that consumer removed in this same issue) is deleted rather than deprecated, since nothing else uses it — unlike the backend's `quantize_events`, which stays until #44 because it remains a live fallback.

**Tech Stack:** Python 3.13/pytest (backend), TypeScript/Jest+RTL (frontend) — existing stacks, no new dependencies.

**Spec:** GitHub issue #43 (V1-010), part of EPIC 2 (#29). Builds on `BeatPoint`/`TempoMap` (#39), `LibrosaBeatDetector` (#40), and `quantize_events_with_beats`/`beat_anchored_position_to_seconds` (#42, see `docs/superpowers/plans/2026-09-21-beat-anchored-quantization.md`, whose "Explicitly out of scope" section names this issue as the place these get wired into the live pipeline).

## Global Constraints

- `event.time` (sourceTime) must never be recomputed, overwritten, or approximated anywhere in this change — only read. This applies on both backend (`DrumEvent.time`) and frontend (`AnalysisEvent.time`).
- Do not modify `quantize_events`, `musical_position_to_seconds`, or `quantize_events_with_beats`/`beat_anchored_position_to_seconds` themselves — they are already correct and tested; this plan only wires the beat-anchored ones in as the primary path with the constant-grid ones kept as a fallback.
- Do not remove `quantize_events`/`musical_position_to_seconds` from the backend (that's #44/V1-011, after this issue proves the new path owns the pipeline).
- Every existing passing test must still pass after this change unless a task explicitly says a test's expectations change (and why).
- Keep `interpolatePlayheadX`/`computeAutoScrollLeft` in `frontend/lib/notation/timeline.ts` untouched — they already operate generically over `TimelinePoint[]` regardless of how `time` was derived; only how `DrumScore` builds that array changes.

---

### Task 1: `Job` gains a `beats` field

**Files:**
- Modify: `backend/app/jobs.py`
- Test: `backend/tests/test_jobs.py`

**Interfaces:**
- Consumes: `app.timing.BeatPoint` (already exists).
- Produces: `Job.beats: list[BeatPoint] | None` (default `None`), settable via the existing `JobStore.update(job_id, **changes)`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_jobs.py`:

```python
from app.timing import BeatPoint


def test_job_beats_defaults_to_none():
    store = JobStore()

    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    assert job.beats is None


def test_update_can_set_beats():
    store = JobStore()
    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")
    beats = [
        BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True),
        BeatPoint(source_time=0.5, measure=1, beat=2, is_downbeat=False),
    ]

    updated = store.update(job.id, beats=beats)

    assert updated.beats == beats
    assert store.get(job.id).beats == beats
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_jobs.py -v -k beats`
Expected: FAIL — `Job` has no field/attribute `beats`.

- [ ] **Step 3: Implement**

In `backend/app/jobs.py`, change the import and add the field:

```python
from app.timing import BeatPoint, TempoMap
```

```python
@dataclass(frozen=True)
class Job:
    id: str
    url: str
    status: JobStatus
    created_at: datetime
    audio_path: str | None = None
    drums_path: str | None = None
    accompaniment_path: str | None = None
    events: list[DrumEvent] | None = None
    raw_events: list[DrumEvent] | None = None
    tempo_bpm: float | None = None
    tempo_map: TempoMap | None = None
    beats: list[BeatPoint] | None = None
    error: str | None = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_jobs.py -v`
Expected: PASS, all tests including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs.py backend/tests/test_jobs.py
git commit -m "feat: add beats field to Job for beat-anchored quantization"
```

---

### Task 2: Wire beat-anchored quantization into `run_tempo_mapping`/`run_pipeline`

**Files:**
- Modify: `backend/app/job_processor.py`
- Test: `backend/tests/test_job_processor.py`

**Interfaces:**
- Consumes: `app.beat_detection.BeatDetector` (protocol, `detect(audio_path: Path) -> list[BeatPoint]`), `app.beat_detection.BeatDetectionError`, `app.beat_mapping.quantize_events_with_beats`, `app.timing.BeatPoint` (all exist already).
- Produces: `run_tempo_mapping(job_id: str, drums_path: Path, events: list[DrumEvent], store: JobStore, tempo_estimator: TempoEstimator, beat_detector: BeatDetector) -> None` (new `beat_detector` parameter, inserted last). `run_pipeline(..., tempo_estimator: TempoEstimator, beat_detector: BeatDetector, storage_dir: Path) -> None` (new `beat_detector` parameter inserted between `tempo_estimator` and `storage_dir`).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_job_processor.py`, near the existing `FakeSuccessfulTempoEstimator`/`FakeFailingTempoEstimator`/`FakeCrashingTempoEstimator` classes:

```python
from app.beat_detection import BeatDetectionError
from app.timing import BeatPoint


class FakeSuccessfulBeatDetector:
    def detect(self, audio_path):
        return [
            BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True),
            BeatPoint(source_time=0.5, measure=1, beat=2, is_downbeat=False),
            BeatPoint(source_time=1.0, measure=1, beat=3, is_downbeat=False),
            BeatPoint(source_time=1.5, measure=1, beat=4, is_downbeat=False),
        ]


class FakeOffsetBeatDetector:
    """Beats whose first point is NOT at t=0 - the scenario that
    distinguishes beat-anchored quantization from the legacy t=0 grid."""

    def detect(self, audio_path):
        return [
            BeatPoint(source_time=2.5, measure=1, beat=1, is_downbeat=True),
            BeatPoint(source_time=3.0, measure=1, beat=2, is_downbeat=False),
            BeatPoint(source_time=3.5, measure=1, beat=3, is_downbeat=False),
        ]


class FakeSingleBeatDetector:
    def detect(self, audio_path):
        return [BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True)]


class FakeFailingBeatDetector:
    def detect(self, audio_path):
        raise BeatDetectionError("no onsets detected")


class FakeCrashingBeatDetector:
    def detect(self, audio_path):
        raise RuntimeError("native decode failure")
```

Then append these test functions:

```python
def test_run_tempo_mapping_quantizes_with_beats_and_stores_them(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=2.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeOffsetBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.TEMPO_MAPPED
    assert updated.beats == FakeOffsetBeatDetector().detect(None)
    # The whole point of beat-anchoring: an event exactly at the first real
    # beat's time (2.5s, not 0s) quantizes to beat 1 - the legacy t=0 grid
    # would instead have placed 2.5s deep into several earlier measures.
    assert updated.events[0].measure == 1
    assert updated.events[0].beat == 1
    assert updated.events[0].subdivision == 0
    assert updated.events[0].time == 2.5


def test_run_tempo_mapping_falls_back_to_the_legacy_grid_when_beat_detection_fails(tmp_path, source):
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
    assert updated.status == JobStatus.TEMPO_MAPPED
    assert updated.beats is None
    # 0.5s at the fallback 120bpm constant grid -> beat 2, matching
    # quantize_events(events, bpm=120.0) exactly.
    assert updated.events[0].beat == 2


def test_run_tempo_mapping_falls_back_to_the_legacy_grid_with_fewer_than_two_beats(tmp_path, source):
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
    assert updated.status == JobStatus.TEMPO_MAPPED
    assert updated.beats is None
    assert updated.events[0].beat == 2


def test_run_tempo_mapping_marks_job_failed_on_unexpected_beat_detector_exception(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeCrashingBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert "native decode failure" in updated.error
```

Now update every existing call site that invokes `run_tempo_mapping` or `run_pipeline` to pass a beat detector, since both signatures gain a new required parameter. For every one of them, add `FakeSuccessfulBeatDetector()` as the argument immediately after the existing tempo-estimator argument (positionally: `run_tempo_mapping(job_id, drums_path, events, store, tempo_estimator, beat_detector)`; `run_pipeline(job_id, source, store, extractor, separator, transcriber, tempo_estimator, beat_detector, storage_dir)`). Apply this to each of the following existing test functions in `backend/tests/test_job_processor.py`:

- `test_run_tempo_mapping_marks_job_tempo_mapped_on_success`
- `test_run_tempo_mapping_populates_tempo_map_alongside_the_legacy_scalar_bpm`
- `test_run_tempo_mapping_marks_job_failed_on_error` (tempo estimator still fails first, so beat detector is never reached, but the call still needs the extra positional argument to type-check)
- `test_run_tempo_mapping_marks_job_failed_on_unexpected_exception` (same — tempo estimator crashes first)
- `test_run_tempo_mapping_does_not_modify_raw_events`
- `test_run_pipeline_preserves_raw_events_separately_from_quantized_events`
- `test_run_pipeline_runs_all_four_steps_on_success`
- `test_run_pipeline_stops_before_separation_when_extraction_fails`
- `test_run_pipeline_stops_before_transcription_when_separation_fails`
- `test_run_pipeline_stops_before_tempo_mapping_when_transcription_fails`
- `test_run_pipeline_resumes_from_stem_separation_when_audio_already_downloaded`
- `test_run_pipeline_resumes_from_transcription_when_stems_already_separated`
- `test_run_pipeline_resumes_from_tempo_mapping_when_events_already_transcribed`

For each, insert `FakeSuccessfulBeatDetector(),` as the new argument right after the existing `FakeSuccessfulTempoEstimator()`/`FakeFailingTempoEstimator()`/`FakeCrashingTempoEstimator()`/`SpyTempoEstimator()` argument (before `tmp_path` for `run_tempo_mapping` calls, before the final `tmp_path` for `run_pipeline` calls).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_job_processor.py -v`
Expected: FAIL — `TypeError: run_tempo_mapping() takes 5 positional arguments but 6 were given` (and equivalent for `run_pipeline`), since the implementation doesn't accept `beat_detector` yet.

- [ ] **Step 3: Implement**

In `backend/app/job_processor.py`, update the imports:

```python
from app.beat_detection import BeatDetectionError, BeatDetector
from app.beat_mapping import quantize_events, quantize_events_with_beats
from app.timing import BeatPoint, TempoMap
```

Replace `run_tempo_mapping` with:

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

    beats: list[BeatPoint] | None = None
    try:
        detected_beats = beat_detector.detect(drums_path)
        if len(detected_beats) >= 2:
            beats = detected_beats
    except BeatDetectionError:
        # A known, expected failure mode (e.g. no onsets detected on very
        # quiet/short audio) - fall back to the constant-grid path below
        # rather than failing the whole job, matching the "introduce beside,
        # migrate consumers" pattern in docs/ARCHITECTURE_V1.md's Migration
        # section. Full removal of this fallback is #44/V1-011's job.
        beats = None
    except Exception as error:  # noqa: BLE001 - guarantee the job reaches a terminal state
        store.update(job_id, status=JobStatus.FAILED, error=f"Unexpected error: {error}")
        return

    quantized_events = (
        quantize_events_with_beats(events, beats)
        if beats is not None
        else quantize_events(events, bpm)
    )

    store.update(
        job_id,
        status=JobStatus.TEMPO_MAPPED,
        tempo_bpm=bpm,
        tempo_map=TempoMap.constant(bpm),
        beats=beats,
        events=quantized_events,
    )
```

Update `run_pipeline`'s signature and final call:

```python
def run_pipeline(
    job_id: str,
    source: ParsedSource,
    store: JobStore,
    extractor: AudioExtractor,
    separator: StemSeparator,
    transcriber: DrumTranscriber,
    tempo_estimator: TempoEstimator,
    beat_detector: BeatDetector,
    storage_dir: Path,
) -> None:
    """Runs each pipeline step in order, skipping any step whose output is
    already present on the job. This lets a retry resume from wherever a
    previous run left off instead of starting over from scratch."""
    job_dir = storage_dir / job_id
    job = store.get(job_id)

    audio_path = Path(job.audio_path) if job.audio_path else None
    if audio_path is None:
        audio_path = run_audio_extraction(job_id, source, store, extractor, storage_dir)
        if audio_path is None:
            return

    drums_path = Path(job.drums_path) if job.drums_path else None
    if drums_path is None:
        drums_path = run_stem_separation(job_id, audio_path, store, separator, job_dir)
        if drums_path is None:
            return

    events = job.events if job.events else None
    if events is None:
        events = run_transcription(job_id, drums_path, store, transcriber)
        if events is None:
            return

    run_tempo_mapping(job_id, drums_path, events, store, tempo_estimator, beat_detector)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_job_processor.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: FAIL only in `tests/test_jobs_api.py` (Task 4 fixes that) — every other file passes.

- [ ] **Step 6: Commit**

```bash
git add backend/app/job_processor.py backend/tests/test_job_processor.py
git commit -m "feat: wire beat-anchored quantization into the tempo-mapping pipeline step"
```

---

### Task 3: `diagnostics.py` reconstructs quantized time from beats when available

**Files:**
- Modify: `backend/app/diagnostics.py`
- Test: `backend/tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `app.beat_mapping.beat_anchored_position_to_seconds` (exists already).
- Produces: `build_event_diagnostics(raw_events, quantized_events, tempo_bpm, beats: list[BeatPoint] | None = None, beats_per_measure=DEFAULT_BEATS_PER_MEASURE, subdivisions_per_beat=DEFAULT_SUBDIVISIONS_PER_BEAT) -> list[EventDiagnostic]` (new optional `beats` parameter; existing callers that omit it keep today's exact behavior).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_diagnostics.py`:

```python
from app.beat_mapping import quantize_events_with_beats
from app.timing import BeatPoint

OFFSET_BEATS = [
    BeatPoint(source_time=2.5, measure=1, beat=1, is_downbeat=True),
    BeatPoint(source_time=3.0, measure=1, beat=2, is_downbeat=False),
    BeatPoint(source_time=3.5, measure=1, beat=3, is_downbeat=False),
]


def test_build_event_diagnostics_uses_beat_anchored_reconstruction_when_beats_are_given():
    raw_events = [DrumEvent(id="e1", time=2.5, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events_with_beats(raw_events, OFFSET_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=OFFSET_BEATS
    )

    # An event exactly at the first real beat (2.5s) must reconstruct back
    # to exactly 2.5s via the beat-anchored inverse - the legacy
    # musical_position_to_seconds(measure=1, beat=1, subdivision=0, bpm=120)
    # would instead return 0.0s, since it assumes measure 1 beat 1 is at t=0.
    assert diagnostics[0].quantized_time == pytest.approx(2.5)
    assert diagnostics[0].quantization_error_seconds == pytest.approx(0.0, abs=1e-9)


def test_build_event_diagnostics_falls_back_to_the_legacy_grid_when_beats_is_none():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events(raw_events, bpm=120.0)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=None
    )

    assert diagnostics[0].quantized_time == pytest.approx(0.125)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_diagnostics.py -v -k beat_anchored`
Expected: FAIL — `build_event_diagnostics() got an unexpected keyword argument 'beats'`.

- [ ] **Step 3: Implement**

In `backend/app/diagnostics.py`, update the import and function:

```python
import dataclasses

from app.beat_mapping import (
    DEFAULT_BEATS_PER_MEASURE,
    DEFAULT_SUBDIVISIONS_PER_BEAT,
    beat_anchored_position_to_seconds,
    musical_position_to_seconds,
)
from app.timing import BeatPoint
from app.transcription import DrumEvent, DrumInstrument
```

```python
def build_event_diagnostics(
    raw_events: list[DrumEvent],
    quantized_events: list[DrumEvent],
    tempo_bpm: float,
    beats: list[BeatPoint] | None = None,
    beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE,
    subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT,
) -> list[EventDiagnostic]:
    """Pairs each raw transcriber event with its quantized counterpart (by
    shared id) and reports how far quantization moved it from its original
    source timestamp. Read-only: never mutates its inputs or the pipeline's
    stored events."""
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
            if beats is not None and len(beats) >= 2:
                quantized_time = beat_anchored_position_to_seconds(
                    beats, measure, beat, subdivision, beats_per_measure, subdivisions_per_beat
                )
            else:
                quantized_time = musical_position_to_seconds(
                    measure, beat, subdivision, tempo_bpm, beats_per_measure, subdivisions_per_beat
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
Expected: PASS, all tests (the pre-existing ones call `build_event_diagnostics` without `beats`, which defaults to `None` and preserves today's exact output).

- [ ] **Step 5: Commit**

```bash
git add backend/app/diagnostics.py backend/tests/test_diagnostics.py
git commit -m "feat: reconstruct diagnostic quantized time from beat anchors when available"
```

---

### Task 4: Wire the beat detector dependency through the API layer

**Files:**
- Modify: `backend/app/api/jobs.py`
- Test: `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `app.librosa_beat_detector.LibrosaBeatDetector` (already implements `BeatDetector`).
- Produces: `get_beat_detector() -> BeatDetector` (new FastAPI dependency getter, same pattern as `get_tempo_estimator`).

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_jobs_api.py`, update the import block to add `get_beat_detector`:

```python
from app.api.jobs import (
    BeatPointResponse,
    TempoMapResponse,
    TempoPointResponse,
    get_audio_extractor,
    get_beat_detector,
    get_job_store,
    get_stem_separator,
    get_storage_dir,
    get_tempo_estimator,
    get_transcriber,
)
```

Add a fake beat detector near the other fakes:

```python
from app.timing import BeatPoint, TempoMap, TempoPoint


class FakeBeatDetector:
    def detect(self, audio_path):
        return [
            BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True),
            BeatPoint(source_time=0.5, measure=1, beat=2, is_downbeat=False),
            BeatPoint(source_time=1.0, measure=1, beat=3, is_downbeat=False),
            BeatPoint(source_time=1.5, measure=1, beat=4, is_downbeat=False),
        ]
```

Update the `isolated_dependencies` fixture to override and clean up the new dependency:

```python
@pytest.fixture(autouse=True)
def isolated_dependencies(tmp_path):
    store = JobStore()
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_audio_extractor] = lambda: FakeAudioExtractor()
    app.dependency_overrides[get_stem_separator] = lambda: FakeStemSeparator()
    app.dependency_overrides[get_transcriber] = lambda: FakeTranscriber()
    app.dependency_overrides[get_tempo_estimator] = lambda: FakeTempoEstimator()
    app.dependency_overrides[get_beat_detector] = lambda: FakeBeatDetector()
    app.dependency_overrides[get_storage_dir] = lambda: tmp_path
    yield store
    app.dependency_overrides.pop(get_job_store, None)
    app.dependency_overrides.pop(get_audio_extractor, None)
    app.dependency_overrides.pop(get_stem_separator, None)
    app.dependency_overrides.pop(get_transcriber, None)
    app.dependency_overrides.pop(get_tempo_estimator, None)
    app.dependency_overrides.pop(get_beat_detector, None)
    app.dependency_overrides.pop(get_storage_dir, None)
```

Add a new test verifying the wiring end to end:

```python
def test_get_diagnostics_uses_beat_anchored_reconstruction():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/diagnostics")

    body = response.json()
    # FakeTranscriber's events are both at time=0.5, exactly FakeBeatDetector's
    # second beat point - the beat-anchored reconstruction must therefore
    # round-trip to exactly 0.5s of error, proving the live endpoint is
    # using beat_anchored_position_to_seconds, not the legacy grid.
    assert body["events"][0]["quantization_error_seconds"] == pytest.approx(0.0, abs=1e-9)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_jobs_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_beat_detector'` (and, once that's fixed by Step 3, the fake-audio-bytes-to-real-`LibrosaBeatDetector` crash without the fixture override, and then the new reconstruction test failing until Step 3's diagnostics wiring lands).

- [ ] **Step 3: Implement**

In `backend/app/api/jobs.py`, add the import and module-level instance/getter, following the exact pattern `get_tempo_estimator` already uses:

```python
from app.beat_detection import BeatDetector
from app.librosa_beat_detector import LibrosaBeatDetector
```

```python
_beat_detector = LibrosaBeatDetector()
```

```python
def get_beat_detector() -> BeatDetector:
    return _beat_detector
```

Thread `beat_detector` through `create_job`:

```python
@router.post("", response_model=JobResponse, status_code=201)
def create_job(
    request: CreateJobRequest,
    background_tasks: BackgroundTasks,
    store: JobStore = Depends(get_job_store),
    validator: MediaSourceValidator = Depends(get_source_validator),
    extractor: AudioExtractor = Depends(get_audio_extractor),
    separator: StemSeparator = Depends(get_stem_separator),
    transcriber: DrumTranscriber = Depends(get_transcriber),
    tempo_estimator: TempoEstimator = Depends(get_tempo_estimator),
    beat_detector: BeatDetector = Depends(get_beat_detector),
    storage_dir: Path = Depends(get_storage_dir),
    limiter: PipelineConcurrencyLimiter = Depends(get_pipeline_limiter),
) -> JobResponse:
    try:
        source = validator.parse(request.url)
    except InvalidSourceUrlError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    cleanup_old_jobs(store, storage_dir)
    job = store.create(url=request.url)
    background_tasks.add_task(
        limiter.run,
        run_pipeline,
        job.id,
        source,
        store,
        extractor,
        separator,
        transcriber,
        tempo_estimator,
        beat_detector,
        storage_dir,
    )
    return JobResponse.from_job(job)
```

Apply the same two changes (add the `beat_detector: BeatDetector = Depends(get_beat_detector)` parameter, and insert `beat_detector` into the `background_tasks.add_task(...)` call in the same position) to `retry_job`.

Finally, update `get_job_diagnostics` to pass the job's beats through:

```python
    diagnostics = build_event_diagnostics(job.raw_events, job.events, job.tempo_bpm, beats=job.beats)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_jobs_api.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS, no regressions anywhere in the backend.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/jobs.py backend/tests/test_jobs_api.py
git commit -m "feat: wire beat detector dependency through the jobs API"
```

---

### Task 5: `buildMeasures` carries each slot's real source timestamps

**Files:**
- Modify: `frontend/lib/notation/buildScore.ts`
- Test: `frontend/lib/notation/__tests__/buildScore.test.ts`

**Interfaces:**
- Produces: `NoteSpec.sourceTimes: number[]` (new field — the immutable original `AnalysisEvent.time` of every event grouped into that slot, in the order they were grouped).

- [ ] **Step 1: Write the failing tests**

In `frontend/lib/notation/__tests__/buildScore.test.ts`, update the four existing `toEqual` assertions on note slots to include `sourceTimes` (the default `event()` helper's `time` is `0`, so a single default event yields `sourceTimes: [0]`):

Replace this block (around line 37-43):
```ts
    expect(measures[0]).toEqual([
      { type: "note", keys: ["f/4"], articulations: [], duration: "16", startSixteenth: 0, sourceTimes: [0] },
      { type: "rest", duration: "16", startSixteenth: 1 },
      { type: "rest", duration: "8", startSixteenth: 2 },
      { type: "rest", duration: "4", startSixteenth: 4 },
      { type: "rest", duration: "2", startSixteenth: 8 },
    ]);
```

Replace this block (around line 52-58, two simultaneous default-time events -> `sourceTimes: [0, 0]`):
```ts
    expect(measures[0][0]).toEqual({
      type: "note",
      keys: ["f/4", "g/5/x2"],
      articulations: [],
      duration: "16",
      startSixteenth: 0,
      sourceTimes: [0, 0],
    });
```

Replace this block (around line 64-70):
```ts
    expect(measures[0][0]).toEqual({
      type: "note",
      keys: ["g/5/x2"],
      articulations: ["ah"],
      duration: "16",
      startSixteenth: 0,
      sourceTimes: [0],
    });
```

Replace this block (around line 87-94):
```ts
    expect(noteSlot).toEqual({
      type: "note",
      keys: ["c/5"],
      articulations: [],
      duration: "16",
      // beat 2, subdivision 1 -> sixteenth position (2-1)*4 + 1 = 5
      startSixteenth: 5,
      sourceTimes: [0],
    });
```

Add one new test proving real, non-default timestamps survive grouping:

```ts
  it("should carry each slot's original event source times through unmodified", () => {
    const measures = buildMeasures([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 12.34 }),
      event({ id: "b", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 12.36 }),
    ]);

    const noteSlot = measures[0][0];
    expect(noteSlot.type).toBe("note");
    expect((noteSlot as { sourceTimes: number[] }).sourceTimes).toEqual([12.34, 12.36]);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx jest lib/notation/__tests__/buildScore.test.ts`
Expected: FAIL — actual `NoteSpec` objects are missing the `sourceTimes` property the updated assertions now expect.

- [ ] **Step 3: Implement**

In `frontend/lib/notation/buildScore.ts`, update `NoteSpec` and `buildNoteSpec`:

```ts
export interface NoteSpec {
  type: "note";
  keys: string[];
  articulations: string[];
  duration: string;
  startSixteenth: number;
  sourceTimes: number[];
}
```

```ts
function buildNoteSpec(slotEvents: AnalysisEvent[], startSixteenth: number): NoteSpec {
  const instruments = Array.from(new Set(slotEvents.map((event) => event.instrument)));

  return {
    type: "note",
    keys: instruments.map((instrument) => INSTRUMENT_NOTATION[instrument].key),
    articulations: instruments
      .map((instrument) => INSTRUMENT_NOTATION[instrument].articulation)
      .filter((articulation): articulation is string => Boolean(articulation)),
    duration: SLOT_DURATION,
    startSixteenth,
    sourceTimes: slotEvents.map((event) => event.time),
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx jest lib/notation/__tests__/buildScore.test.ts`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/notation/buildScore.ts frontend/lib/notation/__tests__/buildScore.test.ts
git commit -m "feat: carry each score slot's real source timestamps through buildMeasures"
```

---

### Task 6: `DrumScore` builds its playhead timeline from real source timestamps

**Files:**
- Modify: `frontend/components/DrumScore.tsx`
- Test: `frontend/components/__tests__/DrumScore.test.tsx`

**Interfaces:**
- Consumes: `NoteSpec.sourceTimes` (Task 5).
- Produces: `DrumScore` no longer accepts a `tempoBpm` prop; `DrumScoreProps` becomes `{ events: AnalysisEvent[]; currentTime?: number }`.

- [ ] **Step 1: Write the failing tests**

Rewrite `frontend/components/__tests__/DrumScore.test.tsx` in full:

```tsx
import { render, screen } from "@testing-library/react";

import type { AnalysisEvent } from "@/lib/api/jobs";
import DrumScore from "../DrumScore";

function event(overrides: Partial<AnalysisEvent>): AnalysisEvent {
  return {
    id: "e",
    time: 0,
    instrument: "kick",
    measure: 1,
    beat: 1,
    subdivision: 0,
    ...overrides,
  };
}

describe("DrumScore", () => {
  it("should render an SVG score without throwing for a simple beat", () => {
    render(
      <DrumScore
        events={[
          event({ id: "1", instrument: "kick", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "3", instrument: "snare", beat: 2, subdivision: 0, time: 0.5 }),
          event({ id: "4", instrument: "hihat_open", beat: 3, subdivision: 2, time: 1.25 }),
        ]}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const svg = container.querySelector("svg");

    expect(svg).not.toBeNull();
    expect(container.querySelectorAll(".vf-stavenote").length).toBeGreaterThan(0);
  });

  it("should render nothing extra for an empty event list", () => {
    render(<DrumScore events={[]} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("svg")).toBeNull();
  });

  it("should not throw when given a currentTime but no events to build a score from", () => {
    render(<DrumScore events={[]} currentTime={5} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("svg")).toBeNull();
  });

  it("should force every note's stem upward, including kick and snare", () => {
    render(
      <DrumScore
        events={[
          event({ id: "1", instrument: "kick", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "snare", beat: 2, subdivision: 0, time: 0.5 }),
        ]}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const stemPaths = container.querySelectorAll(".vf-stem");

    expect(stemPaths.length).toBeGreaterThan(0);
  });

  it("should not draw a playhead line when currentTime is not provided", () => {
    render(<DrumScore events={[event({ id: "1", beat: 1, subdivision: 0, time: 0 })]} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("#drum-score-playhead")).toBeNull();
  });

  it("should draw a playhead line positioned at the current time, driven by each event's own source time", () => {
    const events = [
      event({ id: "1", beat: 1, subdivision: 0, time: 0 }),
      event({ id: "2", beat: 3, subdivision: 0, time: 7.3 }),
    ];

    const { rerender } = render(<DrumScore currentTime={0} events={events} />);

    const container = screen.getByTestId("drum-score");
    const lineAtStart = container.querySelector("#drum-score-playhead");
    expect(lineAtStart).not.toBeNull();
    const xAtStart = Number(lineAtStart?.getAttribute("x1"));

    // 7.3s is event 2's own real source time, not anything computeSlotTimeSeconds
    // would derive from a BPM - this is what "source-linked" means here.
    rerender(<DrumScore currentTime={7.3} events={events} />);

    const lineLater = container.querySelector("#drum-score-playhead");
    const xLater = Number(lineLater?.getAttribute("x1"));

    expect(xLater).toBeGreaterThan(xAtStart);
  });

  it("should auto-scroll the container horizontally to keep the playhead in view", () => {
    const events = [
      event({ id: "1", measure: 1, beat: 1, subdivision: 0, time: 0 }),
      event({ id: "2", measure: 4, beat: 4, subdivision: 3, time: 8 }),
    ];

    const { rerender } = render(<DrumScore currentTime={0} events={events} />);

    const container = screen.getByTestId("drum-score");
    Object.defineProperty(container, "clientWidth", { value: 200, configurable: true });
    container.scrollLeft = 0;

    rerender(<DrumScore currentTime={8} events={events} />);

    expect(container.scrollLeft).toBeGreaterThan(0);
  });

  it("should never move the playhead backward in x while stepping through a real multi-row score", () => {
    // MEASURES_PER_ROW is 4, so measure 5 starts a second row.
    const lastRowZeroTime = 3.95;
    const firstRowOneTime = 4.2;
    const events = [
      event({ id: "1", measure: 4, beat: 4, subdivision: 3, instrument: "kick", time: lastRowZeroTime }),
      event({ id: "2", measure: 5, beat: 1, subdivision: 0, instrument: "snare", time: firstRowOneTime }),
    ];

    const { rerender } = render(<DrumScore currentTime={0} events={events} />);
    const container = screen.getByTestId("drum-score");

    const sampleTimes = [
      lastRowZeroTime - 0.05,
      lastRowZeroTime,
      (lastRowZeroTime + firstRowOneTime) / 2,
      firstRowOneTime,
    ];

    let previousX: number | null = null;
    let previousY: number | null = null;
    for (const time of sampleTimes) {
      rerender(<DrumScore currentTime={time} events={events} />);
      const line = container.querySelector("#drum-score-playhead")!;
      const x = Number(line.getAttribute("x1"));
      const y = Number(line.getAttribute("y1"));

      if (previousX !== null && previousY === y) {
        expect(x).toBeGreaterThanOrEqual(previousX);
      }
      previousX = x;
      previousY = y;
    }

    // Sanity check the boundary was actually exercised across two rows.
    rerender(<DrumScore currentTime={lastRowZeroTime} events={events} />);
    const yBeforeBoundary = container.querySelector("#drum-score-playhead")!.getAttribute("y1");
    rerender(<DrumScore currentTime={firstRowOneTime} events={events} />);
    const yAfterBoundary = container.querySelector("#drum-score-playhead")!.getAttribute("y1");
    expect(yAfterBoundary).not.toBe(yBeforeBoundary);
  });

  it("should not require a tempoBpm prop", () => {
    // @ts-expect-error tempoBpm is no longer part of DrumScoreProps
    render(<DrumScore events={[]} tempoBpm={120} />);

    expect(screen.getByTestId("drum-score")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx jest components/__tests__/DrumScore.test.tsx`
Expected: FAIL — `DrumScore` still requires `tempoBpm`, and the playhead position tests fail because the component still derives time from `computeSlotTimeSeconds`/measure-beat-subdivision instead of each event's real `time`.

- [ ] **Step 3: Implement**

Replace `frontend/components/DrumScore.tsx` in full:

```tsx
"use client";

import { useEffect, useRef } from "react";
import { Beam, Formatter, Fraction, Renderer, Stave, Voice } from "vexflow";

import type { AnalysisEvent } from "@/lib/api/jobs";
import { BEATS_PER_MEASURE, buildMeasures } from "@/lib/notation/buildScore";
import { buildStaveNote } from "@/lib/notation/buildStaveNote";
import { computeAutoScrollLeft, interpolatePlayheadX, type TimelinePoint } from "@/lib/notation/timeline";

interface DrumScoreProps {
  events: AnalysisEvent[];
  currentTime?: number;
}

const MEASURES_PER_ROW = 4;
const MEASURE_WIDTH = 200;
const ROW_HEIGHT = 120;
const STAVE_X_START = 10;
const PLAYHEAD_ID = "drum-score-playhead";

function averageSourceTime(sourceTimes: number[]): number {
  return sourceTimes.reduce((sum, time) => sum + time, 0) / sourceTimes.length;
}

export default function DrumScore({ events, currentTime }: DrumScoreProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<TimelinePoint[]>([]);

  useEffect(() => {
    // containerRef is attached to the div this component always renders,
    // so React guarantees it's set before this effect runs; this guard only
    // satisfies the nullable ref type.
    const container = containerRef.current;
    if (!container) {
      return;
    }

    container.innerHTML = "";
    timelineRef.current = [];

    const measures = buildMeasures(events);
    if (measures.length === 0) {
      return;
    }

    const rows = Math.ceil(measures.length / MEASURES_PER_ROW);
    const width = MEASURES_PER_ROW * MEASURE_WIDTH + STAVE_X_START * 2;
    const height = rows * ROW_HEIGHT + 40;

    const renderer = new Renderer(container, Renderer.Backends.SVG);
    renderer.resize(width, height);
    const context = renderer.getContext();

    measures.forEach((measure, index) => {
      const row = Math.floor(index / MEASURES_PER_ROW);
      const col = index % MEASURES_PER_ROW;
      const x = STAVE_X_START + col * MEASURE_WIDTH;
      const y = 20 + row * ROW_HEIGHT;

      const stave = new Stave(x, y, MEASURE_WIDTH);
      if (col === 0) {
        stave.addClef("percussion");
      }
      if (index === 0) {
        stave.setTimeSignature("4/4");
      }
      stave.setContext(context).draw();

      const notes = measure.map(buildStaveNote);
      const voice = new Voice({ numBeats: 4, beatValue: 4 }).setStrict(false);
      voice.addTickables(notes);

      new Formatter().joinVoices([voice]).format([voice], MEASURE_WIDTH - 20);
      voice.draw(context, stave);

      const beams = Beam.generateBeams(notes, {
        stemDirection: 1,
        maintainStemDirections: true,
        beamRests: false,
        groups: [new Fraction(1, 4)],
      });
      beams.forEach((beam) => beam.setContext(context).draw());

      notes.forEach((note, slotIndex) => {
        const slot = measure[slotIndex];
        // Only note slots are anchored to a real source timestamp - rest
        // slots have no underlying event, so the playhead interpolates
        // smoothly across them between the nearest real anchors instead of
        // reconstructing a time from a BPM/grid assumption (see
        // interpolatePlayheadX in lib/notation/timeline.ts).
        if (slot.type !== "note") {
          return;
        }
        timelineRef.current.push({
          time: averageSourceTime(slot.sourceTimes),
          x: note.getAbsoluteX(),
          row,
        });
      });
    });
  }, [events]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || currentTime == null) {
      return;
    }

    const svg = container.querySelector("svg");
    if (!svg) {
      return;
    }

    // Every measure produced by buildMeasures contributes at least one
    // timeline point, so this is only null when the svg guard above already
    // returned (no measures rendered); kept as a defensive type narrowing.
    const point = interpolatePlayheadX(timelineRef.current, currentTime);
    if (!point) {
      return;
    }

    const yTop = 15 + point.row * ROW_HEIGHT;
    const yBottom = yTop + ROW_HEIGHT - 25;

    let line = svg.querySelector(`#${PLAYHEAD_ID}`);
    if (!line) {
      line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("id", PLAYHEAD_ID);
      line.setAttribute("stroke", "#e53e3e");
      line.setAttribute("stroke-width", "2");
      svg.appendChild(line);
    }
    line.setAttribute("x1", String(point.x));
    line.setAttribute("x2", String(point.x));
    line.setAttribute("y1", String(yTop));
    line.setAttribute("y2", String(yBottom));

    container.scrollLeft = computeAutoScrollLeft(container.scrollLeft, container.clientWidth, point.x);
  }, [currentTime]);

  return (
    <div
      ref={containerRef}
      data-testid="drum-score"
      style={{ width: "100%", overflowX: "auto" }}
    />
  );
}
```

Note `BEATS_PER_MEASURE` is imported but no longer used by this file directly — check: it isn't referenced anywhere else in the new version, so drop it from the import (`import { buildMeasures } from "@/lib/notation/buildScore";`). `SUBDIVISIONS_PER_BEAT` was already unused-removed the same way.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx jest components/__tests__/DrumScore.test.tsx`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/DrumScore.tsx frontend/components/__tests__/DrumScore.test.tsx
git commit -m "feat: build the playhead timeline from real event source times, not scalar BPM"
```

---

### Task 7: Drop `tempoBpm` from `Player`/`JobForm` and delete the now-dead `computeSlotTimeSeconds`

**Files:**
- Modify: `frontend/components/Player.tsx`
- Modify: `frontend/components/JobForm.tsx`
- Modify: `frontend/lib/notation/timeline.ts`
- Test: `frontend/components/__tests__/Player.test.tsx`
- Test: `frontend/components/__tests__/EndToEndFlow.test.tsx`
- Test: `frontend/lib/notation/__tests__/timeline.test.ts`

**Interfaces:**
- Produces: `PlayerProps` drops `tempoBpm`. `frontend/lib/notation/timeline.ts` no longer exports `computeSlotTimeSeconds`.

- [ ] **Step 1: Write the failing tests**

In `frontend/components/__tests__/Player.test.tsx`, remove the `tempoBpm={120}` line from every `<Player ... />` render call (there are 11 occurrences, one per `it(...)` block) so the tests describe the new prop contract. Leave every other prop and assertion unchanged.

In `frontend/lib/notation/__tests__/timeline.test.ts`, delete the entire `describe("computeSlotTimeSeconds", ...)` block (lines 8-19) and remove `computeSlotTimeSeconds` from the top `import { ... } from "../timeline"` line, leaving:

```ts
import { computeAutoScrollLeft, interpolatePlayheadX, type TimelinePoint } from "../timeline";
```

Check `frontend/components/__tests__/EndToEndFlow.test.tsx` for any `tempoBpm` reference (it matched the earlier grep for `Player`) and remove it the same way if present, without changing any other assertion in that file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx jest components/__tests__/Player.test.tsx lib/notation/__tests__/timeline.test.ts components/__tests__/EndToEndFlow.test.tsx`
Expected: FAIL — TypeScript/Jest errors because `Player` and `DrumScore`'s prop types (transitively) haven't dropped `tempoBpm` yet on the implementation side, and `computeSlotTimeSeconds` is still exported/still being imported by `DrumScore.test.tsx`'s old version (already replaced in Task 6, so this should now only fail because `timeline.ts` itself hasn't been changed yet).

- [ ] **Step 3: Implement**

In `frontend/lib/notation/timeline.ts`, delete the `computeSlotTimeSeconds` function and the now-unused `DEFAULT_BEATS_PER_MEASURE`/`DEFAULT_SUBDIVISIONS_PER_BEAT` constants (check first whether `interpolatePlayheadX` or `computeAutoScrollLeft` reference them — they don't, per the current file content), leaving:

```ts
export interface TimelinePoint {
  time: number;
  x: number;
  row: number;
}

export function interpolatePlayheadX(points: TimelinePoint[], time: number): TimelinePoint | null {
  if (points.length === 0) {
    return null;
  }

  if (time <= points[0].time) {
    return points[0];
  }

  const last = points[points.length - 1];
  if (time >= last.time) {
    return last;
  }

  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    if (time >= a.time && time <= b.time) {
      if (b.x < a.x) {
        // Adjacent points can go backward in x for reasons outside this
        // function's control: a new row restarts at the left margin while
        // the previous row's last slot sits at the right edge, or a dense
        // measure's notes overflow past the next measure's nominal start
        // (VexFlow's Formatter can exceed its requested width). Either
        // way, interpolating across such a pair would visibly slide the
        // playhead backward. Hold at the earlier point until the later
        // point's time is reached, then cut straight to it.
        return time >= b.time ? b : { time, x: a.x, row: a.row };
      }
      // Unreachable while points are sorted by non-decreasing time: any
      // pair sharing a.time with an earlier point would already have been
      // matched (and returned) by that earlier bracket first. Guards
      // against a division by zero if that invariant is ever broken.
      if (b.time === a.time) {
        return a;
      }
      const ratio = (time - a.time) / (b.time - a.time);
      return { time, x: a.x + (b.x - a.x) * ratio, row: a.row };
    }
  }

  // Unreachable given sorted points and the clamps above: any time strictly
  // between the first and last point's time is guaranteed to fall inside
  // some consecutive pair. Kept as a safety net if that invariant breaks.
  return last;
}

const DEFAULT_AUTO_SCROLL_MARGIN = 40;

// Keeps a target x position within view, without moving anything while it
// already sits comfortably inside the current viewport - so the playhead
// stays visible during playback without fighting the user's own scrolling.
export function computeAutoScrollLeft(
  currentScrollLeft: number,
  viewportWidth: number,
  targetX: number,
  margin: number = DEFAULT_AUTO_SCROLL_MARGIN,
): number {
  const visibleStart = currentScrollLeft + margin;
  const visibleEnd = currentScrollLeft + viewportWidth - margin;

  if (targetX < visibleStart) {
    return Math.max(0, targetX - margin);
  }
  if (targetX > visibleEnd) {
    return Math.max(0, targetX - viewportWidth + margin);
  }
  return currentScrollLeft;
}
```

In `frontend/components/Player.tsx`, remove `tempoBpm` from `PlayerProps`, from the destructured function parameters, and from the `<DrumScore ... />` call:

```tsx
interface PlayerProps {
  apiBaseUrl: string;
  jobId: string;
  events: AnalysisEvent[];
  createAudioContext?: () => DecodableAudioContext;
}
```

```tsx
export default function Player({
  apiBaseUrl,
  jobId,
  events,
  createAudioContext = defaultCreateAudioContext,
}: PlayerProps) {
```

```tsx
      <DrumScore events={events} currentTime={currentTime} />
```

In `frontend/components/JobForm.tsx`, remove the `tempoBpm={analysis.tempo_bpm}` line from the `<Player ... />` call (keep `apiBaseUrl`, `jobId`, `events` unchanged, and leave the unrelated `bpm` display variable near the top of the component untouched):

```tsx
        <Player
          apiBaseUrl={apiBaseUrl}
          jobId={job.id}
          events={analysis.events}
        />
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx jest components/__tests__/Player.test.tsx lib/notation/__tests__/timeline.test.ts components/__tests__/EndToEndFlow.test.tsx components/__tests__/JobForm.test.tsx`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/Player.tsx frontend/components/JobForm.tsx frontend/lib/notation/timeline.ts frontend/components/__tests__/Player.test.tsx frontend/components/__tests__/EndToEndFlow.test.tsx frontend/lib/notation/__tests__/timeline.test.ts
git commit -m "refactor: drop tempoBpm prop drilling and delete the dead scalar-BPM grid helper"
```

---

### Task 8: Full-suite verification and technical-debt closure note

**Files:**
- Modify: `TECHNICAL_DEBT.md`

**Interfaces:** None (verification + documentation only).

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 2: Run the full frontend suite**

Run: `cd frontend && npx jest`
Expected: PASS, no regressions.

- [ ] **Step 3: Run frontend typecheck and lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint .`
Expected: PASS, no type errors (confirms `tempoBpm` is fully gone from every call site) and no unused-import/unused-var lint errors (confirms `computeSlotTimeSeconds` and the `BEATS_PER_MEASURE`/`SUBDIVISIONS_PER_BEAT` imports were actually cleaned up where no longer used).

- [ ] **Step 4: Manual full-song drift check**

With the backend and frontend dev servers running (`cd backend && uv run fastapi dev app/main.py`, `cd frontend && npm run dev`), submit a real song through the UI, let it fully process, and play it start to finish while watching the playhead against the audio: confirm the playhead tracks each rendered hit closely for the whole song (no widening gap by the end, which is what constant-tempo-grid drift looked like before this change), and that seeking (via the seek bar) repositions the playhead correctly without a stale/incorrect jump. Note the result of this manual check in the PR description, per this issue's "full-song drift regression test/manual check passes" acceptance criterion — an automated full-song audio fixture is out of scope for this plan (no such fixture exists in the repo yet; PROJECT.md's Epic 2 exit gate, not this issue alone, is what ultimately requires one).

- [ ] **Step 5: Update `TECHNICAL_DEBT.md`**

Find the "Playback playhead uses a constant-tempo approximation instead of the real audio clock" entry (added in PR #98, `docs/status/2026-09-20-current-app-state.md` section 6) and append a resolution note in the same style as the file's other **Resolved**/**Partially resolved** entries:

```markdown
**Resolved (V1-010):** `DrumScore` now builds its playhead timeline from
each rendered note slot's real `AnalysisEvent.time` values (threaded
through `buildMeasures`'s `NoteSpec.sourceTimes`), interpolating only
across rest slots between two real anchors - not from
`computeSlotTimeSeconds`/a single BPM, which has been deleted as dead code
now that `DrumScore` was its only caller. The backend's `run_tempo_mapping`
also now quantizes events with `quantize_events_with_beats` (real detected
beat anchors, phase-aligned, not a t=0 grid) whenever at least two beats
are detected, falling back to the legacy constant grid only if beat
detection fails or returns fewer than two points - see
`docs/superpowers/plans/2026-09-21-source-linked-playhead-timeline.md`.
```

- [ ] **Step 6: Commit**

```bash
git add TECHNICAL_DEBT.md
git commit -m "docs: close out the playhead constant-tempo-drift technical debt entry"
```

---

## Self-Review Notes

- **Spec coverage:** "Remove computeSlotTimeSeconds/single-BPM timing as the authority for rendered playhead mapping" -> Task 6 stops `DrumScore` from calling it, Task 7 deletes it entirely. "Link score positions to source-time timing anchors/events" -> Task 5 threads `sourceTimes` through `buildMeasures`, Task 6 builds the timeline from them. "Player time maps through source-linked timeline" -> Task 6's rewritten playhead tests assert this directly (e.g. playhead position driven by `time: 7.3` on an event, not a grid formula). "seek and row transitions remain stable" -> the row-boundary and auto-scroll tests are preserved (adapted to real timestamps) in Task 6. "scalar BPM is no longer required for playhead placement" -> `DrumScoreProps`/`PlayerProps` drop `tempoBpm` entirely (Tasks 6-7), and a dedicated test proves it. "full-song drift regression test/manual check passes" -> Task 8 Step 4 (manual check, since no full-song audio fixture exists yet) plus the underlying fix (real per-event timestamps can't accumulate grid drift by construction). The backend wiring (`quantize_events_with_beats` reaching production, `/diagnostics` using `beat_anchored_position_to_seconds`) that the V1-009 plan explicitly assigned to this issue is covered by Tasks 2-4.
- **Placeholder scan:** no TBD/"handle appropriately"/"similar to above" — every step has literal code or an exact file-content replacement.
- **Type consistency:** `run_tempo_mapping(job_id, drums_path, events, store, tempo_estimator, beat_detector)` (Task 2) matches every call site listed in Task 2 and matches `run_pipeline`'s internal call. `run_pipeline(..., tempo_estimator, beat_detector, storage_dir)` (Task 2) matches both `create_job`/`retry_job`'s `background_tasks.add_task(...)` argument order (Task 4). `build_event_diagnostics(..., beats=None, ...)` (Task 3) matches the `beats=job.beats` call in `get_job_diagnostics` (Task 4). `NoteSpec.sourceTimes: number[]` (Task 5) matches `slot.sourceTimes` usage in `DrumScore.tsx` (Task 6). `DrumScoreProps` dropping `tempoBpm` (Task 6) matches `PlayerProps` dropping it and the `<DrumScore events={events} currentTime={currentTime} />` call (Task 7) and the `<Player apiBaseUrl jobId events />` call in `JobForm.tsx` (Task 7).
