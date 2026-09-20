# TempoMap and BeatPoint Domain Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce the `TempoPoint`, `BeatPoint`, and `TempoMap` domain contracts described in `docs/ARCHITECTURE_V1.md`'s Timing model, with full validation and serialization coverage, and make them coexist alongside the existing scalar `Job.tempo_bpm` without changing any current pipeline behavior.

**Architecture:** New pure-Python domain dataclasses in `backend/app/timing.py` (frozen, `__post_init__`-validated — matching this codebase's existing domain-layer style: `DrumEvent`, `Job`, `EventDiagnostic`), plus matching Pydantic serialization models in `backend/app/api/jobs.py` (matching the existing `DrumEventResponse`/`EventDiagnosticResponse` pattern). `Job` gains one new, purely additive field (`tempo_map: TempoMap | None = None`), populated by `run_tempo_mapping` as a degenerate single-point `TempoMap.constant(bpm)` built from the *same* scalar estimate already used for `tempo_bpm` — the literal "old scalar BPM can coexist temporarily" bridge the issue asks for, with zero behavior change to `quantize_events` or anything else downstream.

**Explicitly out of scope (belongs to later Epic 2 issues, not guessed at here):** real beat/downbeat detection (#40, V1-007), phase-aligned quantization (#42, V1-009), migrating the score/playhead timeline off scalar BPM (#43, V1-010), and removing the legacy scalar-BPM path (#44, V1-011). This issue only adds the contracts and proves they can coexist — it does not change what the pipeline actually computes.

**Tech Stack:** Python 3.13, dataclasses, Pydantic, pytest — existing backend stack, no new dependencies.

**Spec:** GitHub issue #39 (V1-006), part of EPIC 2 (#29). `docs/ARCHITECTURE_V1.md`'s Timing model section (exact contract shapes quoted below) and Migration section ("Introduce new contracts beside old ones, migrate one boundary at a time, and remove legacy scalar-BPM/grid code only after tests prove the new path owns all consumers.").

## Global Constraints

- Field names/shapes must match `docs/ARCHITECTURE_V1.md`'s Timing model exactly: `TempoPoint`: source time + BPM. `BeatPoint`: source time + measure + beat + downbeat flag + optional confidence. This is what "architecture docs match implementation" means for this issue — implementing to the already-committed spec, not writing new prose.
- `sourceTime` (this codebase's existing convention: `source_time`, snake_case) is immutable and authoritative — every contract carries it explicitly, never derives it from a grid.
- Do not touch `quantize_events`, `LibrosaTempoEstimator`, or any pipeline *behavior* — this issue is additive contracts only, not a timing-algorithm change. Real beat detection is #40's job.
- Follow the codebase's established two-layer pattern: plain frozen dataclasses for the domain layer (`app/timing.py`), separate Pydantic models for the API layer (`app/api/jobs.py`) with explicit `from_domain`-style converters — do not introduce Pydantic-as-domain-model, which would break from every existing precedent in this codebase (`DrumEvent`, `Job`, `EventDiagnostic` are all plain dataclasses).

---

### Task 1: `TempoPoint`, `BeatPoint`, `TempoMap` domain contracts

**Files:**
- Create: `backend/app/timing.py`
- Test: `backend/tests/test_timing.py`

**Interfaces:**
- Produces (used by Task 2 and Task 3): `TempoPoint(source_time: float, bpm: float)`, `BeatPoint(source_time: float, measure: int, beat: int, is_downbeat: bool, confidence: float | None = None)`, `TempoMap(points: tuple[TempoPoint, ...])` with `TempoMap.bpm_at(source_time: float) -> float` and `TempoMap.constant(bpm: float) -> TempoMap` (classmethod).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_timing.py`:

```python
import pytest

from app.timing import BeatPoint, TempoMap, TempoPoint


def test_tempo_point_stores_source_time_and_bpm():
    point = TempoPoint(source_time=1.5, bpm=120.0)

    assert point.source_time == 1.5
    assert point.bpm == 120.0


def test_tempo_point_rejects_a_negative_source_time():
    with pytest.raises(ValueError, match="source_time"):
        TempoPoint(source_time=-0.1, bpm=120.0)


def test_tempo_point_rejects_a_non_positive_bpm():
    with pytest.raises(ValueError, match="bpm"):
        TempoPoint(source_time=0.0, bpm=0.0)


def test_beat_point_stores_source_time_measure_beat_and_downbeat_flag():
    point = BeatPoint(source_time=2.0, measure=3, beat=1, is_downbeat=True)

    assert point.source_time == 2.0
    assert point.measure == 3
    assert point.beat == 1
    assert point.is_downbeat is True
    assert point.confidence is None


def test_beat_point_accepts_an_optional_confidence():
    point = BeatPoint(source_time=2.0, measure=1, beat=2, is_downbeat=False, confidence=0.87)

    assert point.confidence == 0.87


def test_beat_point_rejects_a_negative_source_time():
    with pytest.raises(ValueError, match="source_time"):
        BeatPoint(source_time=-1.0, measure=1, beat=1, is_downbeat=True)


def test_beat_point_rejects_a_measure_below_one():
    with pytest.raises(ValueError, match="measure"):
        BeatPoint(source_time=0.0, measure=0, beat=1, is_downbeat=True)


def test_beat_point_rejects_a_beat_below_one():
    with pytest.raises(ValueError, match="beat"):
        BeatPoint(source_time=0.0, measure=1, beat=0, is_downbeat=True)


def test_beat_point_rejects_a_confidence_outside_zero_to_one():
    with pytest.raises(ValueError, match="confidence"):
        BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True, confidence=1.5)


def test_tempo_map_rejects_an_empty_point_list():
    with pytest.raises(ValueError, match="at least one"):
        TempoMap(points=())


def test_tempo_map_rejects_points_not_sorted_by_source_time():
    with pytest.raises(ValueError, match="sorted"):
        TempoMap(
            points=(
                TempoPoint(source_time=1.0, bpm=120.0),
                TempoPoint(source_time=0.5, bpm=100.0),
            )
        )


def test_tempo_map_bpm_at_returns_the_tempo_in_effect_at_a_given_time():
    tempo_map = TempoMap(
        points=(
            TempoPoint(source_time=0.0, bpm=100.0),
            TempoPoint(source_time=10.0, bpm=140.0),
        )
    )

    assert tempo_map.bpm_at(0.0) == 100.0
    assert tempo_map.bpm_at(5.0) == 100.0
    assert tempo_map.bpm_at(10.0) == 140.0
    assert tempo_map.bpm_at(20.0) == 140.0


def test_tempo_map_bpm_at_uses_the_first_point_before_any_point_exists():
    tempo_map = TempoMap(points=(TempoPoint(source_time=2.0, bpm=90.0),))

    assert tempo_map.bpm_at(0.0) == 90.0


def test_tempo_map_constant_builds_a_single_point_map_anchored_at_zero():
    tempo_map = TempoMap.constant(128.0)

    assert tempo_map.points == (TempoPoint(source_time=0.0, bpm=128.0),)
    assert tempo_map.bpm_at(0.0) == 128.0
    assert tempo_map.bpm_at(999.0) == 128.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_timing.py -v`
Expected: FAIL/collection error — `app.timing` doesn't exist yet.

- [ ] **Step 3: Implement `app/timing.py`**

```python
import dataclasses


@dataclasses.dataclass(frozen=True)
class TempoPoint:
    """A tempo marking anchored to an immutable source-audio timestamp.
    See docs/ARCHITECTURE_V1.md's Timing model."""

    source_time: float
    bpm: float

    def __post_init__(self) -> None:
        if self.source_time < 0:
            raise ValueError(f"source_time must be >= 0, got {self.source_time}")
        if self.bpm <= 0:
            raise ValueError(f"bpm must be > 0, got {self.bpm}")


@dataclasses.dataclass(frozen=True)
class BeatPoint:
    """A detected beat anchored to an immutable source-audio timestamp,
    with its musical position and whether it starts a measure (downbeat).
    See docs/ARCHITECTURE_V1.md's Timing model."""

    source_time: float
    measure: int
    beat: int
    is_downbeat: bool
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.source_time < 0:
            raise ValueError(f"source_time must be >= 0, got {self.source_time}")
        if self.measure < 1:
            raise ValueError(f"measure must be >= 1, got {self.measure}")
        if self.beat < 1:
            raise ValueError(f"beat must be >= 1, got {self.beat}")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be between 0 and 1, got {self.confidence}")


@dataclasses.dataclass(frozen=True)
class TempoMap:
    """An ordered, source-time-anchored sequence of tempo points describing
    how tempo evolves across a song. Describes musical timing relative to
    source audio - it is not the playback clock. See
    docs/ARCHITECTURE_V1.md's Timing model."""

    points: tuple[TempoPoint, ...]

    def __post_init__(self) -> None:
        if len(self.points) == 0:
            raise ValueError("TempoMap must contain at least one TempoPoint")
        times = [point.source_time for point in self.points]
        if times != sorted(times):
            raise ValueError("TempoMap points must be sorted by non-decreasing source_time")

    def bpm_at(self, source_time: float) -> float:
        """The tempo in effect at source_time: the last point at or before
        it, or the first point if source_time precedes every point."""
        applicable = self.points[0]
        for point in self.points:
            if point.source_time > source_time:
                break
            applicable = point
        return applicable.bpm

    @classmethod
    def constant(cls, bpm: float) -> "TempoMap":
        """A single-point TempoMap anchored at t=0 - the bridge
        representation for the legacy scalar-BPM pipeline, used until real
        tempo-change detection (TECHNICAL_DEBT.md, "Tempo estimation
        disagrees with DrumScript's own estimate") replaces it."""
        return cls(points=(TempoPoint(source_time=0.0, bpm=bpm),))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_timing.py -v`
Expected: PASS (all 15 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/timing.py backend/tests/test_timing.py
git commit -m "feat: add TempoPoint, BeatPoint, and TempoMap domain contracts"
```

---

### Task 2: Serialization models for the new contracts

**Files:**
- Modify: `backend/app/api/jobs.py`
- Test: `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `app.timing.{TempoPoint, BeatPoint, TempoMap}` (Task 1).
- Produces (used by Task 3): `TempoPointResponse` and `TempoMapResponse` Pydantic models, each with a `from_domain(...)` classmethod converter, mirroring the existing `DrumEventResponse.from_event`/`EventDiagnosticResponse.from_diagnostic` pattern in this same file. (`BeatPointResponse` is added too, for completeness and forward use by #40, even though nothing constructs a real `BeatPoint` yet - only its serialization contract is being proven here.)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_jobs_api.py`:

```python
from app.timing import BeatPoint, TempoMap, TempoPoint


def test_tempo_point_response_round_trips_a_domain_tempo_point():
    from app.api.jobs import TempoPointResponse

    point = TempoPoint(source_time=1.5, bpm=120.0)

    response = TempoPointResponse.from_domain(point)
    dumped = response.model_dump()

    assert dumped == {"source_time": 1.5, "bpm": 120.0}


def test_beat_point_response_round_trips_a_domain_beat_point():
    from app.api.jobs import BeatPointResponse

    point = BeatPoint(source_time=2.0, measure=1, beat=2, is_downbeat=False, confidence=0.9)

    response = BeatPointResponse.from_domain(point)
    dumped = response.model_dump()

    assert dumped == {
        "source_time": 2.0,
        "measure": 1,
        "beat": 2,
        "is_downbeat": False,
        "confidence": 0.9,
    }


def test_tempo_map_response_round_trips_a_domain_tempo_map():
    from app.api.jobs import TempoMapResponse

    tempo_map = TempoMap.constant(128.0)

    response = TempoMapResponse.from_domain(tempo_map)
    dumped = response.model_dump()

    assert dumped == {"points": [{"source_time": 0.0, "bpm": 128.0}]}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_jobs_api.py -v -k "tempo_point_response or beat_point_response or tempo_map_response"`
Expected: FAIL - `TempoPointResponse`/`BeatPointResponse`/`TempoMapResponse` don't exist yet.

- [ ] **Step 3: Implement the response models**

In `backend/app/api/jobs.py`, add the import:

```python
from app.timing import BeatPoint, TempoMap, TempoPoint
```

Append, after the existing `EventDiagnosticResponse`/`DiagnosticsResponse` block:

```python
class TempoPointResponse(BaseModel):
    source_time: float
    bpm: float

    @classmethod
    def from_domain(cls, point: TempoPoint) -> "TempoPointResponse":
        return cls(source_time=point.source_time, bpm=point.bpm)


class BeatPointResponse(BaseModel):
    source_time: float
    measure: int
    beat: int
    is_downbeat: bool
    confidence: float | None = None

    @classmethod
    def from_domain(cls, point: BeatPoint) -> "BeatPointResponse":
        return cls(
            source_time=point.source_time,
            measure=point.measure,
            beat=point.beat,
            is_downbeat=point.is_downbeat,
            confidence=point.confidence,
        )


class TempoMapResponse(BaseModel):
    points: list[TempoPointResponse]

    @classmethod
    def from_domain(cls, tempo_map: TempoMap) -> "TempoMapResponse":
        return cls(points=[TempoPointResponse.from_domain(p) for p in tempo_map.points])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_jobs_api.py -v`
Expected: PASS (all tests in the file, no regressions).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/jobs.py backend/tests/test_jobs_api.py
git commit -m "feat: add serialization models for TempoPoint, BeatPoint, and TempoMap"
```

---

### Task 3: Let `Job.tempo_map` coexist with the legacy scalar `tempo_bpm`

**Files:**
- Modify: `backend/app/jobs.py`
- Modify: `backend/app/job_processor.py`
- Modify: `backend/app/api/jobs.py`
- Test: `backend/tests/test_job_processor.py`, `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `app.timing.TempoMap` (Task 1), `TempoMapResponse` (Task 2).
- Produces: `Job.tempo_map: TempoMap | None = None` (additive field, mirrors `raw_events`'s precedent from #35); `run_tempo_mapping` populates it; `JobResponse` exposes it (`null` until populated, matching every other optional field's precedent in this file).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_job_processor.py`:

```python
def test_run_tempo_mapping_populates_tempo_map_alongside_the_legacy_scalar_bpm(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(job.id, tmp_path / "drums.wav", events, store, FakeSuccessfulTempoEstimator())

    updated = store.get(job.id)
    assert updated.tempo_bpm == 120.0
    assert updated.tempo_map is not None
    assert updated.tempo_map.bpm_at(0.0) == 120.0
    assert updated.tempo_map.points == (TempoPoint(source_time=0.0, bpm=120.0),)
```

Add the `TempoPoint` import at the top of `backend/tests/test_job_processor.py`:

```python
from app.timing import TempoPoint
```

Append to `backend/tests/test_jobs_api.py`:

```python
def test_get_job_exposes_tempo_map_alongside_the_legacy_scalar_bpm():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    body = response.json()
    assert body["tempo_bpm"] == 128.0
    assert body["tempo_map"] == {"points": [{"source_time": 0.0, "bpm": 128.0}]}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_job_processor.py tests/test_jobs_api.py -v -k "tempo_map"`
Expected: FAIL - `Job` has no `tempo_map` attribute yet; `JobResponse` has no `tempo_map` key yet.

- [ ] **Step 3: Add the field and wire it up**

In `backend/app/jobs.py`, add the import and field:

```python
from app.timing import TempoMap
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
    error: str | None = None
```

In `backend/app/job_processor.py`, add the import and update `run_tempo_mapping`'s success path:

```python
from app.timing import TempoMap
```

```python
    quantized_events = quantize_events(events, bpm)
    store.update(
        job_id,
        status=JobStatus.TEMPO_MAPPED,
        tempo_bpm=bpm,
        tempo_map=TempoMap.constant(bpm),
        events=quantized_events,
    )
```

In `backend/app/api/jobs.py`, update `JobResponse`:

```python
class JobResponse(BaseModel):
    id: str
    url: str
    status: JobStatus
    audio_path: str | None = None
    drums_path: str | None = None
    accompaniment_path: str | None = None
    event_count: int | None = None
    tempo_bpm: float | None = None
    tempo_map: TempoMapResponse | None = None
    error: str | None = None

    @classmethod
    def from_job(cls, job: Job) -> "JobResponse":
        return cls(
            id=job.id,
            url=job.url,
            status=job.status,
            audio_path=job.audio_path,
            drums_path=job.drums_path,
            accompaniment_path=job.accompaniment_path,
            event_count=len(job.events) if job.events is not None else None,
            tempo_bpm=job.tempo_bpm,
            tempo_map=TempoMapResponse.from_domain(job.tempo_map) if job.tempo_map else None,
            error=job.error,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_job_processor.py tests/test_jobs_api.py -v`
Expected: PASS (all tests in both files, no regressions).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS, same pass count as before plus this plan's new tests - proves the additive `tempo_map` field changed nothing for existing consumers (`quantize_events`, the `/analysis` endpoint, retry, cleanup).

- [ ] **Step 6: Commit**

```bash
git add backend/app/jobs.py backend/app/job_processor.py backend/app/api/jobs.py backend/tests/test_job_processor.py backend/tests/test_jobs_api.py
git commit -m "feat: populate Job.tempo_map alongside the legacy scalar tempo_bpm"
```

---

## Self-Review Notes

- **Spec coverage:** "Contracts are strongly typed/validated" -> Task 1's `__post_init__` validation + 15 tests. "source timestamps are explicit" -> every contract's `source_time` field, never derived. "old scalar BPM can coexist temporarily" -> Task 3: both `tempo_bpm` and `tempo_map` populated from the same estimate, on the same `Job`, at the same time, with zero change to `quantize_events`'s behavior. "serialization/API tests pass" -> Task 2's round-trip tests plus Task 3's live `/api/jobs/{id}` test. "architecture docs match implementation" -> field names/shapes copied verbatim from `docs/ARCHITECTURE_V1.md`'s Timing model; no doc changes needed since the doc already specifies this correctly.
- **Scope check:** no beat/downbeat detection algorithm, no quantization changes, no frontend changes - all correctly deferred to #40/#42/#43. `BeatPoint`'s serialization model is added in Task 2 for forward use by #40 (so that issue doesn't have to also touch this file's established pattern), but nothing constructs a real `BeatPoint` yet - that stays out of scope here.
- **Type consistency:** `TempoMap.points` is `tuple[TempoPoint, ...]` throughout (Task 1 defines it, Task 2/3 consume it identically); `TempoMapResponse.points` is `list[TempoPointResponse]` (JSON has no tuple type, so the API layer's list is deliberate, not an inconsistency).
