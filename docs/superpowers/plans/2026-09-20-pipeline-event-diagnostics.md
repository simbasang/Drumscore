# Pipeline Event Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a developer inspect, for one job, how each raw transcriber event maps through quantization to its final score event and source timestamp — without changing what the production pipeline stores or returns today.

**Architecture:** The pipeline already discards pre-quantization events once `run_tempo_mapping` overwrites `job.events` with `quantize_events(...)` output (`app/job_processor.py:117-118`). This plan (1) persists the pre-quantization output separately as `Job.raw_events` (additive field, `job.events`/`job.tempo_bpm`/API responses are untouched), (2) adds `musical_position_to_seconds` — the exact inverse of `quantize_events`'s formula — to `beat_mapping.py`, so a quantized musical position can be converted back to seconds for comparison against the original source timestamp, (3) adds a pure `app/diagnostics.py` module that pairs each raw event with its quantized counterpart by `id` and computes the quantization error in seconds, and (4) exposes it read-only via `GET /api/jobs/{job_id}/diagnostics`, mirroring the existing `/analysis` endpoint's shape and status-code conventions.

**Tech Stack:** Python 3.13, dataclasses, FastAPI, pytest (all existing backend dependencies — no new dependencies).

**Spec:** GitHub issue #35 (V1-002), part of EPIC 1 (#28). `docs/ARCHITECTURE_V1.md`'s Observability section: "Timing diagnostics can compare raw source timestamp, nearest beat/downbeat, quantized musical position and rendered event." (Beat/downbeat detection doesn't exist yet — that's Epic 2/#40 — so this plan's diagnostics compare raw source timestamp, quantized musical position, and the quantization error; a `nearest_beat`/`downbeat` field can be added to `EventDiagnostic` in that later issue without breaking this one.) `TECHNICAL_DEBT.md`, "Quantization grid isn't phase-aligned to the beat" — the quantization-error field this plan adds is exactly the number needed to confirm/refute that hypothesis on a real job.

## Global Constraints

- Diagnostics must not alter production results: `job.events`, `job.tempo_bpm`, `job.status`, and every existing API response shape/behavior must be unchanged by this work. Regression-test this explicitly, don't just assume it.
- Every transformed (quantized) event must be traceable back to its raw source event — via the shared `DrumEvent.id`, which `quantize_events` already preserves.
- Source timestamps remain immutable and authoritative (`PROJECT.md`, `docs/ARCHITECTURE_V1.md`) — diagnostics only read `DrumEvent.time`, never recompute or overwrite it.
- Keep changes scoped to this issue: no beat/downbeat detection, no frontend changes, no changes to `quantize_events`'s existing signature/behavior (only a new sibling function is added to `beat_mapping.py`).
- Follow existing backend conventions: flat `test_*.py` files under `backend/tests/`, pytest AAA style, dataclasses for domain types, Pydantic response models in `app/api/jobs.py` mirroring existing ones (e.g. `AnalysisResponse`/`DrumEventResponse`).

---

### Task 1: `musical_position_to_seconds` — the inverse of `quantize_events`

**Files:**
- Modify: `backend/app/beat_mapping.py`
- Test: `backend/tests/test_beat_mapping.py`

**Interfaces:**
- Consumes: `app.transcription.DrumEvent`, `app.beat_mapping.{DEFAULT_BEATS_PER_MEASURE, DEFAULT_SUBDIVISIONS_PER_BEAT, quantize_events}` (all existing).
- Produces (used by Task 3): `musical_position_to_seconds(measure: int, beat: int, subdivision: int, bpm: float, beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE, subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT) -> float`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_beat_mapping.py`:

```python
from app.beat_mapping import musical_position_to_seconds


@pytest.mark.parametrize(
    "measure,beat,subdivision,expected_time",
    [
        (1, 1, 0, 0.0),
        (1, 1, 1, 0.125),
        (1, 1, 2, 0.25),
        (1, 1, 3, 0.375),
        (1, 2, 0, 0.5),
        (1, 4, 0, 1.5),
        (2, 1, 0, 2.0),
        (2, 1, 1, 2.125),
    ],
)
def test_musical_position_to_seconds_at_120bpm(measure, beat, subdivision, expected_time):
    time = musical_position_to_seconds(measure, beat, subdivision, bpm=120.0)

    assert time == pytest.approx(expected_time)


def test_musical_position_to_seconds_is_the_inverse_of_quantize_events_on_grid_aligned_times():
    grid_aligned_time = 1.5
    event = _event(grid_aligned_time)

    quantized = quantize_events([event], bpm=120.0)[0]
    reconstructed_time = musical_position_to_seconds(
        quantized.measure, quantized.beat, quantized.subdivision, bpm=120.0
    )

    assert reconstructed_time == pytest.approx(grid_aligned_time)


def test_musical_position_to_seconds_supports_different_tempo():
    time = musical_position_to_seconds(1, 2, 1, bpm=60.0)

    assert time == pytest.approx(1.25)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_beat_mapping.py -v`
Expected: FAIL/collection error — `musical_position_to_seconds` doesn't exist yet.

- [ ] **Step 3: Implement `musical_position_to_seconds`**

Append to `backend/app/beat_mapping.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_beat_mapping.py -v`
Expected: PASS (all tests, including pre-existing ones — no regressions).

- [ ] **Step 5: Commit**

```bash
git add backend/app/beat_mapping.py backend/tests/test_beat_mapping.py
git commit -m "feat: add musical_position_to_seconds as the inverse of quantize_events"
```

---

### Task 2: Persist raw (pre-quantization) transcriber events on the job

**Files:**
- Modify: `backend/app/jobs.py`
- Modify: `backend/app/job_processor.py`
- Test: `backend/tests/test_job_processor.py`

**Interfaces:**
- Consumes: existing `Job`, `JobStore`, `run_transcription`, `run_tempo_mapping`, `run_pipeline`.
- Produces (used by Task 4): `Job.raw_events: list[DrumEvent] | None` — the transcriber's output exactly as returned, before `quantize_events` ever touches it. Set once, in `run_transcription`, and never overwritten afterward.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_job_processor.py`:

```python
def test_run_transcription_stores_raw_events_alongside_events(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_transcription(job.id, tmp_path / "drums.wav", store, FakeSuccessfulTranscriber())

    updated = store.get(job.id)
    assert updated.raw_events == [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.KICK)]


def test_run_tempo_mapping_does_not_modify_raw_events(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    raw_events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]
    store.update(job.id, raw_events=raw_events)

    run_tempo_mapping(
        job.id, tmp_path / "drums.wav", raw_events, store, FakeSuccessfulTempoEstimator()
    )

    updated = store.get(job.id)
    assert updated.raw_events == raw_events
    assert updated.raw_events[0].beat is None
    assert updated.events[0].beat is not None


def test_run_pipeline_preserves_raw_events_separately_from_quantized_events(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_pipeline(
        job.id,
        source,
        store,
        FakeSuccessfulExtractor(),
        FakeSuccessfulSeparator(),
        FakeSuccessfulTranscriber(),
        FakeSuccessfulTempoEstimator(),
        tmp_path,
    )

    updated = store.get(job.id)
    assert updated.raw_events == [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.KICK)]
    assert updated.raw_events[0].beat is None
    assert updated.events[0].beat is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_job_processor.py -v`
Expected: FAIL — `Job` has no attribute/field `raw_events` yet.

- [ ] **Step 3: Add the `raw_events` field to `Job` and populate it in `run_transcription`**

In `backend/app/jobs.py`, add the field to the `Job` dataclass (after `events`, keeping every existing field and its position unchanged):

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
    error: str | None = None
```

In `backend/app/job_processor.py`, change the success branch of `run_transcription` from:

```python
    store.update(job_id, status=JobStatus.TRANSCRIBED, events=events)
    return events
```

to:

```python
    store.update(job_id, status=JobStatus.TRANSCRIBED, events=events, raw_events=events)
    return events
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_job_processor.py tests/test_jobs.py -v`
Expected: PASS (all tests, including pre-existing ones in both files — no regressions).

- [ ] **Step 5: Run the full backend suite to confirm production results are unchanged**

Run: `cd backend && uv run pytest -v`
Expected: PASS, same pass count as before plus the 3 new tests — proves the additive `raw_events` field didn't change any existing behavior (`JobResponse.from_job`, `/analysis`, retry, cleanup, etc. don't reference it).

- [ ] **Step 6: Commit**

```bash
git add backend/app/jobs.py backend/app/job_processor.py backend/tests/test_job_processor.py
git commit -m "feat: persist raw transcriber events separately from quantized events"
```

---

### Task 3: `app/diagnostics.py` — pair raw and quantized events with provenance and timing error

**Files:**
- Create: `backend/app/diagnostics.py`
- Test: `backend/tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `app.transcription.DrumEvent`, `app.beat_mapping.{musical_position_to_seconds, DEFAULT_BEATS_PER_MEASURE, DEFAULT_SUBDIVISIONS_PER_BEAT}` (Task 1).
- Produces (used by Task 4): `EventDiagnostic` frozen dataclass with fields `event_id: str`, `instrument: DrumInstrument`, `source_time: float`, `velocity: float | None`, `confidence: float | None`, `tempo_bpm: float`, `measure: int | None`, `beat: int | None`, `subdivision: int | None`, `quantized_time: float | None`, `quantization_error_seconds: float | None`; and `build_event_diagnostics(raw_events: list[DrumEvent], quantized_events: list[DrumEvent], tempo_bpm: float, beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE, subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT) -> list[EventDiagnostic]`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_diagnostics.py`:

```python
import pytest

from app.beat_mapping import quantize_events
from app.diagnostics import build_event_diagnostics
from app.transcription import DrumEvent, DrumInstrument


def test_build_event_diagnostics_traces_each_quantized_event_back_to_its_raw_source():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events(raw_events, bpm=120.0)

    diagnostics = build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    assert diagnostics[0].event_id == "e1"
    assert diagnostics[0].source_time == 0.13
    assert diagnostics[0].instrument == DrumInstrument.SNARE


def test_build_event_diagnostics_reports_the_quantization_error_in_seconds():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events(raw_events, bpm=120.0)

    diagnostics = build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    # 0.13s quantizes to subdivision 1 (0.125s) at 120 BPM.
    assert diagnostics[0].quantized_time == pytest.approx(0.125)
    assert diagnostics[0].quantization_error_seconds == pytest.approx(0.125 - 0.13)


def test_build_event_diagnostics_reports_zero_error_for_perfectly_grid_aligned_hits():
    raw_events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]
    quantized_events = quantize_events(raw_events, bpm=120.0)

    diagnostics = build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    assert diagnostics[0].quantization_error_seconds == pytest.approx(0.0, abs=1e-9)


def test_build_event_diagnostics_preserves_order_and_count():
    raw_events = [
        DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK),
        DrumEvent(id="e2", time=0.5, instrument=DrumInstrument.SNARE),
    ]
    quantized_events = quantize_events(raw_events, bpm=120.0)

    diagnostics = build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    assert [d.event_id for d in diagnostics] == ["e1", "e2"]


def test_build_event_diagnostics_passes_through_velocity_and_confidence():
    raw_events = [
        DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK, velocity=0.8, confidence=0.9)
    ]
    quantized_events = quantize_events(raw_events, bpm=120.0)

    diagnostics = build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    assert diagnostics[0].velocity == 0.8
    assert diagnostics[0].confidence == 0.9


def test_build_event_diagnostics_leaves_quantized_fields_none_when_no_matching_quantized_event():
    raw_events = [DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK)]

    diagnostics = build_event_diagnostics(raw_events, quantized_events=[], tempo_bpm=120.0)

    assert diagnostics[0].measure is None
    assert diagnostics[0].quantized_time is None
    assert diagnostics[0].quantization_error_seconds is None


def test_build_event_diagnostics_does_not_mutate_its_inputs():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events(raw_events, bpm=120.0)
    raw_events_before = list(raw_events)
    quantized_events_before = list(quantized_events)

    build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    assert raw_events == raw_events_before
    assert quantized_events == quantized_events_before
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_diagnostics.py -v`
Expected: FAIL/collection error — `app.diagnostics` doesn't exist yet.

- [ ] **Step 3: Implement `app/diagnostics.py`**

Create `backend/app/diagnostics.py`:

```python
import dataclasses

from app.beat_mapping import (
    DEFAULT_BEATS_PER_MEASURE,
    DEFAULT_SUBDIVISIONS_PER_BEAT,
    musical_position_to_seconds,
)
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
Expected: PASS (all 7 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/diagnostics.py backend/tests/test_diagnostics.py
git commit -m "feat: add build_event_diagnostics to trace quantized events back to source"
```

---

### Task 4: `GET /api/jobs/{job_id}/diagnostics` endpoint

**Files:**
- Modify: `backend/app/api/jobs.py`
- Test: `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `app.diagnostics.{EventDiagnostic, build_event_diagnostics}` (Task 3), existing `JobStore`/`Job`/`get_job_store` dependency.
- Produces: `GET /api/jobs/{job_id}/diagnostics` -> `DiagnosticsResponse` (200), 404 for an unknown job, 409 when the job hasn't reached `raw_events`/`events`/`tempo_bpm` all being set.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_jobs_api.py`:

```python
def test_get_diagnostics_returns_traced_events_when_job_is_tempo_mapped():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["tempo_bpm"] == 128.0
    assert len(body["events"]) == 2
    assert body["events"][0]["event_id"] == "e1"
    assert body["events"][0]["source_time"] == 0.5
    assert body["events"][0]["measure"] is not None
    assert isinstance(body["events"][0]["quantization_error_seconds"], float)


def test_get_diagnostics_returns_409_when_job_not_yet_tempo_mapped():
    app.dependency_overrides[get_transcriber] = lambda: FailingTranscriber()

    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/diagnostics")

    assert response.status_code == 409


def test_get_diagnostics_returns_404_for_unknown_job():
    response = client.get("/api/jobs/does-not-exist/diagnostics")

    assert response.status_code == 404


def test_get_diagnostics_does_not_change_job_state_or_analysis_output():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]
    analysis_before = client.get(f"/api/jobs/{job_id}/analysis").json()
    job_before = client.get(f"/api/jobs/{job_id}").json()

    client.get(f"/api/jobs/{job_id}/diagnostics")

    analysis_after = client.get(f"/api/jobs/{job_id}/analysis").json()
    job_after = client.get(f"/api/jobs/{job_id}").json()
    assert analysis_after == analysis_before
    assert job_after == job_before
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_jobs_api.py -v -k diagnostics`
Expected: FAIL — 404 Not Found for the route (endpoint doesn't exist yet).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/jobs.py`, add the import:

```python
from app.diagnostics import EventDiagnostic, build_event_diagnostics
```

Append, after the existing `AnalysisResponse`/`get_job_analysis` block:

```python
class EventDiagnosticResponse(BaseModel):
    event_id: str
    instrument: DrumInstrument
    source_time: float
    velocity: float | None = None
    confidence: float | None = None
    measure: int | None = None
    beat: int | None = None
    subdivision: int | None = None
    quantized_time: float | None = None
    quantization_error_seconds: float | None = None

    @classmethod
    def from_diagnostic(cls, diagnostic: EventDiagnostic) -> "EventDiagnosticResponse":
        return cls(
            event_id=diagnostic.event_id,
            instrument=diagnostic.instrument,
            source_time=diagnostic.source_time,
            velocity=diagnostic.velocity,
            confidence=diagnostic.confidence,
            measure=diagnostic.measure,
            beat=diagnostic.beat,
            subdivision=diagnostic.subdivision,
            quantized_time=diagnostic.quantized_time,
            quantization_error_seconds=diagnostic.quantization_error_seconds,
        )


class DiagnosticsResponse(BaseModel):
    tempo_bpm: float
    events: list[EventDiagnosticResponse]


@router.get("/{job_id}/diagnostics", response_model=DiagnosticsResponse)
def get_job_diagnostics(
    job_id: str, store: JobStore = Depends(get_job_store)
) -> DiagnosticsResponse:
    job = store.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.raw_events is None or job.events is None or job.tempo_bpm is None:
        raise HTTPException(
            status_code=409,
            detail=f"Diagnostics not available yet: job status is {job.status.value}",
        )

    diagnostics = build_event_diagnostics(job.raw_events, job.events, job.tempo_bpm)
    return DiagnosticsResponse(
        tempo_bpm=job.tempo_bpm,
        events=[EventDiagnosticResponse.from_diagnostic(d) for d in diagnostics],
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_jobs_api.py -v -k diagnostics`
Expected: PASS (all 4 new tests).

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && uv run pytest -v`
Expected: PASS, no regressions in any pre-existing test.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/jobs.py backend/tests/test_jobs_api.py
git commit -m "feat: expose GET /api/jobs/{id}/diagnostics for raw-to-quantized event tracing"
```

---

## Self-Review Notes

- **Spec coverage:** "a job can produce inspectable diagnostics" -> Task 4's endpoint; "every transformed event can be traced to source data" -> shared `id` matching in Task 3 plus `source_time`/`quantized_time`/`quantization_error_seconds` fields; "diagnostics do not alter production results" -> Task 2's additive-only `raw_events` field plus Task 4's explicit before/after regression test; "tests cover mapping identity/provenance" -> Task 3's `test_build_event_diagnostics_traces_each_quantized_event_back_to_its_raw_source` and `test_build_event_diagnostics_preserves_order_and_count`.
- **Out of scope, confirmed against `docs/ARCHITECTURE_V1.md`:** beat/downbeat anchors are not part of this plan's `EventDiagnostic` because beat/downbeat detection doesn't exist in the codebase yet (`docs/ARCHITECTURE_V1.md`'s BeatPoint concept is Epic 2 work, tracked separately as #40). Adding a `nearest_beat_time`/`is_downbeat` field later is additive and won't require reshaping this plan's output.
- **Type consistency checked:** `EventDiagnostic` field names/types in Task 3 match `EventDiagnosticResponse.from_diagnostic` in Task 4 exactly; `musical_position_to_seconds`'s parameter order/defaults in Task 1 match every call site in Task 3.
