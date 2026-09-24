# Epic 6 Slice A — Persistence, Durable Queue, Storage & Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Projects, jobs, analyses, saved score edits and artifact references survive restarts. Processing moves to a durable Postgres-backed queue drained by separate worker processes with leases, idempotent stage resume and a stage cache. Artifacts get a managed lifecycle. The frontend gains a project library, a `/projects/[id]` page and explicit score saving. This covers GitHub issues #80–#83 (V1-029 through V1-032).

**Architecture:** One `Store` protocol (projects, jobs-as-queue, artifacts, analyses, score versions, stage cache) has two implementations: `InMemoryStore` (unit tests) and `PostgresStore` (SQLAlchemy Core + psycopg 3, schema owned by Alembic). A shared contract test suite runs against both. The API only enqueues. `python -m app.worker` processes claim jobs with `FOR UPDATE SKIP LOCKED` leases, run the existing engines stage by stage, and write every stage output through `LocalArtifactStorage` (temp write → fsync → atomic rename) before committing its row. A crash therefore resumes cleanly at the first stage without output. A pruner behind a Postgres advisory lock applies the retention rules.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0.54, Alembic 1.20.0, psycopg 3.3.6 (binary), pydantic-settings 2.15.0, testcontainers 4.15.0 (Postgres 18), pytest; Next.js 16.3.5, React 19, TypeScript, Jest 30 + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-24-epic6a-persistence-queue-storage-design.md`

## Global Constraints

- Source audio time is authoritative: `DrumEvent.time` (sourceTime) must round-trip exactly through every persistence path (JSON file, JSONB). Never recompute it.
- Third-party outputs never become contracts: the DB and API store only application-owned dataclasses (`DrumEvent`, `BeatPoint`, `TempoMap`) and the frontend's `Score` JSON.
- The API never returns absolute filesystem paths. Storage keys are relative to `STORAGE_ROOT` and are never exposed either.
- The API never runs the pipeline. `BackgroundTasks` and `PipelineConcurrencyLimiter` are removed.
- Tempo-mapping behaviour (beat-anchored quantization, measure floor shift, ≥2 beats rule) is moved unchanged.
- Worker defaults: `WORKER_CONCURRENCY=2`, `LEASE_SECONDS=300`, `HEARTBEAT_SECONDS=60`, `POLL_INTERVAL_SECONDS=2.0`, `MAX_ATTEMPTS=3`, `RETRY_BASE_SECONDS=30` (backoff `30·2^(attempts-1)`), `FAILED_JOB_RETENTION_DAYS=7`, `PRUNE_INTERVAL_SECONDS=3600`.
- `PIPELINE_VERSION = "1"` lives in `backend/app/pipeline/version.py`. Bump it whenever an engine or its parameters change.
- New dependencies use the latest stable versions listed in Tech Stack (verified on PyPI 2026-09-24). Re-check with `uv add` (it resolves latest) and do not pin to older majors.
- Backend tests: pytest, flat `backend/tests/test_*.py` (existing convention). Tests that need Docker/Postgres carry `@pytest.mark.integration` (or run through the parametrized `store` fixture's `postgres` param). Shared fakes live in `backend/tests/fakes.py`, not duplicated inline.
- Frontend tests: Jest + RTL in `__tests__` folders next to the code; reusable mocks in `__mocks__` folders; `describe("<unit>")` / `it("should …")`; Arrange/Act/Assert separated by blank lines, no comments in tests (per `~/.claude/rules/testing.md`).
- Aim for 100% coverage of new code. A line that genuinely cannot be tested gets a comment explaining why (plus `# pragma: no cover` / `/* istanbul ignore next */`).
- Commits: the user's global rule forbids `git add`/`git commit` unless the user explicitly asks in that message. The **Commit** steps below are checkpoints. Run them only after the user has authorized committing for this execution; otherwise stop at the checkpoint and report.
- Verification commands: backend `cd backend && uv run pytest` (full, needs Docker running) or `uv run pytest -m "not integration"` (fast). Frontend `cd frontend && pnpm test && pnpm lint && pnpm exec tsc --noEmit`.

## Deliberate refinements of the spec (decided while planning)

1. **One `Store` protocol instead of six repository protocols.** The spec requires stage output, cache entry and status transition in one transaction, and a single store object is the simplest way to guarantee that. Methods are grouped by aggregate in the protocol.
2. **Raw transcription is an artifact file** (`raw_transcription.json`) rather than a JSONB payload in `stage_cache`. All three cached stages (extract, separate, transcribe) then produce artifacts, and `stage_cache` stores only artifact descriptors. The analysis row still carries `raw_events` JSONB for the diagnostics endpoint.
3. **`tempo_mapped` is replaced by `completed`** as the terminal success status. The `mapping_tempo` stage writes the analysis and completes the job in one transaction, so no job ever rests in `tempo_mapped`.
4. **Forced duplicate projects copy the existing project's title** (a cache hit skips extraction, so no title would arrive otherwise).
5. **Time is passed in** (`now: datetime`) to every store method that depends on it, instead of using DB `now()`. Leases, backoff and pruning are then deterministic in both implementations.

## File structure

Backend (new unless noted):
```
backend/
  alembic.ini
  migrations/env.py, script.py.mako, versions/0001_initial_schema.py
  app/config.py                         Settings (pydantic-settings)
  app/persistence/__init__.py
  app/persistence/models.py             JobStatus, ArtifactKind, Stage, Project, Job, Artifact, NewArtifact,
                                        CacheEntry, NewAnalysis, Analysis, ScoreVersion, ProjectSummary, errors
  app/persistence/serialization.py      DrumEvent/BeatPoint/TempoMap <-> JSON-able dicts, events json bytes
  app/persistence/store.py              Store protocol
  app/persistence/memory.py             InMemoryStore
  app/persistence/tables.py             SQLAlchemy Core tables (metadata)
  app/persistence/postgres.py           PostgresStore
  app/persistence/migrations.py         upgrade_to_head / downgrade_to_base helpers
  app/storage.py                        ArtifactStorage protocol + LocalArtifactStorage
  app/pipeline/__init__.py
  app/pipeline/version.py               PIPELINE_VERSION
  app/pipeline/errors.py                PERMANENT_ERRORS, InsufficientBeatsError, is_permanent, backoff_seconds
  app/pipeline/tempo_mapping.py         map_tempo (moved logic from job_processor.run_tempo_mapping)
  app/pipeline/runner.py                PipelineEngines, JobContext, JobAbandoned, process_job
  app/worker/__init__.py
  app/worker/heartbeat.py               LeaseHeartbeat
  app/worker/worker.py                  Worker (run_once / run_forever / stop)
  app/worker/pruner.py                  prune, PruneReport
  app/worker/__main__.py                process entrypoint
  app/api/schemas.py                    response models moved out of api/jobs.py
  app/api/projects.py                   /api/projects router
  app/audio_extraction.py               (modify) ExtractedAudio
  app/youtube_audio_extractor.py        (modify) returns ExtractedAudio with title
  app/main.py                           (modify) projects router, lifespan migrations, CORS methods
  DELETE: app/jobs.py, app/job_processor.py, app/job_cleanup.py, app/api/jobs.py
          tests/test_jobs.py, tests/test_job_processor.py, tests/test_job_cleanup.py, tests/test_jobs_api.py
  tests/conftest.py, tests/fakes.py, tests/test_config.py, tests/test_persistence_serialization.py,
  tests/test_store_contract.py, tests/test_migrations.py, tests/test_storage.py, tests/test_tempo_mapping.py,
  tests/test_pipeline_errors.py, tests/test_runner.py, tests/test_heartbeat.py, tests/test_worker.py,
  tests/test_worker_integration.py, tests/test_pruner.py, tests/test_projects_api.py
docker-compose.dev.yml                  (repo root) Postgres 18 for dev
backend/.env.example
```

Frontend:
```
frontend/lib/api/types.ts               DrumInstrument, AnalysisEvent, Beat, Analysis (moved from jobs.ts)
frontend/lib/api/projects.ts            new client (replaces jobs.ts)
frontend/lib/api/__mocks__/projects.ts
frontend/lib/api/__tests__/projects.test.ts
frontend/lib/score/useScoreEditor.ts    (modify) initialScore, isDirty, markSaved
frontend/components/Player.tsx          (modify) projectId, initialScore, onSave, save UI
frontend/components/ProjectView.tsx     polling + load order + save wiring
frontend/components/NewProjectForm.tsx  submit + duplicate dialog
frontend/components/ProjectLibrary.tsx  list/open/delete
frontend/app/page.tsx                   (modify) form + library
frontend/app/projects/[id]/page.tsx
frontend/__mocks__/next/navigation.ts
DELETE: frontend/lib/api/jobs.ts, lib/api/__tests__/jobs.test.ts, components/JobForm.tsx, components/__tests__/JobForm.test.tsx
```

Docs: `docs/PERSISTENCE.md` (new), `docs/ARCHITECTURE_V1.md`, `TECHNICAL_DEBT.md`, `README.md` (run instructions).

---

### Task 1: Dependencies, settings, dev Postgres and test fixtures

**Files:**
- Modify: `backend/pyproject.toml` (via `uv add`)
- Create: `backend/app/config.py`, `backend/.env.example`, `docker-compose.dev.yml`, `backend/tests/conftest.py`, `backend/tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings` (fields below), `app.config.get_settings() -> Settings` (cached); pytest fixture `postgres_url` (session, str `postgresql+psycopg://…`); marker `integration`.

- [ ] **Step 1: Add dependencies**

Run (from `backend/`):
```bash
uv add sqlalchemy alembic "psycopg[binary]" pydantic-settings
uv add --dev "testcontainers[postgres]"
```
Expected: `pyproject.toml` lists `sqlalchemy>=2.0.54`, `alembic>=1.20.0`, `psycopg[binary]>=3.3.6`, `pydantic-settings>=2.15.0`, and dev `testcontainers[postgres]>=4.15.0`.

Then add the marker to `[tool.pytest.ini_options]` in `backend/pyproject.toml`:
```toml
[tool.pytest.ini_options]
pythonpath = ["."]
markers = [
    "integration: needs Docker (Postgres via testcontainers)",
]
```

- [ ] **Step 2: Write the failing settings tests**

`backend/tests/test_config.py`:
```python
from pathlib import Path

from app.config import Settings


def test_settings_have_documented_defaults(monkeypatch):
    for name in ("DATABASE_URL", "STORAGE_ROOT", "WORKER_CONCURRENCY", "LEASE_SECONDS"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore"
    assert settings.storage_root == Path(__file__).resolve().parent.parent / "data"
    assert settings.worker_concurrency == 2
    assert settings.lease_seconds == 300
    assert settings.heartbeat_seconds == 60
    assert settings.poll_interval_seconds == 2.0
    assert settings.max_attempts == 3
    assert settings.retry_base_seconds == 30
    assert settings.failed_job_retention_days == 7
    assert settings.prune_interval_seconds == 3600
    assert settings.storage_warn_bytes == 50 * 1024**3
    assert settings.run_migrations_on_startup is True


def test_settings_read_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("WORKER_CONCURRENCY", "4")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"
    assert settings.storage_root == tmp_path
    assert settings.worker_concurrency == 4
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.config'`.

- [ ] **Step 4: Implement settings**

`backend/app/config.py`:
```python
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or
    backend/.env). See docs/PERSISTENCE.md for what each value controls."""

    model_config = SettingsConfigDict(env_file=_BACKEND_DIR / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore"
    storage_root: Path = _BACKEND_DIR / "data"
    worker_concurrency: int = 2
    lease_seconds: int = 300
    heartbeat_seconds: float = 60
    poll_interval_seconds: float = 2.0
    max_attempts: int = 3
    retry_base_seconds: int = 30
    failed_job_retention_days: int = 7
    prune_interval_seconds: int = 3600
    storage_warn_bytes: int = 50 * 1024**3
    run_migrations_on_startup: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: 2 passed.

- [ ] **Step 6: Dev Postgres, env example and the shared Postgres fixture**

`docker-compose.dev.yml` (repo root):
```yaml
services:
  postgres:
    image: postgres:18-alpine
    environment:
      POSTGRES_USER: drumscore
      POSTGRES_PASSWORD: drumscore
      POSTGRES_DB: drumscore
    ports:
      - "5432:5432"
    volumes:
      - drumscore-pg:/var/lib/postgresql
volumes:
  drumscore-pg:
```

`backend/.env.example`:
```
DATABASE_URL=postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore
STORAGE_ROOT=./data
WORKER_CONCURRENCY=2
```

`backend/tests/conftest.py`:
```python
import pytest


@pytest.fixture(scope="session")
def postgres_url():
    """One throwaway Postgres 18 container per test session. Only
    requested by integration tests, so `pytest -m "not integration"` never
    starts Docker."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:18-alpine", driver="psycopg") as container:
        yield container.get_connection_url()
```

Check that `backend/.gitignore` already ignores `.env` (add a line `.env` if it doesn't; `data/` is already ignored).

- [ ] **Step 7: Commit (checkpoint, see Global Constraints)**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/config.py backend/.env.example backend/.gitignore backend/tests/conftest.py backend/tests/test_config.py docker-compose.dev.yml
git commit -m "feat(backend): add persistence dependencies, settings and dev Postgres"
```

---

### Task 2: Domain records and analysis serialization

**Files:**
- Create: `backend/app/persistence/__init__.py` (empty), `backend/app/persistence/models.py`, `backend/app/persistence/serialization.py`, `backend/app/pipeline/__init__.py` (empty), `backend/app/pipeline/version.py`
- Test: `backend/tests/test_persistence_serialization.py`

**Interfaces:**
- Produces (models.py): enums `JobStatus`, `ArtifactKind`, `Stage`; `TERMINAL_STATUSES`; frozen dataclasses `Project`, `Job`, `Artifact`, `NewArtifact`, `CacheEntry`, `NewAnalysis`, `Analysis`, `ScoreVersion`, `ProjectSummary`; exceptions `LeaseLostError`, `ScoreVersionConflictError(latest_version: int | None)`; `new_id() -> str`.
- Produces (serialization.py): `event_to_dict`, `event_from_dict`, `beat_to_dict`, `beat_from_dict`, `tempo_map_to_dict`, `tempo_map_from_dict`, `events_to_json_bytes(list[DrumEvent]) -> bytes`, `events_from_json_bytes(bytes) -> list[DrumEvent]`, `artifact_to_dict(NewArtifact) -> dict`, `artifact_from_dict(dict) -> NewArtifact`.
- Produces: `app.pipeline.version.PIPELINE_VERSION = "1"`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_persistence_serialization.py`:
```python
import json

from app.persistence.models import ArtifactKind, NewArtifact
from app.persistence.serialization import (
    artifact_from_dict,
    artifact_to_dict,
    beat_from_dict,
    beat_to_dict,
    event_from_dict,
    event_to_dict,
    events_from_json_bytes,
    events_to_json_bytes,
    tempo_map_from_dict,
    tempo_map_to_dict,
)
from app.timing import BeatPoint, TempoMap, TempoPoint
from app.transcription import DrumEvent, DrumInstrument

AWKWARD_TIME = 0.1 + 0.2


def test_event_round_trips_every_field_through_json():
    event = DrumEvent(
        id="e1",
        time=AWKWARD_TIME,
        instrument=DrumInstrument.HIHAT_OPEN,
        velocity=0.8,
        confidence=0.5,
        provenance="drumscript",
        measure=3,
        beat=2,
        subdivision=1,
    )

    restored = event_from_dict(json.loads(json.dumps(event_to_dict(event))))

    assert restored == event
    assert restored.time == AWKWARD_TIME


def test_event_round_trips_optional_fields_as_none():
    event = DrumEvent(id="e2", time=1.5, instrument=DrumInstrument.KICK)

    restored = event_from_dict(json.loads(json.dumps(event_to_dict(event))))

    assert restored == event


def test_event_dict_stores_instrument_as_plain_string():
    event = DrumEvent(id="e3", time=2.0, instrument=DrumInstrument.SNARE)

    assert event_to_dict(event)["instrument"] == "snare"


def test_beat_round_trips_through_json():
    beat = BeatPoint(source_time=AWKWARD_TIME, measure=2, beat=4, is_downbeat=False, confidence=0.9)

    restored = beat_from_dict(json.loads(json.dumps(beat_to_dict(beat))))

    assert restored == beat


def test_tempo_map_round_trips_through_json():
    tempo_map = TempoMap(points=(TempoPoint(source_time=0.0, bpm=120.0), TempoPoint(source_time=30.5, bpm=128.25)))

    restored = tempo_map_from_dict(json.loads(json.dumps(tempo_map_to_dict(tempo_map))))

    assert restored == tempo_map


def test_events_json_bytes_round_trip_preserves_source_times():
    events = [
        DrumEvent(id="e1", time=AWKWARD_TIME, instrument=DrumInstrument.KICK),
        DrumEvent(id="e2", time=123.456789012345, instrument=DrumInstrument.RIDE, provenance="drumscript"),
    ]

    restored = events_from_json_bytes(events_to_json_bytes(events))

    assert restored == events


def test_artifact_descriptor_round_trips_through_json():
    artifact = NewArtifact(kind=ArtifactKind.DRUMS_STEM, storage_key="projects/p/j/drums.wav", size_bytes=10, sha256="ab")

    restored = artifact_from_dict(json.loads(json.dumps(artifact_to_dict(artifact))))

    assert restored == artifact
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_persistence_serialization.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.persistence'`.

- [ ] **Step 3: Implement models, serialization and the pipeline version**

`backend/app/pipeline/version.py`:
```python
# Identifies the engines/parameters that produced a cached stage output.
# Bump whenever an extractor, separator, transcriber or tempo/beat engine
# (or its parameters) changes, so stale stage_cache entries are never reused.
PIPELINE_VERSION = "1"
```

`backend/app/persistence/models.py`:
```python
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from app.timing import BeatPoint, TempoMap
from app.transcription import DrumEvent


def new_id() -> str:
    return str(uuid.uuid4())


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    SEPARATING_STEMS = "separating_stems"
    STEMS_SEPARATED = "stems_separated"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    MAPPING_TEMPO = "mapping_tempo"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED})


class ArtifactKind(str, Enum):
    SOURCE_AUDIO = "source_audio"
    DRUMS_STEM = "drums_stem"
    ACCOMPANIMENT_STEM = "accompaniment_stem"
    RAW_TRANSCRIPTION = "raw_transcription"


class Stage(str, Enum):
    EXTRACT = "extract"
    SEPARATE = "separate"
    TRANSCRIBE = "transcribe"


@dataclass(frozen=True)
class Project:
    id: str
    title: str
    source_kind: str
    source_url: str
    source_key: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class Job:
    id: str
    project_id: str
    status: JobStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    correlation_id: str
    created_at: datetime
    updated_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    error: str | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class NewArtifact:
    kind: ArtifactKind
    storage_key: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class Artifact:
    id: str
    project_id: str
    job_id: str
    kind: ArtifactKind
    storage_key: str
    size_bytes: int
    sha256: str
    created_at: datetime
    pruned_at: datetime | None = None


@dataclass(frozen=True)
class CacheEntry:
    source_key: str
    stage: Stage
    pipeline_version: str
    artifacts: tuple[NewArtifact, ...]


@dataclass(frozen=True)
class NewAnalysis:
    pipeline_version: str
    tempo_bpm: float
    tempo_map: TempoMap
    beats: list[BeatPoint]
    events: list[DrumEvent]
    raw_events: list[DrumEvent]


@dataclass(frozen=True)
class Analysis:
    id: str
    project_id: str
    job_id: str
    pipeline_version: str
    tempo_bpm: float
    tempo_map: TempoMap
    beats: list[BeatPoint]
    events: list[DrumEvent]
    raw_events: list[DrumEvent]
    created_at: datetime


@dataclass(frozen=True)
class ScoreVersion:
    id: str
    project_id: str
    analysis_id: str
    version: int
    score: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class ProjectSummary:
    project: Project
    latest_job_status: JobStatus | None
    has_edits: bool


class LeaseLostError(Exception):
    """The caller no longer owns the job's lease (another worker reclaimed
    it after expiry), so it must stop touching the job."""


class ScoreVersionConflictError(Exception):
    def __init__(self, latest_version: int | None) -> None:
        super().__init__(f"Score has moved on; latest version is {latest_version}")
        self.latest_version = latest_version
```

`backend/app/persistence/serialization.py`:
```python
import json
from typing import Any

from app.persistence.models import ArtifactKind, NewArtifact
from app.timing import BeatPoint, TempoMap, TempoPoint
from app.transcription import DrumEvent, DrumInstrument

# Floats are written with json's shortest round-trip repr, so every
# sourceTime reads back bit-identical (see test_persistence_serialization).


def event_to_dict(event: DrumEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "time": event.time,
        "instrument": event.instrument.value,
        "velocity": event.velocity,
        "confidence": event.confidence,
        "provenance": event.provenance,
        "measure": event.measure,
        "beat": event.beat,
        "subdivision": event.subdivision,
    }


def event_from_dict(data: dict[str, Any]) -> DrumEvent:
    return DrumEvent(
        id=data["id"],
        time=data["time"],
        instrument=DrumInstrument(data["instrument"]),
        velocity=data.get("velocity"),
        confidence=data.get("confidence"),
        provenance=data.get("provenance"),
        measure=data.get("measure"),
        beat=data.get("beat"),
        subdivision=data.get("subdivision"),
    )


def beat_to_dict(beat: BeatPoint) -> dict[str, Any]:
    return {
        "source_time": beat.source_time,
        "measure": beat.measure,
        "beat": beat.beat,
        "is_downbeat": beat.is_downbeat,
        "confidence": beat.confidence,
    }


def beat_from_dict(data: dict[str, Any]) -> BeatPoint:
    return BeatPoint(
        source_time=data["source_time"],
        measure=data["measure"],
        beat=data["beat"],
        is_downbeat=data["is_downbeat"],
        confidence=data.get("confidence"),
    )


def tempo_map_to_dict(tempo_map: TempoMap) -> dict[str, Any]:
    return {"points": [{"source_time": p.source_time, "bpm": p.bpm} for p in tempo_map.points]}


def tempo_map_from_dict(data: dict[str, Any]) -> TempoMap:
    return TempoMap(points=tuple(TempoPoint(source_time=p["source_time"], bpm=p["bpm"]) for p in data["points"]))


def events_to_json_bytes(events: list[DrumEvent]) -> bytes:
    return json.dumps([event_to_dict(event) for event in events]).encode("utf-8")


def events_from_json_bytes(data: bytes) -> list[DrumEvent]:
    return [event_from_dict(item) for item in json.loads(data.decode("utf-8"))]


def artifact_to_dict(artifact: NewArtifact) -> dict[str, Any]:
    return {
        "kind": artifact.kind.value,
        "storage_key": artifact.storage_key,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
    }


def artifact_from_dict(data: dict[str, Any]) -> NewArtifact:
    return NewArtifact(
        kind=ArtifactKind(data["kind"]),
        storage_key=data["storage_key"],
        size_bytes=data["size_bytes"],
        sha256=data["sha256"],
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_persistence_serialization.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit (checkpoint)**

```bash
git add backend/app/persistence backend/app/pipeline backend/tests/test_persistence_serialization.py
git commit -m "feat(backend): add persistence domain records and analysis serialization"
```

---

### Task 3: Store protocol and in-memory store (projects, analyses, scores)

**Files:**
- Create: `backend/app/persistence/store.py`, `backend/app/persistence/memory.py`, `backend/tests/test_store_contract.py`
- Modify: `backend/tests/conftest.py` (add `store` fixture)

**Interfaces:**
- Consumes: everything in `app.persistence.models`.
- Produces: `Store` protocol (full surface, used by every later task); `InMemoryStore()` implementing the project/job-read/analysis/score part now. Tasks 4 and 5 add the rest. Contract-test helpers in `test_store_contract.py`: `NOW`, `create(store, key="youtube:abc", now=NOW) -> tuple[Project, Job]`.

- [ ] **Step 1: Write the Store protocol**

`backend/app/persistence/store.py`:
```python
from collections.abc import Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Protocol

from app.persistence.models import (
    Analysis,
    Artifact,
    ArtifactKind,
    CacheEntry,
    Job,
    JobStatus,
    NewAnalysis,
    NewArtifact,
    Project,
    ProjectSummary,
    ScoreVersion,
    Stage,
)


class Store(Protocol):
    """Durable state for projects, the job queue, artifacts, analyses,
    score versions and the stage cache. One object (rather than one
    repository per table) so a stage commit - artifact rows, cache entry
    and status transition - is a single transaction. Methods that mutate a
    leased job take the caller's `owner` and raise LeaseLostError if the
    job's lease has passed to someone else. See docs/PERSISTENCE.md."""

    # --- projects -------------------------------------------------------
    def create_project_with_job(
        self, *, source_kind: str, source_url: str, source_key: str, title: str, max_attempts: int, now: datetime
    ) -> tuple[Project, Job]: ...

    def get_project(self, project_id: str) -> Project | None: ...

    def find_live_project_by_source_key(self, source_key: str) -> Project | None: ...

    def list_live_projects(self) -> list[ProjectSummary]: ...

    def set_project_title(self, project_id: str, title: str, now: datetime) -> None: ...

    def soft_delete_project(self, project_id: str, now: datetime) -> bool: ...

    # --- jobs / queue -----------------------------------------------------
    def get_job(self, job_id: str) -> Job | None: ...

    def latest_job(self, project_id: str) -> Job | None: ...

    def claim_next_job(self, owner: str, lease_seconds: int, now: datetime) -> Job | None: ...

    def extend_lease(self, job_id: str, owner: str, lease_seconds: int, now: datetime) -> bool: ...

    def release_lease(self, job_id: str, owner: str, now: datetime) -> None: ...

    def set_job_status(self, job_id: str, owner: str, status: JobStatus, now: datetime) -> None: ...

    def commit_stage(
        self,
        job_id: str,
        owner: str,
        status: JobStatus,
        artifacts: Sequence[NewArtifact],
        cache_entry: CacheEntry | None,
        now: datetime,
    ) -> list[Artifact]: ...

    def complete_job(self, job_id: str, owner: str, analysis: NewAnalysis, now: datetime) -> Analysis: ...

    def fail_job(self, job_id: str, owner: str, error: str, now: datetime) -> None: ...

    def schedule_retry(self, job_id: str, owner: str, error: str, available_at: datetime, now: datetime) -> None: ...

    def requeue_failed_job(self, job_id: str, now: datetime) -> Job | None: ...

    # --- artifacts / cache ------------------------------------------------
    def artifacts_for_job(self, job_id: str) -> dict[ArtifactKind, Artifact]: ...

    def get_cache_entry(self, source_key: str, stage: Stage, pipeline_version: str) -> CacheEntry | None: ...

    # --- analyses / scores ------------------------------------------------
    def latest_analysis(self, project_id: str) -> Analysis | None: ...

    def latest_score(self, project_id: str) -> ScoreVersion | None: ...

    def save_score(
        self, project_id: str, analysis_id: str, score: dict[str, Any], base_version: int | None, now: datetime
    ) -> ScoreVersion: ...

    # --- lifecycle ----------------------------------------------------------
    def disposable_storage_keys(self, failed_before: datetime) -> set[str]: ...

    def mark_storage_keys_pruned(self, keys: set[str], now: datetime) -> None: ...

    def purge_deleted_projects(self) -> int: ...

    def maintenance_lock(self) -> AbstractContextManager[bool]: ...
```

- [ ] **Step 2: Add the `store` fixture**

Append to `backend/tests/conftest.py`:
```python
from app.persistence.memory import InMemoryStore


@pytest.fixture(params=["memory"])
def store(request):
    """Every Store contract test runs once per implementation. Task 7 adds
    the "postgres" param."""
    return InMemoryStore()
```
(Put the import at the top of the file.)

- [ ] **Step 3: Write the failing contract tests (projects, analyses, scores)**

`backend/tests/test_store_contract.py`:
```python
from datetime import UTC, datetime, timedelta

import pytest

from app.persistence.models import JobStatus, NewAnalysis, ScoreVersionConflictError
from app.timing import BeatPoint, TempoMap
from app.transcription import DrumEvent, DrumInstrument

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
OWNER = "worker-a"
LEASE = 300


def create(store, key="youtube:abc", now=NOW, url="https://youtu.be/abc", title=None):
    return store.create_project_with_job(
        source_kind="youtube",
        source_url=url,
        source_key=key,
        title=title or url,
        max_attempts=3,
        now=now,
    )


def sample_analysis():
    raw = [DrumEvent(id="e1", time=0.1 + 0.2, instrument=DrumInstrument.KICK, provenance="drumscript")]
    quantized = [DrumEvent(id="e1", time=0.1 + 0.2, instrument=DrumInstrument.KICK, provenance="drumscript", measure=1, beat=1, subdivision=0)]
    return NewAnalysis(
        pipeline_version="1",
        tempo_bpm=120.0,
        tempo_map=TempoMap.constant(120.0),
        beats=[BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True), BeatPoint(source_time=0.5, measure=1, beat=2, is_downbeat=False)],
        events=quantized,
        raw_events=raw,
    )


def complete(store, job_id, now=NOW):
    store.claim_next_job(OWNER, LEASE, now)
    return store.complete_job(job_id, OWNER, sample_analysis(), now)


def test_create_project_with_job_returns_queued_job(store):
    project, job = create(store)

    assert project.source_key == "youtube:abc"
    assert project.title == "https://youtu.be/abc"
    assert project.created_at == NOW
    assert project.deleted_at is None
    assert job.project_id == project.id
    assert job.status == JobStatus.QUEUED
    assert job.attempts == 0
    assert job.max_attempts == 3
    assert job.available_at == NOW
    assert job.lease_owner is None
    assert job.correlation_id


def test_get_project_and_job_round_trip(store):
    project, job = create(store)

    assert store.get_project(project.id) == project
    assert store.get_job(job.id) == job
    assert store.latest_job(project.id) == job


def test_unknown_ids_return_none(store):
    missing = "00000000-0000-0000-0000-000000000000"

    assert store.get_project(missing) is None
    assert store.get_job(missing) is None
    assert store.latest_job(missing) is None
    assert store.latest_analysis(missing) is None
    assert store.latest_score(missing) is None


def test_find_live_project_by_source_key_ignores_deleted_and_other_sources(store):
    deleted, _ = create(store, now=NOW)
    store.soft_delete_project(deleted.id, NOW)
    live, _ = create(store, now=NOW + timedelta(minutes=1))
    create(store, key="youtube:other")

    assert store.find_live_project_by_source_key("youtube:abc") == store.get_project(live.id)
    assert store.find_live_project_by_source_key("youtube:none") is None


def test_list_live_projects_most_recently_updated_first_with_status_and_edit_flag(store):
    edited, edited_job = create(store, key="youtube:a", now=NOW)
    analysis = complete(store, edited_job.id, now=NOW + timedelta(minutes=1))
    untouched, _ = create(store, key="youtube:b", now=NOW + timedelta(minutes=2))
    store.save_score(edited.id, analysis.id, {"measures": []}, None, NOW + timedelta(minutes=3))
    gone, _ = create(store, key="youtube:c", now=NOW + timedelta(minutes=4))
    store.soft_delete_project(gone.id, NOW + timedelta(minutes=5))

    summaries = store.list_live_projects()

    assert [s.project.id for s in summaries] == [edited.id, untouched.id]
    assert summaries[0].latest_job_status == JobStatus.COMPLETED
    assert summaries[0].has_edits is True
    assert summaries[1].latest_job_status == JobStatus.QUEUED
    assert summaries[1].has_edits is False


def test_set_project_title_updates_title_and_timestamp(store):
    project, _ = create(store)

    store.set_project_title(project.id, "Song Title", NOW + timedelta(seconds=5))

    updated = store.get_project(project.id)
    assert updated.title == "Song Title"
    assert updated.updated_at == NOW + timedelta(seconds=5)


def test_soft_delete_project_marks_once(store):
    project, _ = create(store)

    first = store.soft_delete_project(project.id, NOW)
    second = store.soft_delete_project(project.id, NOW)

    assert first is True
    assert second is False
    assert store.get_project(project.id).deleted_at == NOW
    assert store.soft_delete_project("00000000-0000-0000-0000-000000000000", NOW) is False


def test_complete_job_persists_analysis_with_exact_source_times(store):
    project, job = create(store)

    analysis = complete(store, job.id)

    loaded = store.latest_analysis(project.id)
    assert loaded == analysis
    assert loaded.job_id == job.id
    assert loaded.events[0].time == 0.1 + 0.2
    assert loaded.raw_events[0].measure is None
    assert loaded.beats == sample_analysis().beats
    assert loaded.tempo_map == TempoMap.constant(120.0)


def test_save_score_versions_increase_and_latest_is_returned(store):
    project, job = create(store)
    analysis = complete(store, job.id)

    first = store.save_score(project.id, analysis.id, {"measures": [["a"]]}, None, NOW)
    second = store.save_score(project.id, analysis.id, {"measures": [["b"]]}, 1, NOW + timedelta(seconds=1))

    assert first.version == 1
    assert second.version == 2
    assert store.latest_score(project.id) == second
    assert store.latest_score(project.id).score == {"measures": [["b"]]}


def test_save_score_with_stale_base_version_conflicts(store):
    project, job = create(store)
    analysis = complete(store, job.id)
    store.save_score(project.id, analysis.id, {"measures": []}, None, NOW)
    store.save_score(project.id, analysis.id, {"measures": []}, 1, NOW)

    with pytest.raises(ScoreVersionConflictError) as error:
        store.save_score(project.id, analysis.id, {"measures": []}, 1, NOW)

    assert error.value.latest_version == 2


def test_first_save_with_a_base_version_conflicts(store):
    project, job = create(store)
    analysis = complete(store, job.id)

    with pytest.raises(ScoreVersionConflictError) as error:
        store.save_score(project.id, analysis.id, {"measures": []}, 3, NOW)

    assert error.value.latest_version is None
```

- [ ] **Step 4: Run to verify it fails**

Run: `uv run pytest tests/test_store_contract.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.persistence.memory'`.

- [ ] **Step 5: Implement `InMemoryStore` (this task's surface plus the minimum claim/complete the tests use)**

`backend/app/persistence/memory.py`:
```python
import copy
import dataclasses
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from app.persistence.models import (
    TERMINAL_STATUSES,
    Analysis,
    Artifact,
    ArtifactKind,
    CacheEntry,
    Job,
    JobStatus,
    LeaseLostError,
    NewAnalysis,
    NewArtifact,
    Project,
    ProjectSummary,
    ScoreVersion,
    ScoreVersionConflictError,
    Stage,
    new_id,
)


class InMemoryStore:
    """Thread-safe in-process Store used by unit tests. Honours exactly the
    same contract as PostgresStore (tests/test_store_contract.py runs
    against both)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._maintenance = threading.Lock()
        self._projects: dict[str, Project] = {}
        self._jobs: dict[str, Job] = {}
        self._artifacts: dict[str, Artifact] = {}
        self._analyses: dict[str, Analysis] = {}
        self._scores: list[ScoreVersion] = []
        self._cache: dict[tuple[str, Stage, str], CacheEntry] = {}

    # --- projects -------------------------------------------------------
    def create_project_with_job(self, *, source_kind, source_url, source_key, title, max_attempts, now):
        with self._lock:
            project = Project(
                id=new_id(),
                title=title,
                source_kind=source_kind,
                source_url=source_url,
                source_key=source_key,
                created_at=now,
                updated_at=now,
            )
            job = Job(
                id=new_id(),
                project_id=project.id,
                status=JobStatus.QUEUED,
                attempts=0,
                max_attempts=max_attempts,
                available_at=now,
                correlation_id=new_id(),
                created_at=now,
                updated_at=now,
            )
            self._projects[project.id] = project
            self._jobs[job.id] = job
            return project, job

    def get_project(self, project_id):
        with self._lock:
            return self._projects.get(project_id)

    def find_live_project_by_source_key(self, source_key):
        with self._lock:
            matches = [p for p in self._projects.values() if p.source_key == source_key and p.deleted_at is None]
            return max(matches, key=lambda p: p.created_at, default=None)

    def list_live_projects(self):
        with self._lock:
            live = [p for p in self._projects.values() if p.deleted_at is None]
            live.sort(key=lambda p: (p.updated_at, p.created_at), reverse=True)
            summaries = []
            for project in live:
                job = self.latest_job(project.id)
                summaries.append(
                    ProjectSummary(
                        project=project,
                        latest_job_status=job.status if job else None,
                        has_edits=any(s.project_id == project.id for s in self._scores),
                    )
                )
            return summaries

    def set_project_title(self, project_id, title, now):
        with self._lock:
            self._touch_project(project_id, now, title=title)

    def soft_delete_project(self, project_id, now):
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.deleted_at is not None:
                return False
            self._projects[project_id] = dataclasses.replace(project, deleted_at=now, updated_at=now)
            return True

    def _touch_project(self, project_id: str, now: datetime, **changes: Any) -> None:
        project = self._projects[project_id]
        self._projects[project_id] = dataclasses.replace(project, updated_at=now, **changes)

    # --- jobs / queue -----------------------------------------------------
    def get_job(self, job_id):
        with self._lock:
            return self._jobs.get(job_id)

    def latest_job(self, project_id):
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.project_id == project_id]
            return max(jobs, key=lambda j: j.created_at, default=None)

    def claim_next_job(self, owner, lease_seconds, now):
        with self._lock:
            candidates = [
                j
                for j in self._jobs.values()
                if j.status not in TERMINAL_STATUSES
                and j.available_at <= now
                and (j.lease_expires_at is None or j.lease_expires_at < now)
            ]
            if not candidates:
                return None
            job = min(candidates, key=lambda j: j.created_at)
            claimed = dataclasses.replace(
                job,
                lease_owner=owner,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                attempts=job.attempts + 1,
                updated_at=now,
            )
            self._jobs[job.id] = claimed
            return claimed

    def _owned(self, job_id: str, owner: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None or job.lease_owner != owner:
            raise LeaseLostError(job_id)
        return job

    def complete_job(self, job_id, owner, analysis: NewAnalysis, now):
        with self._lock:
            job = self._owned(job_id, owner)
            stored = Analysis(
                id=new_id(),
                project_id=job.project_id,
                job_id=job.id,
                pipeline_version=analysis.pipeline_version,
                tempo_bpm=analysis.tempo_bpm,
                tempo_map=analysis.tempo_map,
                beats=list(analysis.beats),
                events=list(analysis.events),
                raw_events=list(analysis.raw_events),
                created_at=now,
            )
            self._analyses[stored.id] = stored
            self._jobs[job_id] = dataclasses.replace(
                job,
                status=JobStatus.COMPLETED,
                error=None,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )
            self._touch_project(job.project_id, now)
            return stored

    # --- analyses / scores ------------------------------------------------
    def latest_analysis(self, project_id):
        with self._lock:
            analyses = [a for a in self._analyses.values() if a.project_id == project_id]
            return max(analyses, key=lambda a: a.created_at, default=None)

    def latest_score(self, project_id):
        with self._lock:
            scores = [s for s in self._scores if s.project_id == project_id]
            return max(scores, key=lambda s: s.version, default=None)

    def save_score(self, project_id, analysis_id, score, base_version, now):
        with self._lock:
            latest = self.latest_score(project_id)
            latest_version = latest.version if latest else None
            if base_version != latest_version:
                raise ScoreVersionConflictError(latest_version)
            saved = ScoreVersion(
                id=new_id(),
                project_id=project_id,
                analysis_id=analysis_id,
                version=(latest_version or 0) + 1,
                score=copy.deepcopy(score),
                created_at=now,
            )
            self._scores.append(saved)
            self._touch_project(project_id, now)
            return saved
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/test_store_contract.py -v`
Expected: 11 passed.

- [ ] **Step 7: Commit (checkpoint)**

```bash
git add backend/app/persistence/store.py backend/app/persistence/memory.py backend/tests/conftest.py backend/tests/test_store_contract.py
git commit -m "feat(backend): add Store protocol and in-memory store for projects, analyses and scores"
```

---

### Task 4: Queue operations (claim, lease, stage commit, fail, retry)

**Files:**
- Modify: `backend/app/persistence/memory.py`
- Test: `backend/tests/test_store_contract.py` (append)

**Interfaces:**
- Consumes: `create`, `NOW`, `OWNER`, `LEASE`, `complete` helpers from Task 3's test module.
- Produces: `InMemoryStore.extend_lease`, `release_lease`, `set_job_status`, `commit_stage`, `fail_job`, `schedule_retry`, `requeue_failed_job`, `artifacts_for_job`, `get_cache_entry` with the semantics tested below.

- [ ] **Step 1: Write the failing contract tests**

Append to `backend/tests/test_store_contract.py` (add `ArtifactKind, CacheEntry, LeaseLostError, NewArtifact, Stage` to the models import):
```python
def descriptor(kind=ArtifactKind.SOURCE_AUDIO, key="projects/p/j/source.wav"):
    return NewArtifact(kind=kind, storage_key=key, size_bytes=4, sha256="deadbeef")


def test_claim_takes_oldest_available_job_and_starts_a_lease(store):
    _, first = create(store, key="youtube:a", now=NOW)
    create(store, key="youtube:b", now=NOW + timedelta(seconds=1))

    claimed = store.claim_next_job(OWNER, LEASE, NOW + timedelta(seconds=2))

    assert claimed.id == first.id
    assert claimed.lease_owner == OWNER
    assert claimed.lease_expires_at == NOW + timedelta(seconds=2 + LEASE)
    assert claimed.attempts == 1
    assert store.get_job(first.id) == claimed


def test_claim_skips_leased_future_and_terminal_jobs(store):
    _, leased = create(store, key="youtube:a")
    store.claim_next_job(OWNER, LEASE, NOW)
    _, later = create(store, key="youtube:b")
    store.claim_next_job("other", LEASE, NOW)
    store.schedule_retry(later.id, "other", "boom", NOW + timedelta(minutes=5), NOW)
    _, done = create(store, key="youtube:c")
    complete(store, done.id)

    assert store.claim_next_job("third", LEASE, NOW + timedelta(seconds=1)) is None


def test_expired_lease_can_be_reclaimed_by_another_worker(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    reclaimed = store.claim_next_job("worker-b", LEASE, NOW + timedelta(seconds=LEASE + 1))

    assert reclaimed.id == job.id
    assert reclaimed.lease_owner == "worker-b"
    assert reclaimed.attempts == 2


def test_extend_lease_only_for_current_owner(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    extended = store.extend_lease(job.id, OWNER, LEASE, NOW + timedelta(seconds=60))
    stolen = store.extend_lease(job.id, "intruder", LEASE, NOW + timedelta(seconds=60))

    assert extended is True
    assert stolen is False
    assert store.get_job(job.id).lease_expires_at == NOW + timedelta(seconds=60 + LEASE)


def test_release_lease_makes_job_claimable_immediately(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    store.release_lease(job.id, OWNER, NOW + timedelta(seconds=1))

    released = store.get_job(job.id)
    assert released.lease_owner is None
    assert released.lease_expires_at is None
    assert store.claim_next_job("worker-b", LEASE, NOW + timedelta(seconds=1)).id == job.id


def test_mutations_by_non_owner_raise_lease_lost(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    with pytest.raises(LeaseLostError):
        store.set_job_status(job.id, "intruder", JobStatus.DOWNLOADING, NOW)
    with pytest.raises(LeaseLostError):
        store.commit_stage(job.id, "intruder", JobStatus.DOWNLOADED, [descriptor()], None, NOW)
    with pytest.raises(LeaseLostError):
        store.complete_job(job.id, "intruder", sample_analysis(), NOW)
    with pytest.raises(LeaseLostError):
        store.fail_job(job.id, "intruder", "x", NOW)
    with pytest.raises(LeaseLostError):
        store.schedule_retry(job.id, "intruder", "x", NOW, NOW)


def test_set_job_status_updates_status(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    store.set_job_status(job.id, OWNER, JobStatus.DOWNLOADING, NOW + timedelta(seconds=1))

    updated = store.get_job(job.id)
    assert updated.status == JobStatus.DOWNLOADING
    assert updated.updated_at == NOW + timedelta(seconds=1)


def test_commit_stage_records_artifacts_status_and_cache_atomically(store):
    project, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)
    drums = descriptor(ArtifactKind.DRUMS_STEM, "projects/p/j/drums.wav")
    accompaniment = descriptor(ArtifactKind.ACCOMPANIMENT_STEM, "projects/p/j/accompaniment.wav")
    entry = CacheEntry(source_key="youtube:abc", stage=Stage.SEPARATE, pipeline_version="1", artifacts=(drums, accompaniment))

    created = store.commit_stage(job.id, OWNER, JobStatus.STEMS_SEPARATED, [drums, accompaniment], entry, NOW)

    assert store.get_job(job.id).status == JobStatus.STEMS_SEPARATED
    by_kind = store.artifacts_for_job(job.id)
    assert set(by_kind) == {ArtifactKind.DRUMS_STEM, ArtifactKind.ACCOMPANIMENT_STEM}
    assert by_kind[ArtifactKind.DRUMS_STEM].storage_key == "projects/p/j/drums.wav"
    assert by_kind[ArtifactKind.DRUMS_STEM].project_id == project.id
    assert by_kind[ArtifactKind.DRUMS_STEM].pruned_at is None
    assert {a.id for a in created} == {a.id for a in by_kind.values()}
    assert store.get_cache_entry("youtube:abc", Stage.SEPARATE, "1") == entry
    assert store.get_cache_entry("youtube:abc", Stage.SEPARATE, "2") is None


def test_commit_stage_failure_leaves_no_partial_state(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)
    store.claim_next_job("worker-b", LEASE, NOW + timedelta(seconds=LEASE + 1))

    with pytest.raises(LeaseLostError):
        store.commit_stage(job.id, OWNER, JobStatus.DOWNLOADED, [descriptor()], None, NOW)

    assert store.artifacts_for_job(job.id) == {}


def test_fail_job_is_terminal_and_clears_lease(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    store.fail_job(job.id, OWNER, "video unavailable", NOW + timedelta(seconds=3))

    failed = store.get_job(job.id)
    assert failed.status == JobStatus.FAILED
    assert failed.error == "video unavailable"
    assert failed.finished_at == NOW + timedelta(seconds=3)
    assert failed.lease_owner is None
    assert store.claim_next_job(OWNER, LEASE, NOW + timedelta(hours=1)) is None


def test_schedule_retry_delays_job_and_keeps_it_non_terminal(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)
    store.set_job_status(job.id, OWNER, JobStatus.SEPARATING_STEMS, NOW)

    store.schedule_retry(job.id, OWNER, "Unexpected error: oom", NOW + timedelta(seconds=30), NOW)

    retried = store.get_job(job.id)
    assert retried.status == JobStatus.SEPARATING_STEMS
    assert retried.error == "Unexpected error: oom"
    assert retried.lease_owner is None
    assert store.claim_next_job(OWNER, LEASE, NOW + timedelta(seconds=29)) is None
    assert store.claim_next_job(OWNER, LEASE, NOW + timedelta(seconds=30)).id == job.id


def test_requeue_failed_job_resets_attempts_and_error(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)
    store.fail_job(job.id, OWNER, "boom", NOW)

    requeued = store.requeue_failed_job(job.id, NOW + timedelta(minutes=1))

    assert requeued.status == JobStatus.QUEUED
    assert requeued.attempts == 0
    assert requeued.error is None
    assert requeued.finished_at is None
    assert requeued.available_at == NOW + timedelta(minutes=1)


def test_requeue_ignores_non_failed_and_unknown_jobs(store):
    _, job = create(store)

    assert store.requeue_failed_job(job.id, NOW) is None
    assert store.requeue_failed_job("00000000-0000-0000-0000-000000000000", NOW) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_store_contract.py -v`
Expected: new tests FAIL with `AttributeError: 'InMemoryStore' object has no attribute 'schedule_retry'` (and similar).

- [ ] **Step 3: Implement the queue operations**

Add to `InMemoryStore` (queue section, after `_owned`):
```python
    def extend_lease(self, job_id, owner, lease_seconds, now):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.lease_owner != owner:
                return False
            self._jobs[job_id] = dataclasses.replace(
                job, lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now
            )
            return True

    def release_lease(self, job_id, owner, now):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.lease_owner != owner:
                return
            self._jobs[job_id] = dataclasses.replace(
                job, lease_owner=None, lease_expires_at=None, available_at=now, updated_at=now
            )

    def set_job_status(self, job_id, owner, status, now):
        with self._lock:
            job = self._owned(job_id, owner)
            self._jobs[job_id] = dataclasses.replace(job, status=status, updated_at=now)

    def commit_stage(self, job_id, owner, status, artifacts: Sequence[NewArtifact], cache_entry, now):
        with self._lock:
            job = self._owned(job_id, owner)
            created = [
                Artifact(
                    id=new_id(),
                    project_id=job.project_id,
                    job_id=job.id,
                    kind=a.kind,
                    storage_key=a.storage_key,
                    size_bytes=a.size_bytes,
                    sha256=a.sha256,
                    created_at=now,
                )
                for a in artifacts
            ]
            for artifact in created:
                self._artifacts[artifact.id] = artifact
            if cache_entry is not None:
                self._cache[(cache_entry.source_key, cache_entry.stage, cache_entry.pipeline_version)] = cache_entry
            self._jobs[job_id] = dataclasses.replace(job, status=status, updated_at=now)
            return created

    def fail_job(self, job_id, owner, error, now):
        with self._lock:
            job = self._owned(job_id, owner)
            self._jobs[job_id] = dataclasses.replace(
                job,
                status=JobStatus.FAILED,
                error=error,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )

    def schedule_retry(self, job_id, owner, error, available_at, now):
        with self._lock:
            job = self._owned(job_id, owner)
            self._jobs[job_id] = dataclasses.replace(
                job, error=error, available_at=available_at, lease_owner=None, lease_expires_at=None, updated_at=now
            )

    def requeue_failed_job(self, job_id, now):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != JobStatus.FAILED:
                return None
            requeued = dataclasses.replace(
                job,
                status=JobStatus.QUEUED,
                attempts=0,
                error=None,
                available_at=now,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=None,
                updated_at=now,
            )
            self._jobs[job_id] = requeued
            return requeued

    # --- artifacts / cache ------------------------------------------------
    def artifacts_for_job(self, job_id):
        with self._lock:
            by_kind: dict[ArtifactKind, Artifact] = {}
            for artifact in sorted(self._artifacts.values(), key=lambda a: a.created_at):
                if artifact.job_id == job_id:
                    by_kind[artifact.kind] = artifact
            return by_kind

    def get_cache_entry(self, source_key, stage, pipeline_version):
        with self._lock:
            return self._cache.get((source_key, stage, pipeline_version))
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_store_contract.py -v`
Expected: all passed (11 + 14).

- [ ] **Step 5: Commit (checkpoint)**

```bash
git add backend/app/persistence/memory.py backend/tests/test_store_contract.py
git commit -m "feat(backend): add lease-based queue operations to the in-memory store"
```

---

### Task 5: Lifecycle queries (disposable keys, pruning, purge, maintenance lock)

**Files:**
- Modify: `backend/app/persistence/memory.py`
- Test: `backend/tests/test_store_contract.py` (append)

**Interfaces:**
- Produces: `disposable_storage_keys(failed_before) -> set[str]`, `mark_storage_keys_pruned(keys, now)`, `purge_deleted_projects() -> int`, `maintenance_lock()` context manager yielding `bool`.
- Rule: a storage key is disposable when it has at least one unpruned artifact row and **every** unpruned row that references it is disposable. A row is disposable if its project is soft-deleted, OR its job is `failed` with `finished_at < failed_before`, OR it is `source_audio` of a `completed` job.

- [ ] **Step 1: Write the failing contract tests**

Append:
```python
def run_stage(store, job_id, artifacts, owner=OWNER, now=NOW, cache_entry=None):
    store.claim_next_job(owner, LEASE, now)
    return store.commit_stage(job_id, owner, JobStatus.DOWNLOADED, artifacts, cache_entry, now)


def test_source_audio_of_completed_job_is_disposable_but_stems_are_not(store):
    _, job = create(store)
    run_stage(store, job.id, [descriptor(), descriptor(ArtifactKind.DRUMS_STEM, "k/drums.wav")])
    store.complete_job(job.id, OWNER, sample_analysis(), NOW)

    keys = store.disposable_storage_keys(failed_before=NOW - timedelta(days=7))

    assert keys == {"projects/p/j/source.wav"}


def test_failed_job_artifacts_are_disposable_only_after_retention(store):
    _, job = create(store)
    run_stage(store, job.id, [descriptor(ArtifactKind.DRUMS_STEM, "k/drums.wav")])
    store.fail_job(job.id, OWNER, "boom", NOW)

    assert store.disposable_storage_keys(failed_before=NOW) == set()
    assert store.disposable_storage_keys(failed_before=NOW + timedelta(seconds=1)) == {"k/drums.wav"}


def test_deleted_project_artifacts_are_disposable(store):
    project, job = create(store)
    run_stage(store, job.id, [descriptor(ArtifactKind.DRUMS_STEM, "k/drums.wav")])
    store.soft_delete_project(project.id, NOW)

    assert store.disposable_storage_keys(failed_before=NOW) == {"k/drums.wav"}


def test_key_shared_with_a_live_row_is_not_disposable(store):
    deleted, deleted_job = create(store, key="youtube:abc", now=NOW)
    run_stage(store, deleted_job.id, [descriptor(ArtifactKind.DRUMS_STEM, "shared/drums.wav")])
    store.complete_job(deleted_job.id, OWNER, sample_analysis(), NOW)
    store.soft_delete_project(deleted.id, NOW)
    _, live_job = create(store, key="youtube:abc", now=NOW + timedelta(seconds=1))
    run_stage(store, live_job.id, [descriptor(ArtifactKind.DRUMS_STEM, "shared/drums.wav")], now=NOW + timedelta(seconds=1))

    assert store.disposable_storage_keys(failed_before=NOW + timedelta(days=1)) == set()


def test_mark_pruned_sets_pruned_at_and_drops_referencing_cache_entries(store):
    _, job = create(store)
    source = descriptor()
    entry = CacheEntry(source_key="youtube:abc", stage=Stage.EXTRACT, pipeline_version="1", artifacts=(source,))
    run_stage(store, job.id, [source], cache_entry=entry)

    store.mark_storage_keys_pruned({"projects/p/j/source.wav"}, NOW + timedelta(hours=1))

    artifact = store.artifacts_for_job(job.id)[ArtifactKind.SOURCE_AUDIO]
    assert artifact.pruned_at == NOW + timedelta(hours=1)
    assert store.get_cache_entry("youtube:abc", Stage.EXTRACT, "1") is None
    assert store.disposable_storage_keys(failed_before=NOW + timedelta(days=30)) == set()


def test_mark_pruned_with_no_keys_is_a_no_op(store):
    store.mark_storage_keys_pruned(set(), NOW)


def test_purge_deleted_projects_removes_their_rows(store):
    doomed, doomed_job = create(store, key="youtube:a")
    kept, _ = create(store, key="youtube:b")
    analysis = complete(store, doomed_job.id)
    store.save_score(doomed.id, analysis.id, {"measures": []}, None, NOW)
    store.soft_delete_project(doomed.id, NOW)

    purged = store.purge_deleted_projects()

    assert purged == 1
    assert store.get_project(doomed.id) is None
    assert store.get_job(doomed_job.id) is None
    assert store.latest_analysis(doomed.id) is None
    assert store.latest_score(doomed.id) is None
    assert store.get_project(kept.id) is not None


def test_maintenance_lock_is_exclusive(store):
    with store.maintenance_lock() as first:
        with store.maintenance_lock() as second:
            assert first is True
            assert second is False

    with store.maintenance_lock() as again:
        assert again is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_store_contract.py -v`
Expected: new tests FAIL with `AttributeError … 'disposable_storage_keys'`.

- [ ] **Step 3: Implement**

Add to `InMemoryStore`:
```python
    # --- lifecycle ----------------------------------------------------------
    def _row_is_disposable(self, artifact: Artifact, failed_before: datetime) -> bool:
        project = self._projects[artifact.project_id]
        job = self._jobs[artifact.job_id]
        if project.deleted_at is not None:
            return True
        if job.status == JobStatus.FAILED and job.finished_at is not None and job.finished_at < failed_before:
            return True
        return artifact.kind == ArtifactKind.SOURCE_AUDIO and job.status == JobStatus.COMPLETED

    def disposable_storage_keys(self, failed_before):
        with self._lock:
            rows_by_key: dict[str, list[Artifact]] = {}
            for artifact in self._artifacts.values():
                if artifact.pruned_at is None:
                    rows_by_key.setdefault(artifact.storage_key, []).append(artifact)
            return {
                key
                for key, rows in rows_by_key.items()
                if all(self._row_is_disposable(row, failed_before) for row in rows)
            }

    def mark_storage_keys_pruned(self, keys, now):
        with self._lock:
            for artifact_id, artifact in list(self._artifacts.items()):
                if artifact.storage_key in keys and artifact.pruned_at is None:
                    self._artifacts[artifact_id] = dataclasses.replace(artifact, pruned_at=now)
            self._cache = {
                cache_key: entry
                for cache_key, entry in self._cache.items()
                if not any(a.storage_key in keys for a in entry.artifacts)
            }

    def purge_deleted_projects(self):
        with self._lock:
            doomed = {pid for pid, p in self._projects.items() if p.deleted_at is not None}
            self._projects = {pid: p for pid, p in self._projects.items() if pid not in doomed}
            self._jobs = {jid: j for jid, j in self._jobs.items() if j.project_id not in doomed}
            self._artifacts = {aid: a for aid, a in self._artifacts.items() if a.project_id not in doomed}
            self._analyses = {aid: a for aid, a in self._analyses.items() if a.project_id not in doomed}
            self._scores = [s for s in self._scores if s.project_id not in doomed]
            return len(doomed)

    @contextmanager
    def maintenance_lock(self) -> Iterator[bool]:
        acquired = self._maintenance.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                self._maintenance.release()
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_store_contract.py -v`
Expected: all passed.

- [ ] **Step 5: Commit (checkpoint)**

```bash
git add backend/app/persistence/memory.py backend/tests/test_store_contract.py
git commit -m "feat(backend): add artifact lifecycle queries to the in-memory store"
```

---

### Task 6: Postgres schema — SQLAlchemy tables and Alembic migration

**Files:**
- Create: `backend/app/persistence/tables.py`, `backend/app/persistence/migrations.py`, `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`, `backend/migrations/versions/0001_initial_schema.py`, `backend/tests/test_migrations.py`
- Modify: `backend/tests/conftest.py` (add `fresh_database_url`)

**Interfaces:**
- Produces: `app.persistence.tables.metadata` and table objects `projects`, `jobs`, `artifacts`, `analyses`, `score_versions`, `stage_cache`; `app.persistence.migrations.upgrade_to_head(database_url: str) -> None`, `downgrade_to_base(database_url: str) -> None`; fixture `fresh_database_url` (a new empty database per test).

- [ ] **Step 1: Write the failing migration tests**

Add to `backend/tests/conftest.py`:
```python
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture
def fresh_database_url(postgres_url):
    """A brand-new empty database on the session container, dropped after
    the test - for tests that must start from (or return to) an empty
    schema without disturbing the shared test database."""
    name = f"t_{uuid.uuid4().hex}"
    admin = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(postgres_url).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
```

`backend/tests/test_migrations.py`:
```python
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.persistence.migrations import downgrade_to_base, upgrade_to_head
from app.persistence.tables import metadata

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {"projects", "jobs", "artifacts", "analyses", "score_versions", "stage_cache"}


def table_names(url):
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_upgrade_from_empty_creates_every_table(fresh_database_url):
    upgrade_to_head(fresh_database_url)

    assert table_names(fresh_database_url) == EXPECTED_TABLES


def test_migrated_schema_matches_sqlalchemy_metadata(fresh_database_url):
    upgrade_to_head(fresh_database_url)
    engine = create_engine(fresh_database_url)

    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), metadata)
    engine.dispose()

    assert diff == []


def test_downgrade_then_upgrade_round_trips(fresh_database_url):
    upgrade_to_head(fresh_database_url)

    downgrade_to_base(fresh_database_url)
    emptied = table_names(fresh_database_url)
    upgrade_to_head(fresh_database_url)

    assert emptied == set()
    assert table_names(fresh_database_url) == EXPECTED_TABLES
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_migrations.py -v` (Docker must be running)
Expected: FAIL, `ModuleNotFoundError: No module named 'app.persistence.migrations'`.

- [ ] **Step 3: Write the tables**

`backend/app/persistence/tables.py`:
```python
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

# Schema source of truth for PostgresStore. Alembic migrations in
# backend/migrations must keep the database identical to this metadata
# (tests/test_migrations.py compares them).
metadata = MetaData()


def _timestamp(name: str, nullable: bool = False) -> Column:
    return Column(name, DateTime(timezone=True), nullable=nullable)


projects = Table(
    "projects",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("title", Text, nullable=False),
    Column("source_kind", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("source_key", Text, nullable=False),
    _timestamp("created_at"),
    _timestamp("updated_at"),
    _timestamp("deleted_at", nullable=True),
    Index("ix_projects_source_key", "source_key"),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("status", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    _timestamp("available_at"),
    Column("lease_owner", Text, nullable=True),
    _timestamp("lease_expires_at", nullable=True),
    Column("error", Text, nullable=True),
    Column("correlation_id", Uuid(as_uuid=False), nullable=False),
    _timestamp("created_at"),
    _timestamp("updated_at"),
    _timestamp("finished_at", nullable=True),
    Index("ix_jobs_project_id", "project_id"),
    Index("ix_jobs_claim", "status", "available_at"),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("job_id", Uuid(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("sha256", Text, nullable=False),
    _timestamp("created_at"),
    _timestamp("pruned_at", nullable=True),
    Index("ix_artifacts_job_id", "job_id"),
    Index("ix_artifacts_storage_key", "storage_key"),
)

analyses = Table(
    "analyses",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("job_id", Uuid(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
    Column("pipeline_version", Text, nullable=False),
    Column("tempo_bpm", Double, nullable=False),
    Column("tempo_map", JSONB, nullable=False),
    Column("beats", JSONB, nullable=False),
    Column("events", JSONB, nullable=False),
    Column("raw_events", JSONB, nullable=False),
    _timestamp("created_at"),
    UniqueConstraint("job_id", name="uq_analyses_job_id"),
    Index("ix_analyses_project_id", "project_id"),
)

score_versions = Table(
    "score_versions",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("analysis_id", Uuid(as_uuid=False), ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("score", JSONB, nullable=False),
    _timestamp("created_at"),
    UniqueConstraint("project_id", "version", name="uq_score_versions_project_version"),
)

stage_cache = Table(
    "stage_cache",
    metadata,
    Column("source_key", Text, nullable=False),
    Column("stage", Text, nullable=False),
    Column("pipeline_version", Text, nullable=False),
    Column("artifacts", JSONB, nullable=False),
    _timestamp("created_at"),
    PrimaryKeyConstraint("source_key", "stage", "pipeline_version", name="pk_stage_cache"),
)
```

- [ ] **Step 4: Alembic config, env and helpers**

`backend/alembic.ini`:
```ini
[alembic]
script_location = %(here)s/migrations
path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

`backend/migrations/env.py`:
```python
from alembic import context
from sqlalchemy import create_engine

from app.config import get_settings
from app.persistence.tables import metadata

config = context.config
database_url = config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_online() -> None:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
```

`backend/migrations/script.py.mako`:
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`backend/app/persistence/migrations.py`:
```python
from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def _config(database_url: str) -> Config:
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    # configparser interpolation treats '%' specially (e.g. url-encoded passwords).
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(_config(database_url), "head")


def downgrade_to_base(database_url: str) -> None:
    command.downgrade(_config(database_url), "base")
```

- [ ] **Step 5: Write the initial migration**

`backend/migrations/versions/0001_initial_schema.py`:
```python
"""initial schema: projects, jobs, artifacts, analyses, score_versions, stage_cache

Revision ID: 0001
Revises:
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("deleted_at", nullable=True),
    )
    op.create_index("ix_projects_source_key", "projects", ["source_key"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        _ts("available_at"),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        _ts("lease_expires_at", nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(as_uuid=False), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("finished_at", nullable=True),
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])
    op.create_index("ix_jobs_claim", "jobs", ["status", "available_at"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=False), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        _ts("created_at"),
        _ts("pruned_at", nullable=True),
    )
    op.create_index("ix_artifacts_job_id", "artifacts", ["job_id"])
    op.create_index("ix_artifacts_storage_key", "artifacts", ["storage_key"])

    op.create_table(
        "analyses",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=False), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("tempo_bpm", sa.Double(), nullable=False),
        sa.Column("tempo_map", postgresql.JSONB(), nullable=False),
        sa.Column("beats", postgresql.JSONB(), nullable=False),
        sa.Column("events", postgresql.JSONB(), nullable=False),
        sa.Column("raw_events", postgresql.JSONB(), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("job_id", name="uq_analyses_job_id"),
    )
    op.create_index("ix_analyses_project_id", "analyses", ["project_id"])

    op.create_table(
        "score_versions",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analysis_id", sa.Uuid(as_uuid=False), sa.ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("score", postgresql.JSONB(), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("project_id", "version", name="uq_score_versions_project_version"),
    )

    op.create_table(
        "stage_cache",
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("artifacts", postgresql.JSONB(), nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("source_key", "stage", "pipeline_version", name="pk_stage_cache"),
    )


def downgrade() -> None:
    op.drop_table("stage_cache")
    op.drop_table("score_versions")
    op.drop_table("analyses")
    op.drop_table("artifacts")
    op.drop_table("jobs")
    op.drop_table("projects")
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: 3 passed. If `compare_metadata` reports a diff (for example an index or constraint name), fix the **migration** so it matches `tables.py`, not the other way round, then re-run.

- [ ] **Step 7: Commit (checkpoint)**

```bash
git add backend/alembic.ini backend/migrations backend/app/persistence/tables.py backend/app/persistence/migrations.py backend/tests/conftest.py backend/tests/test_migrations.py
git commit -m "feat(backend): add Postgres schema and initial Alembic migration"
```

---

### Task 7: PostgresStore passing the shared contract suite

**Files:**
- Create: `backend/app/persistence/postgres.py`
- Modify: `backend/tests/conftest.py` (`store` fixture gains the `postgres` param)
- Test: `backend/tests/test_store_contract.py` (append two Postgres-specific tests)

**Interfaces:**
- Consumes: `tables.*`, `serialization.*`, `models.*`, `upgrade_to_head`.
- Produces: `PostgresStore(engine: sqlalchemy.Engine)` implementing every `Store` method; `create_postgres_store(database_url: str) -> PostgresStore` (creates the engine with `pool_pre_ping=True`). Fixture `postgres_store` (function-scoped, truncated DB).

- [ ] **Step 1: Extend the fixtures**

In `backend/tests/conftest.py` replace the `store` fixture with:
```python
from app.persistence.migrations import upgrade_to_head
from app.persistence.postgres import create_postgres_store

TABLES = "stage_cache, score_versions, analyses, artifacts, jobs, projects"


@pytest.fixture(scope="session")
def migrated_postgres_url(postgres_url):
    upgrade_to_head(postgres_url)
    return postgres_url


@pytest.fixture
def postgres_store(migrated_postgres_url):
    store = create_postgres_store(migrated_postgres_url)
    with store.engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    yield store
    store.engine.dispose()


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def store(request):
    """Every Store contract test runs once per implementation."""
    if request.param == "memory":
        return InMemoryStore()
    return request.getfixturevalue("postgres_store")
```

- [ ] **Step 2: Add Postgres-specific tests and run the suite to see Postgres fail**

Append to `backend/tests/test_store_contract.py`:
```python
import threading


@pytest.mark.integration
def test_concurrent_claims_hand_a_job_to_exactly_one_worker(postgres_store):
    create(postgres_store)
    barrier = threading.Barrier(8)
    results = []

    def claim(owner):
        barrier.wait()
        results.append(postgres_store.claim_next_job(owner, LEASE, NOW))

    threads = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len([r for r in results if r is not None]) == 1


@pytest.mark.integration
def test_concurrent_saves_from_same_base_version_conflict(postgres_store):
    project, job = create(postgres_store)
    analysis = complete(postgres_store, job.id)
    barrier = threading.Barrier(4)
    outcomes = []

    def save():
        barrier.wait()
        try:
            outcomes.append(postgres_store.save_score(project.id, analysis.id, {"measures": []}, None, NOW).version)
        except ScoreVersionConflictError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=save) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes, key=str) == [1, "conflict", "conflict", "conflict"]
```

Run: `uv run pytest tests/test_store_contract.py -v`
Expected: every `[postgres]` case FAILS with `ModuleNotFoundError: No module named 'app.persistence.postgres'` (memory cases still pass).

- [ ] **Step 3: Implement `PostgresStore`**

`backend/app/persistence/postgres.py`:
```python
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, bindparam, create_engine, delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text

from app.persistence import tables as t
from app.persistence.models import (
    Analysis,
    Artifact,
    ArtifactKind,
    CacheEntry,
    Job,
    JobStatus,
    LeaseLostError,
    NewAnalysis,
    NewArtifact,
    Project,
    ProjectSummary,
    ScoreVersion,
    ScoreVersionConflictError,
    Stage,
    new_id,
)
from app.persistence.serialization import (
    artifact_from_dict,
    artifact_to_dict,
    beat_from_dict,
    beat_to_dict,
    event_from_dict,
    event_to_dict,
    tempo_map_from_dict,
    tempo_map_to_dict,
)

# Arbitrary constant identifying the pruner's advisory lock.
_MAINTENANCE_LOCK_KEY = 6_021_001

_CLAIM_SQL = text(
    """
    UPDATE jobs
    SET lease_owner = :owner, lease_expires_at = :lease_expires_at,
        attempts = attempts + 1, updated_at = :now
    WHERE id = (
        SELECT id FROM jobs
        WHERE status NOT IN ('completed', 'failed')
          AND available_at <= :now
          AND (lease_expires_at IS NULL OR lease_expires_at < :now)
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1)
    RETURNING *
    """
)

_DISPOSABLE_SQL = text(
    """
    SELECT a.storage_key
    FROM artifacts a
    JOIN jobs j ON j.id = a.job_id
    JOIN projects p ON p.id = a.project_id
    WHERE a.pruned_at IS NULL
    GROUP BY a.storage_key
    HAVING bool_and(
        p.deleted_at IS NOT NULL
        OR (j.status = 'failed' AND j.finished_at < :failed_before)
        OR (a.kind = 'source_audio' AND j.status = 'completed'))
    """
)

_DROP_CACHE_SQL = text(
    """
    DELETE FROM stage_cache
    WHERE EXISTS (
        SELECT 1 FROM jsonb_array_elements(stage_cache.artifacts) AS element
        WHERE element->>'storage_key' = ANY(:keys))
    """
).bindparams(bindparam("keys", type_=ARRAY(Text)))


def _project(row) -> Project:
    return Project(
        id=row.id,
        title=row.title,
        source_kind=row.source_kind,
        source_url=row.source_url,
        source_key=row.source_key,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


def _job(row) -> Job:
    return Job(
        id=str(row.id),
        project_id=str(row.project_id),
        status=JobStatus(row.status),
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        available_at=row.available_at,
        correlation_id=str(row.correlation_id),
        created_at=row.created_at,
        updated_at=row.updated_at,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        error=row.error,
        finished_at=row.finished_at,
    )


def _artifact(row) -> Artifact:
    return Artifact(
        id=row.id,
        project_id=row.project_id,
        job_id=row.job_id,
        kind=ArtifactKind(row.kind),
        storage_key=row.storage_key,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        created_at=row.created_at,
        pruned_at=row.pruned_at,
    )


def _analysis(row) -> Analysis:
    return Analysis(
        id=row.id,
        project_id=row.project_id,
        job_id=row.job_id,
        pipeline_version=row.pipeline_version,
        tempo_bpm=row.tempo_bpm,
        tempo_map=tempo_map_from_dict(row.tempo_map),
        beats=[beat_from_dict(b) for b in row.beats],
        events=[event_from_dict(e) for e in row.events],
        raw_events=[event_from_dict(e) for e in row.raw_events],
        created_at=row.created_at,
    )


def _score(row) -> ScoreVersion:
    return ScoreVersion(
        id=row.id,
        project_id=row.project_id,
        analysis_id=row.analysis_id,
        version=row.version,
        score=row.score,
        created_at=row.created_at,
    )


class PostgresStore:
    """Store backed by Postgres (schema: app.persistence.tables, owned by
    Alembic). Every public method is one transaction."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # --- projects -------------------------------------------------------
    def create_project_with_job(self, *, source_kind, source_url, source_key, title, max_attempts, now):
        project_id, job_id = new_id(), new_id()
        with self.engine.begin() as c:
            c.execute(
                insert(t.projects).values(
                    id=project_id,
                    title=title,
                    source_kind=source_kind,
                    source_url=source_url,
                    source_key=source_key,
                    created_at=now,
                    updated_at=now,
                )
            )
            c.execute(
                insert(t.jobs).values(
                    id=job_id,
                    project_id=project_id,
                    status=JobStatus.QUEUED.value,
                    attempts=0,
                    max_attempts=max_attempts,
                    available_at=now,
                    correlation_id=new_id(),
                    created_at=now,
                    updated_at=now,
                )
            )
            project = _project(c.execute(select(t.projects).where(t.projects.c.id == project_id)).one())
            job = _job(c.execute(select(t.jobs).where(t.jobs.c.id == job_id)).one())
        return project, job

    def get_project(self, project_id):
        with self.engine.connect() as c:
            row = c.execute(select(t.projects).where(t.projects.c.id == project_id)).one_or_none()
        return _project(row) if row else None

    def find_live_project_by_source_key(self, source_key):
        query = (
            select(t.projects)
            .where(t.projects.c.source_key == source_key, t.projects.c.deleted_at.is_(None))
            .order_by(t.projects.c.created_at.desc())
            .limit(1)
        )
        with self.engine.connect() as c:
            row = c.execute(query).one_or_none()
        return _project(row) if row else None

    def list_live_projects(self):
        latest_status = (
            select(t.jobs.c.status)
            .where(t.jobs.c.project_id == t.projects.c.id)
            .order_by(t.jobs.c.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        has_edits = select(func.count()).where(t.score_versions.c.project_id == t.projects.c.id).exists()
        query = (
            select(t.projects, latest_status.label("latest_status"), has_edits.label("has_edits"))
            .where(t.projects.c.deleted_at.is_(None))
            .order_by(t.projects.c.updated_at.desc(), t.projects.c.created_at.desc())
        )
        with self.engine.connect() as c:
            rows = c.execute(query).all()
        return [
            ProjectSummary(
                project=_project(row),
                latest_job_status=JobStatus(row.latest_status) if row.latest_status else None,
                has_edits=bool(row.has_edits),
            )
            for row in rows
        ]

    def set_project_title(self, project_id, title, now):
        with self.engine.begin() as c:
            c.execute(update(t.projects).where(t.projects.c.id == project_id).values(title=title, updated_at=now))

    def soft_delete_project(self, project_id, now):
        with self.engine.begin() as c:
            result = c.execute(
                update(t.projects)
                .where(t.projects.c.id == project_id, t.projects.c.deleted_at.is_(None))
                .values(deleted_at=now, updated_at=now)
            )
        return result.rowcount == 1

    # --- jobs / queue -----------------------------------------------------
    def get_job(self, job_id):
        with self.engine.connect() as c:
            row = c.execute(select(t.jobs).where(t.jobs.c.id == job_id)).one_or_none()
        return _job(row) if row else None

    def latest_job(self, project_id):
        query = select(t.jobs).where(t.jobs.c.project_id == project_id).order_by(t.jobs.c.created_at.desc()).limit(1)
        with self.engine.connect() as c:
            row = c.execute(query).one_or_none()
        return _job(row) if row else None

    def claim_next_job(self, owner, lease_seconds, now):
        with self.engine.begin() as c:
            row = c.execute(
                _CLAIM_SQL,
                {"owner": owner, "now": now, "lease_expires_at": now + timedelta(seconds=lease_seconds)},
            ).one_or_none()
        return _job(row) if row else None

    def _owned_update(self, c, job_id: str, owner: str, **values: Any) -> None:
        result = c.execute(
            update(t.jobs).where(t.jobs.c.id == job_id, t.jobs.c.lease_owner == owner).values(**values)
        )
        if result.rowcount != 1:
            raise LeaseLostError(job_id)

    def extend_lease(self, job_id, owner, lease_seconds, now):
        with self.engine.begin() as c:
            try:
                self._owned_update(
                    c, job_id, owner, lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now
                )
            except LeaseLostError:
                return False
        return True

    def release_lease(self, job_id, owner, now):
        with self.engine.begin() as c:
            c.execute(
                update(t.jobs)
                .where(t.jobs.c.id == job_id, t.jobs.c.lease_owner == owner)
                .values(lease_owner=None, lease_expires_at=None, available_at=now, updated_at=now)
            )

    def set_job_status(self, job_id, owner, status, now):
        with self.engine.begin() as c:
            self._owned_update(c, job_id, owner, status=status.value, updated_at=now)

    def commit_stage(self, job_id, owner, status, artifacts: Sequence[NewArtifact], cache_entry, now):
        with self.engine.begin() as c:
            self._owned_update(c, job_id, owner, status=status.value, updated_at=now)
            project_id = c.execute(select(t.jobs.c.project_id).where(t.jobs.c.id == job_id)).scalar_one()
            ids = [new_id() for _ in artifacts]
            if artifacts:
                c.execute(
                    insert(t.artifacts),
                    [
                        {
                            "id": artifact_id,
                            "project_id": project_id,
                            "job_id": job_id,
                            "kind": a.kind.value,
                            "storage_key": a.storage_key,
                            "size_bytes": a.size_bytes,
                            "sha256": a.sha256,
                            "created_at": now,
                        }
                        for artifact_id, a in zip(ids, artifacts)
                    ],
                )
            if cache_entry is not None:
                c.execute(
                    text(
                        """
                        INSERT INTO stage_cache (source_key, stage, pipeline_version, artifacts, created_at)
                        VALUES (:source_key, :stage, :pipeline_version, CAST(:artifacts AS JSONB), :now)
                        ON CONFLICT ON CONSTRAINT pk_stage_cache
                        DO UPDATE SET artifacts = EXCLUDED.artifacts, created_at = EXCLUDED.created_at
                        """
                    ),
                    {
                        "source_key": cache_entry.source_key,
                        "stage": cache_entry.stage.value,
                        "pipeline_version": cache_entry.pipeline_version,
                        "artifacts": _json([artifact_to_dict(a) for a in cache_entry.artifacts]),
                        "now": now,
                    },
                )
            rows = c.execute(select(t.artifacts).where(t.artifacts.c.id.in_(ids))).all() if ids else []
        return [_artifact(row) for row in rows]

    def complete_job(self, job_id, owner, analysis: NewAnalysis, now):
        analysis_id = new_id()
        with self.engine.begin() as c:
            self._owned_update(
                c,
                job_id,
                owner,
                status=JobStatus.COMPLETED.value,
                error=None,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )
            project_id = c.execute(select(t.jobs.c.project_id).where(t.jobs.c.id == job_id)).scalar_one()
            c.execute(
                insert(t.analyses).values(
                    id=analysis_id,
                    project_id=project_id,
                    job_id=job_id,
                    pipeline_version=analysis.pipeline_version,
                    tempo_bpm=analysis.tempo_bpm,
                    tempo_map=tempo_map_to_dict(analysis.tempo_map),
                    beats=[beat_to_dict(b) for b in analysis.beats],
                    events=[event_to_dict(e) for e in analysis.events],
                    raw_events=[event_to_dict(e) for e in analysis.raw_events],
                    created_at=now,
                )
            )
            c.execute(update(t.projects).where(t.projects.c.id == project_id).values(updated_at=now))
            row = c.execute(select(t.analyses).where(t.analyses.c.id == analysis_id)).one()
        return _analysis(row)

    def fail_job(self, job_id, owner, error, now):
        with self.engine.begin() as c:
            self._owned_update(
                c,
                job_id,
                owner,
                status=JobStatus.FAILED.value,
                error=error,
                lease_owner=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )

    def schedule_retry(self, job_id, owner, error, available_at, now):
        with self.engine.begin() as c:
            self._owned_update(
                c,
                job_id,
                owner,
                error=error,
                available_at=available_at,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=now,
            )

    def requeue_failed_job(self, job_id, now):
        with self.engine.begin() as c:
            row = c.execute(
                update(t.jobs)
                .where(t.jobs.c.id == job_id, t.jobs.c.status == JobStatus.FAILED.value)
                .values(
                    status=JobStatus.QUEUED.value,
                    attempts=0,
                    error=None,
                    available_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    finished_at=None,
                    updated_at=now,
                )
                .returning(t.jobs)
            ).one_or_none()
        return _job(row) if row else None

    # --- artifacts / cache ------------------------------------------------
    def artifacts_for_job(self, job_id):
        query = select(t.artifacts).where(t.artifacts.c.job_id == job_id).order_by(t.artifacts.c.created_at)
        with self.engine.connect() as c:
            rows = c.execute(query).all()
        return {ArtifactKind(row.kind): _artifact(row) for row in rows}

    def get_cache_entry(self, source_key, stage, pipeline_version):
        query = select(t.stage_cache).where(
            t.stage_cache.c.source_key == source_key,
            t.stage_cache.c.stage == stage.value,
            t.stage_cache.c.pipeline_version == pipeline_version,
        )
        with self.engine.connect() as c:
            row = c.execute(query).one_or_none()
        if row is None:
            return None
        return CacheEntry(
            source_key=row.source_key,
            stage=Stage(row.stage),
            pipeline_version=row.pipeline_version,
            artifacts=tuple(artifact_from_dict(a) for a in row.artifacts),
        )

    # --- analyses / scores ------------------------------------------------
    def latest_analysis(self, project_id):
        query = (
            select(t.analyses)
            .where(t.analyses.c.project_id == project_id)
            .order_by(t.analyses.c.created_at.desc())
            .limit(1)
        )
        with self.engine.connect() as c:
            row = c.execute(query).one_or_none()
        return _analysis(row) if row else None

    def latest_score(self, project_id):
        query = (
            select(t.score_versions)
            .where(t.score_versions.c.project_id == project_id)
            .order_by(t.score_versions.c.version.desc())
            .limit(1)
        )
        with self.engine.connect() as c:
            row = c.execute(query).one_or_none()
        return _score(row) if row else None

    def save_score(self, project_id, analysis_id, score, base_version, now):
        score_id = new_id()
        with self.engine.begin() as c:
            # Row lock on the project serialises concurrent saves so the
            # version check below cannot race.
            c.execute(select(t.projects.c.id).where(t.projects.c.id == project_id).with_for_update())
            latest_version = c.execute(
                select(func.max(t.score_versions.c.version)).where(t.score_versions.c.project_id == project_id)
            ).scalar_one()
            if base_version != latest_version:
                raise ScoreVersionConflictError(latest_version)
            c.execute(
                insert(t.score_versions).values(
                    id=score_id,
                    project_id=project_id,
                    analysis_id=analysis_id,
                    version=(latest_version or 0) + 1,
                    score=score,
                    created_at=now,
                )
            )
            c.execute(update(t.projects).where(t.projects.c.id == project_id).values(updated_at=now))
            row = c.execute(select(t.score_versions).where(t.score_versions.c.id == score_id)).one()
        return _score(row)

    # --- lifecycle ----------------------------------------------------------
    def disposable_storage_keys(self, failed_before):
        with self.engine.connect() as c:
            return set(c.execute(_DISPOSABLE_SQL, {"failed_before": failed_before}).scalars())

    def mark_storage_keys_pruned(self, keys, now):
        if not keys:
            return
        key_list = sorted(keys)
        with self.engine.begin() as c:
            c.execute(
                update(t.artifacts)
                .where(t.artifacts.c.storage_key.in_(key_list), t.artifacts.c.pruned_at.is_(None))
                .values(pruned_at=now)
            )
            c.execute(_DROP_CACHE_SQL, {"keys": key_list})

    def purge_deleted_projects(self):
        with self.engine.begin() as c:
            result = c.execute(delete(t.projects).where(t.projects.c.deleted_at.is_not(None)))
        return result.rowcount

    @contextmanager
    def maintenance_lock(self) -> Iterator[bool]:
        with self.engine.connect() as c:
            acquired = c.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _MAINTENANCE_LOCK_KEY}).scalar_one()
            c.commit()
            try:
                yield bool(acquired)
            finally:
                if acquired:
                    c.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _MAINTENANCE_LOCK_KEY})
                    c.commit()


def _json(value: Any) -> str:
    return json.dumps(value)


def create_postgres_store(database_url: str) -> PostgresStore:
    return PostgresStore(create_engine(database_url, pool_pre_ping=True))
```
Note: with `Uuid(as_uuid=False)` the driver returns `str` ids. `_job` wraps them in `str(...)` defensively; apply the same to other converters if a test shows a `UUID` object leaking.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_store_contract.py -v`
Expected: every `[memory]` and `[postgres]` case passes, plus the two concurrency tests. Fix any divergence in `PostgresStore` (the contract is the spec). For example, if `created_at` comes back with a different tzinfo object, compare-equal UTC datetimes still pass.

- [ ] **Step 5: Commit (checkpoint)**

```bash
git add backend/app/persistence/postgres.py backend/tests/conftest.py backend/tests/test_store_contract.py
git commit -m "feat(backend): add PostgresStore passing the shared store contract"
```

---

### Task 8: Durable artifact storage

**Files:**
- Create: `backend/app/storage.py`, `backend/tests/test_storage.py`

**Interfaces:**
- Produces: `ArtifactStorage` protocol and `LocalArtifactStorage(root: Path)` with
  - `staging_dir() -> ContextManager[Path]`: fresh directory under `root/tmp`, removed on exit
  - `put(key: str, source: Path) -> StoredFile`: copy to `root/tmp/<uuid>.part`, fsync, `os.replace` to `root/<key>`. `StoredFile(key, size_bytes, sha256)`
  - `put_bytes(key: str, data: bytes) -> StoredFile`
  - `path(key) -> Path` (rejects absolute keys, `..` and backslashes with `ValueError`)
  - `exists(key) -> bool`, `read_bytes(key) -> bytes`, `delete(key) -> None` (missing is fine)
  - `delete_stale_temp(older_than: datetime) -> int`: removes entries in `root/tmp` whose mtime < older_than
  - `total_bytes() -> int`: all files under root, excluding `tmp`
  - module function `artifact_key(project_id, job_id, filename) -> str` = `f"projects/{project_id}/{job_id}/{filename}"`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_storage.py`:
```python
import hashlib
import os
from datetime import UTC, datetime, timedelta

import pytest

from app.storage import LocalArtifactStorage, artifact_key


def test_artifact_key_is_relative_and_scoped_by_project_and_job():
    assert artifact_key("p1", "j1", "drums.wav") == "projects/p1/j1/drums.wav"


def test_put_moves_file_into_place_and_reports_size_and_hash(tmp_path):
    storage = LocalArtifactStorage(tmp_path / "store")
    source = tmp_path / "input.wav"
    source.write_bytes(b"audio-bytes")

    stored = storage.put("projects/p/j/source.wav", source)

    assert stored.key == "projects/p/j/source.wav"
    assert stored.size_bytes == 11
    assert stored.sha256 == hashlib.sha256(b"audio-bytes").hexdigest()
    assert storage.read_bytes("projects/p/j/source.wav") == b"audio-bytes"
    assert storage.exists("projects/p/j/source.wav")
    assert list((tmp_path / "store" / "tmp").iterdir()) == []


def test_put_bytes_writes_content(tmp_path):
    storage = LocalArtifactStorage(tmp_path)

    stored = storage.put_bytes("projects/p/j/raw.json", b"[]")

    assert stored.size_bytes == 2
    assert storage.read_bytes("projects/p/j/raw.json") == b"[]"


def test_put_replaces_an_existing_key_atomically(tmp_path):
    storage = LocalArtifactStorage(tmp_path)
    storage.put_bytes("k/a.bin", b"old")

    storage.put_bytes("k/a.bin", b"new")

    assert storage.read_bytes("k/a.bin") == b"new"


def test_failed_copy_leaves_no_committed_file(tmp_path, monkeypatch):
    storage = LocalArtifactStorage(tmp_path)
    source = tmp_path / "input.wav"
    source.write_bytes(b"x")

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)

    with pytest.raises(OSError):
        storage.put("k/source.wav", source)

    assert not storage.exists("k/source.wav")
    assert list((tmp_path / "tmp").iterdir()) == []


@pytest.mark.parametrize("bad_key", ["/etc/passwd", "../escape", "a/../../b", "a\\b", ""])
def test_path_rejects_unsafe_keys(tmp_path, bad_key):
    storage = LocalArtifactStorage(tmp_path)

    with pytest.raises(ValueError):
        storage.path(bad_key)


def test_delete_removes_file_and_tolerates_missing(tmp_path):
    storage = LocalArtifactStorage(tmp_path)
    storage.put_bytes("k/a.bin", b"x")

    storage.delete("k/a.bin")
    storage.delete("k/a.bin")

    assert not storage.exists("k/a.bin")


def test_staging_dir_is_created_under_tmp_and_removed(tmp_path):
    storage = LocalArtifactStorage(tmp_path)

    with storage.staging_dir() as staging:
        (staging / "nested").mkdir()
        (staging / "nested" / "f.wav").write_bytes(b"x")
        inside = staging.parent == tmp_path / "tmp"

    assert inside
    assert not staging.exists()


def test_delete_stale_temp_removes_only_old_entries(tmp_path):
    storage = LocalArtifactStorage(tmp_path)
    old = tmp_path / "tmp" / "old.part"
    old.write_bytes(b"x")
    old_dir = tmp_path / "tmp" / "olddir"
    old_dir.mkdir()
    (old_dir / "f").write_bytes(b"x")
    fresh = tmp_path / "tmp" / "fresh.part"
    fresh.write_bytes(b"x")
    long_ago = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(old, (long_ago, long_ago))
    os.utime(old_dir, (long_ago, long_ago))

    removed = storage.delete_stale_temp(datetime.now(UTC) - timedelta(days=1))

    assert removed == 2
    assert not old.exists()
    assert not old_dir.exists()
    assert fresh.exists()


def test_total_bytes_counts_stored_files_but_not_temp(tmp_path):
    storage = LocalArtifactStorage(tmp_path)
    storage.put_bytes("k/a.bin", b"12345")
    storage.put_bytes("k/b.bin", b"123")
    (tmp_path / "tmp" / "junk.part").write_bytes(b"xxxxxxxxxx")

    assert storage.total_bytes() == 8
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.storage'`.

- [ ] **Step 3: Implement**

`backend/app/storage.py`:
```python
import hashlib
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import ContextManager, Protocol

_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class StoredFile:
    key: str
    size_bytes: int
    sha256: str


def artifact_key(project_id: str, job_id: str, filename: str) -> str:
    return f"projects/{project_id}/{job_id}/{filename}"


class ArtifactStorage(Protocol):
    def staging_dir(self) -> ContextManager[Path]: ...
    def put(self, key: str, source: Path) -> StoredFile: ...
    def put_bytes(self, key: str, data: bytes) -> StoredFile: ...
    def path(self, key: str) -> Path: ...
    def exists(self, key: str) -> bool: ...
    def read_bytes(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def delete_stale_temp(self, older_than: datetime) -> int: ...
    def total_bytes(self) -> int: ...


class LocalArtifactStorage:
    """Artifacts on the local filesystem under `root`. Writes go to
    root/tmp first and are fsync'd and atomically renamed into place, so a
    key either holds a complete file or does not exist - never a partial
    file that looks finished."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._tmp = root / "tmp"
        self._tmp.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        pure = PurePosixPath(key)
        if not key or "\\" in key or pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"Unsafe storage key: {key!r}")
        return self.root.joinpath(*pure.parts)

    @contextmanager
    def staging_dir(self) -> Iterator[Path]:
        directory = self._tmp / f"stage-{uuid.uuid4().hex}"
        directory.mkdir()
        try:
            yield directory
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def put(self, key: str, source: Path) -> StoredFile:
        destination = self.path(key)
        partial = self._tmp / f"{uuid.uuid4().hex}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with source.open("rb") as reader, partial.open("wb") as writer:
                while chunk := reader.read(_CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(partial, destination)
        finally:
            partial.unlink(missing_ok=True)
        return StoredFile(key=key, size_bytes=size, sha256=digest.hexdigest())

    def put_bytes(self, key: str, data: bytes) -> StoredFile:
        with self.staging_dir() as staging:
            source = staging / "payload"
            source.write_bytes(data)
            return self.put(key, source)

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def read_bytes(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def delete_stale_temp(self, older_than: datetime) -> int:
        cutoff = older_than.timestamp()
        removed = 0
        for entry in self._tmp.iterdir():
            if entry.stat().st_mtime >= cutoff:
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            removed += 1
        return removed

    def total_bytes(self) -> int:
        return sum(
            f.stat().st_size for f in self.root.rglob("*") if f.is_file() and self._tmp not in f.parents
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_storage.py -v`
Expected: all passed.

- [ ] **Step 5: Commit (checkpoint)**

```bash
git add backend/app/storage.py backend/tests/test_storage.py
git commit -m "feat(backend): add atomic local artifact storage"
```

---

### Task 9: Stage building blocks: extractor title, error policy, tempo mapping, shared fakes

**Files:**
- Modify: `backend/app/audio_extraction.py`, `backend/app/youtube_audio_extractor.py`, `backend/tests/test_youtube_audio_extractor.py`
- Modify (keep the old path green until Task 13 deletes it): `backend/app/job_processor.py` (`run_audio_extraction`), fake extractors in `backend/tests/test_job_processor.py` and `backend/tests/test_jobs_api.py`
- Create: `backend/app/clock.py`, `backend/app/pipeline/errors.py`, `backend/app/pipeline/tempo_mapping.py`, `backend/tests/fakes.py`, `backend/tests/test_pipeline_errors.py`, `backend/tests/test_tempo_mapping.py`

**Interfaces:**
- Produces: `ExtractedAudio(audio_path: Path, title: str | None = None)`, and `AudioExtractor.extract(...) -> ExtractedAudio`.
- Produces: `app.clock.utc_now() -> datetime`.
- Produces: `app.pipeline.errors.InsufficientBeatsError`, `PERMANENT_ERRORS`, `is_permanent(error) -> bool`, `backoff_seconds(attempts: int, base_seconds: int) -> int`.
- Produces: `app.pipeline.tempo_mapping.TempoMappingResult(tempo_bpm, tempo_map, beats, events)` and `map_tempo(drums_path, events, tempo_estimator, beat_detector) -> TempoMappingResult`.
- Produces (tests/fakes.py): `START`, `FakeClock`, `FakeExtractor`, `FakeSeparator`, `FakeTranscriber`, `FakeTempoEstimator`, `FakeBeatDetector`, `FOUR_BEATS`, `OFFSET_BEATS`, `SAMPLE_RAW_EVENTS`. Task 10 adds `make_engines(**overrides)`.

- [ ] **Step 1: Write the failing extractor tests**

Replace the three `extract` tests in `backend/tests/test_youtube_audio_extractor.py` (keep the `_build_ydl_options` tests) with:
```python
def test_extract_raises_when_no_output_file_is_produced(tmp_path, source):
    extractor = YtDlpAudioExtractor()

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.return_value.extract_info.return_value = {"title": "Song"}

        with pytest.raises(AudioExtractionError, match="did not produce"):
            extractor.extract(source, tmp_path / "job-1")


def test_extract_returns_output_path_and_video_title(tmp_path, source):
    extractor = YtDlpAudioExtractor()
    destination_dir = tmp_path / "job-1"
    destination_dir.mkdir()
    (destination_dir / "source.wav").write_bytes(b"fake wav data")

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl = mock_ydl_cls.return_value.__enter__.return_value
        mock_ydl.extract_info.return_value = {"title": "Never Gonna Give You Up"}

        result = extractor.extract(source, destination_dir)

    assert result.audio_path == destination_dir / "source.wav"
    assert result.title == "Never Gonna Give You Up"
    mock_ydl.extract_info.assert_called_once_with(source.url, download=True)


def test_extract_returns_no_title_when_metadata_is_missing(tmp_path, source):
    extractor = YtDlpAudioExtractor()
    destination_dir = tmp_path / "job-1"
    destination_dir.mkdir()
    (destination_dir / "source.wav").write_bytes(b"fake wav data")

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.return_value.extract_info.return_value = None

        result = extractor.extract(source, destination_dir)

    assert result.title is None


def test_extract_wraps_download_errors(tmp_path, source):
    import yt_dlp

    extractor = YtDlpAudioExtractor()

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.return_value.extract_info.side_effect = (
            yt_dlp.utils.DownloadError("video unavailable")
        )

        with pytest.raises(AudioExtractionError, match="video unavailable"):
            extractor.extract(source, tmp_path / "job-1")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_youtube_audio_extractor.py -v`
Expected: FAIL (the result has no `audio_path`/`title`; `extract_info` is never called).

- [ ] **Step 3: Implement `ExtractedAudio` and the title**

`backend/app/audio_extraction.py`:
```python
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.media_source import ParsedSource


class AudioExtractionError(Exception):
    pass


@dataclass(frozen=True)
class ExtractedAudio:
    audio_path: Path
    # Human-readable source title (e.g. the YouTube video title) when the
    # provider reports one; used as the project's display title.
    title: str | None = None


class AudioExtractor(Protocol):
    def extract(self, source: ParsedSource, destination_dir: Path) -> ExtractedAudio: ...
```

In `backend/app/youtube_audio_extractor.py` import `ExtractedAudio` next to `AudioExtractionError` and change `extract` to:
```python
    def extract(self, source: ParsedSource, destination_dir: Path) -> ExtractedAudio:
        destination_dir.mkdir(parents=True, exist_ok=True)
        options = _build_ydl_options(destination_dir)

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(source.url, download=True)
        except yt_dlp.utils.DownloadError as error:
            raise AudioExtractionError(f"Failed to download audio: {error}") from error

        output_path = destination_dir / "source.wav"
        if not output_path.exists():
            raise AudioExtractionError("Audio extraction did not produce an output file")

        title = info.get("title") if isinstance(info, dict) else None
        return ExtractedAudio(audio_path=output_path, title=title)
```

Keep the legacy path green until Task 13:
- In `backend/app/job_processor.py` `run_audio_extraction`, change `audio_path = extractor.extract(source, storage_dir / job_id)` to `audio_path = extractor.extract(source, storage_dir / job_id).audio_path`.
- In `tests/test_job_processor.py`, change `FakeSuccessfulExtractor.extract` to `return ExtractedAudio(destination_dir / "source.wav")`.
- In `tests/test_jobs_api.py`, change the last line of `FakeAudioExtractor.extract` to `return ExtractedAudio(path)`.
- Import `ExtractedAudio` from `app.audio_extraction` in both test files.

- [ ] **Step 4: Run to verify the extractor and legacy suites pass**

Run: `uv run pytest tests/test_youtube_audio_extractor.py tests/test_job_processor.py tests/test_jobs_api.py -v`
Expected: all passed.

- [ ] **Step 5: Write the shared fakes**

`backend/tests/fakes.py`:
```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.audio_extraction import ExtractedAudio
from app.stem_separation import SeparatedStems
from app.timing import BeatPoint
from app.transcription import DrumEvent, DrumInstrument

START = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)

FOUR_BEATS = [
    BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True),
    BeatPoint(source_time=0.5, measure=1, beat=2, is_downbeat=False),
    BeatPoint(source_time=1.0, measure=1, beat=3, is_downbeat=False),
    BeatPoint(source_time=1.5, measure=1, beat=4, is_downbeat=False),
]

# First beat NOT at t=0 - distinguishes beat-anchored quantization from a t=0 grid.
OFFSET_BEATS = [
    BeatPoint(source_time=2.5, measure=1, beat=1, is_downbeat=True),
    BeatPoint(source_time=3.0, measure=1, beat=2, is_downbeat=False),
    BeatPoint(source_time=3.5, measure=1, beat=3, is_downbeat=False),
]

SAMPLE_RAW_EVENTS = [
    DrumEvent(id="e1", time=0.5 + 1e-9, instrument=DrumInstrument.KICK, provenance="drumscript"),
    DrumEvent(id="e2", time=0.5 + 1e-9, instrument=DrumInstrument.HIHAT_CLOSED, provenance="drumscript"),
]


class FakeClock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class FakeExtractor:
    def __init__(self, title: str | None = "Fake Song", error: BaseException | None = None, on_call=None) -> None:
        self.title = title
        self.error = error
        self.on_call = on_call
        self.calls = 0

    def extract(self, source, destination_dir: Path) -> ExtractedAudio:
        self.calls += 1
        if self.on_call:
            self.on_call()
        if self.error:
            raise self.error
        destination_dir.mkdir(parents=True, exist_ok=True)
        path = destination_dir / "source.wav"
        path.write_bytes(b"fake source audio")
        return ExtractedAudio(audio_path=path, title=self.title)


class FakeSeparator:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls = 0

    def separate(self, audio_path: Path, destination_dir: Path) -> SeparatedStems:
        self.calls += 1
        if self.error:
            raise self.error
        assert audio_path.read_bytes() == b"fake source audio"
        output = destination_dir / "htdemucs" / "source"
        output.mkdir(parents=True, exist_ok=True)
        (output / "drums.wav").write_bytes(b"fake drums")
        (output / "no_drums.wav").write_bytes(b"fake accompaniment")
        return SeparatedStems(drums_path=output / "drums.wav", accompaniment_path=output / "no_drums.wav")


class FakeTranscriber:
    def __init__(self, events=None, error: BaseException | None = None) -> None:
        self.events = list(SAMPLE_RAW_EVENTS if events is None else events)
        self.error = error
        self.calls = 0

    def transcribe(self, audio_path: Path):
        self.calls += 1
        if self.error:
            raise self.error
        assert audio_path.read_bytes() == b"fake drums"
        return list(self.events)


class FakeTempoEstimator:
    def __init__(self, bpm: float = 120.0, error: BaseException | None = None) -> None:
        self.bpm = bpm
        self.error = error

    def estimate(self, audio_path: Path) -> float:
        if self.error:
            raise self.error
        return self.bpm


class FakeBeatDetector:
    def __init__(self, beats=None, error: BaseException | None = None) -> None:
        self.beats = list(FOUR_BEATS if beats is None else beats)
        self.error = error

    def detect(self, audio_path: Path):
        if self.error:
            raise self.error
        return list(self.beats)
```

- [ ] **Step 6: Write the failing error-policy and tempo-mapping tests**

`backend/tests/test_pipeline_errors.py`:
```python
import pytest

from app.audio_extraction import AudioExtractionError
from app.beat_detection import BeatDetectionError
from app.media_source import InvalidSourceUrlError
from app.pipeline.errors import InsufficientBeatsError, backoff_seconds, is_permanent
from app.stem_separation import StemSeparationError
from app.tempo_estimation import TempoEstimationError
from app.transcription import TranscriptionError


@pytest.mark.parametrize(
    "error",
    [
        AudioExtractionError("video unavailable"),
        StemSeparationError("demucs failed"),
        TranscriptionError("model crashed"),
        TempoEstimationError("no tempo"),
        BeatDetectionError("no onsets"),
        InsufficientBeatsError("1 beat"),
        InvalidSourceUrlError("bad url"),
    ],
)
def test_domain_errors_are_permanent(error):
    assert is_permanent(error) is True


@pytest.mark.parametrize("error", [RuntimeError("oom"), OSError("disk"), KeyError("x")])
def test_unexpected_errors_are_retryable(error):
    assert is_permanent(error) is False


@pytest.mark.parametrize("attempts, expected", [(0, 30), (1, 30), (2, 60), (3, 120)])
def test_backoff_doubles_per_attempt(attempts, expected):
    assert backoff_seconds(attempts, 30) == expected
```

`backend/tests/test_tempo_mapping.py`:
```python
from pathlib import Path

import pytest

from app.pipeline.errors import InsufficientBeatsError
from app.pipeline.tempo_mapping import map_tempo
from app.tempo_estimation import TempoEstimationError
from app.timing import TempoMap
from app.transcription import DrumEvent, DrumInstrument
from tests.fakes import FOUR_BEATS, OFFSET_BEATS, FakeBeatDetector, FakeTempoEstimator

DRUMS = Path("drums.wav")


def test_map_tempo_returns_bpm_constant_tempo_map_and_beats():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    result = map_tempo(DRUMS, events, FakeTempoEstimator(128.0), FakeBeatDetector(FOUR_BEATS))

    assert result.tempo_bpm == 128.0
    assert result.tempo_map == TempoMap.constant(128.0)
    assert result.beats == FOUR_BEATS


def test_map_tempo_quantizes_against_real_beat_anchors():
    events = [DrumEvent(id="e1", time=2.5, instrument=DrumInstrument.KICK)]

    result = map_tempo(DRUMS, events, FakeTempoEstimator(), FakeBeatDetector(OFFSET_BEATS))

    assert (result.events[0].measure, result.events[0].beat, result.events[0].subdivision) == (1, 1, 0)
    assert result.events[0].time == 2.5


def test_map_tempo_shifts_measures_so_pre_first_beat_events_are_kept():
    events = [
        DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK),
        DrumEvent(id="e2", time=3.0, instrument=DrumInstrument.SNARE),
    ]

    result = map_tempo(DRUMS, events, FakeTempoEstimator(), FakeBeatDetector(OFFSET_BEATS))

    e1, e2 = result.events
    assert (e1.measure, e1.beat, e1.subdivision) == (1, 1, 0)
    assert (e2.measure, e2.beat, e2.subdivision) == (2, 2, 0)


def test_map_tempo_does_not_shift_when_measures_already_start_at_one():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    result = map_tempo(DRUMS, events, FakeTempoEstimator(), FakeBeatDetector(FOUR_BEATS))

    assert (result.events[0].measure, result.events[0].beat) == (1, 2)


def test_map_tempo_leaves_input_events_untouched():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    map_tempo(DRUMS, events, FakeTempoEstimator(), FakeBeatDetector(FOUR_BEATS))

    assert events[0].beat is None


def test_map_tempo_requires_two_beats():
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    with pytest.raises(InsufficientBeatsError, match="found only 1 beat"):
        map_tempo(DRUMS, events, FakeTempoEstimator(), FakeBeatDetector(FOUR_BEATS[:1]))


def test_map_tempo_propagates_engine_errors():
    with pytest.raises(TempoEstimationError):
        map_tempo(DRUMS, [], FakeTempoEstimator(error=TempoEstimationError("no tempo")), FakeBeatDetector())


def test_map_tempo_handles_no_events():
    result = map_tempo(DRUMS, [], FakeTempoEstimator(), FakeBeatDetector())

    assert result.events == []
```

- [ ] **Step 7: Run to verify they fail**

Run: `uv run pytest tests/test_pipeline_errors.py tests/test_tempo_mapping.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.pipeline.errors'`.

- [ ] **Step 8: Implement clock, errors and tempo mapping**

`backend/app/clock.py`:
```python
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
```

`backend/app/pipeline/errors.py`:
```python
from app.audio_extraction import AudioExtractionError
from app.beat_detection import BeatDetectionError
from app.media_source import InvalidSourceUrlError
from app.stem_separation import StemSeparationError
from app.tempo_estimation import TempoEstimationError
from app.transcription import TranscriptionError


class InsufficientBeatsError(Exception):
    pass


# Expected, input-determined failures: retrying the same input cannot
# succeed, so the job fails immediately with the engine's message. Any
# other exception is treated as transient and retried with backoff.
PERMANENT_ERRORS: tuple[type[Exception], ...] = (
    AudioExtractionError,
    StemSeparationError,
    TranscriptionError,
    TempoEstimationError,
    BeatDetectionError,
    InsufficientBeatsError,
    InvalidSourceUrlError,
)


def is_permanent(error: BaseException) -> bool:
    return isinstance(error, PERMANENT_ERRORS)


def backoff_seconds(attempts: int, base_seconds: int) -> int:
    return base_seconds * 2 ** max(attempts - 1, 0)
```

`backend/app/pipeline/tempo_mapping.py`:
```python
import dataclasses
from dataclasses import dataclass
from pathlib import Path

from app.beat_detection import BeatDetector
from app.beat_mapping import quantize_events_with_beats
from app.pipeline.errors import InsufficientBeatsError
from app.tempo_estimation import TempoEstimator
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
    events: list[DrumEvent],
    tempo_estimator: TempoEstimator,
    beat_detector: BeatDetector,
) -> TempoMappingResult:
    """Estimates tempo, detects beats and assigns each event a musical
    position anchored to the real beats. Source timestamps are never
    changed. (Moved unchanged from job_processor.run_tempo_mapping.)"""
    bpm = tempo_estimator.estimate(drums_path)
    beats = beat_detector.detect(drums_path)

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

    return TempoMappingResult(tempo_bpm=bpm, tempo_map=TempoMap.constant(bpm), beats=beats, events=quantized_events)
```

- [ ] **Step 9: Run to verify they pass**

Run: `uv run pytest tests/test_pipeline_errors.py tests/test_tempo_mapping.py -v`
Expected: all passed.

- [ ] **Step 10: Commit (checkpoint)**

```bash
git add backend/app/audio_extraction.py backend/app/youtube_audio_extractor.py backend/app/job_processor.py backend/app/clock.py backend/app/pipeline backend/tests/fakes.py backend/tests/test_youtube_audio_extractor.py backend/tests/test_job_processor.py backend/tests/test_jobs_api.py backend/tests/test_pipeline_errors.py backend/tests/test_tempo_mapping.py
git commit -m "feat(backend): add extractor titles, stage error policy and standalone tempo mapping"
```

---

### Task 10: Job runner: idempotent stages, stage cache, failure handling

**Files:**
- Create: `backend/app/pipeline/runner.py`, `backend/tests/test_runner.py`
- Modify: `backend/tests/fakes.py` (add `make_engines`)

**Interfaces:**
- Consumes: `Store`, `ArtifactStorage`/`artifact_key`, `PIPELINE_VERSION`, `map_tempo`, `is_permanent`, `backoff_seconds`, `events_to_json_bytes`/`events_from_json_bytes`.
- Produces:
  - `PipelineEngines(source_validator, extractor, separator, transcriber, tempo_estimator, beat_detector)`
  - `JobContext(store, storage, engines, owner, retry_base_seconds, clock, should_stop=lambda: False)` (field order matters: tests construct it positionally)
  - `JobAbandoned(Exception)`
  - `process_job(job: Job, ctx: JobContext) -> None`. It raises only `JobAbandoned`, `LeaseLostError`, or a non-`Exception` `BaseException`. Every ordinary exception ends in `fail_job` or `schedule_retry`.

- [ ] **Step 1: Add `make_engines` to fakes**

Append to `backend/tests/fakes.py`:
```python
def make_engines(**overrides):
    from app.pipeline.runner import PipelineEngines
    from app.youtube_source import YouTubeSourceValidator

    engines = {
        "source_validator": YouTubeSourceValidator(),
        "extractor": FakeExtractor(),
        "separator": FakeSeparator(),
        "transcriber": FakeTranscriber(),
        "tempo_estimator": FakeTempoEstimator(),
        "beat_detector": FakeBeatDetector(),
    }
    engines.update(overrides)
    return PipelineEngines(**engines)
```

- [ ] **Step 2: Write the failing runner tests**

`backend/tests/test_runner.py`:
```python
from datetime import timedelta

import pytest

from app.audio_extraction import AudioExtractionError
from app.persistence.memory import InMemoryStore
from app.persistence.models import ArtifactKind, JobStatus, LeaseLostError
from app.pipeline.runner import JobAbandoned, JobContext, process_job
from app.storage import LocalArtifactStorage
from tests.fakes import (
    FOUR_BEATS,
    SAMPLE_RAW_EVENTS,
    FakeBeatDetector,
    FakeClock,
    FakeExtractor,
    FakeSeparator,
    FakeTranscriber,
    make_engines,
)

URL = "https://youtu.be/dQw4w9WgXcQ"
KEY = "youtube:dQw4w9WgXcQ"
OWNER = "worker-a"


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def storage(tmp_path):
    return LocalArtifactStorage(tmp_path / "storage")


@pytest.fixture
def clock():
    return FakeClock()


def new_project(store, clock, title=URL):
    return store.create_project_with_job(
        source_kind="youtube", source_url=URL, source_key=KEY, title=title, max_attempts=3, now=clock()
    )


def run(store, storage, clock, engines, should_stop=lambda: False):
    job = store.claim_next_job(OWNER, 300, clock())
    ctx = JobContext(
        store=store,
        storage=storage,
        engines=engines,
        owner=OWNER,
        retry_base_seconds=30,
        clock=clock,
        should_stop=should_stop,
    )
    process_job(job, ctx)
    return store.get_job(job.id)


def test_full_run_completes_job_with_analysis_artifacts_and_title(store, storage, clock):
    project, _ = new_project(store, clock)

    job = run(store, storage, clock, make_engines())

    assert job.status == JobStatus.COMPLETED
    analysis = store.latest_analysis(project.id)
    assert analysis.raw_events == SAMPLE_RAW_EVENTS
    assert [e.time for e in analysis.events] == [e.time for e in SAMPLE_RAW_EVENTS]
    assert all(e.measure is not None for e in analysis.events)
    assert analysis.beats == FOUR_BEATS
    assert analysis.pipeline_version == "1"
    artifacts = store.artifacts_for_job(job.id)
    assert set(artifacts) == set(ArtifactKind)
    assert storage.read_bytes(artifacts[ArtifactKind.DRUMS_STEM].storage_key) == b"fake drums"
    assert artifacts[ArtifactKind.DRUMS_STEM].storage_key == f"projects/{project.id}/{job.id}/drums.wav"
    assert store.get_project(project.id).title == "Fake Song"


def test_existing_custom_title_is_not_overwritten(store, storage, clock):
    project, _ = new_project(store, clock, title="My Title")

    run(store, storage, clock, make_engines())

    assert store.get_project(project.id).title == "My Title"


def test_retry_resumes_after_last_committed_stage(store, storage, clock):
    new_project(store, clock)
    extractor = FakeExtractor()
    first = run(store, storage, clock, make_engines(extractor=extractor, separator=FakeSeparator(error=RuntimeError("oom"))))
    clock.advance(31)

    second = run(store, storage, clock, make_engines(extractor=extractor))

    assert first.status == JobStatus.SEPARATING_STEMS
    assert first.error == "Unexpected error: oom"
    assert second.status == JobStatus.COMPLETED
    assert extractor.calls == 1


def test_forced_duplicate_reuses_cached_stage_outputs(store, storage, clock):
    extractor, separator, transcriber = FakeExtractor(), FakeSeparator(), FakeTranscriber()
    engines = make_engines(extractor=extractor, separator=separator, transcriber=transcriber)
    original, _ = new_project(store, clock)
    first = run(store, storage, clock, engines)
    duplicate, _ = new_project(store, clock)

    second = run(store, storage, clock, engines)

    assert second.status == JobStatus.COMPLETED
    assert (extractor.calls, separator.calls, transcriber.calls) == (1, 1, 1)
    original_keys = {k: a.storage_key for k, a in store.artifacts_for_job(first.id).items()}
    duplicate_keys = {k: a.storage_key for k, a in store.artifacts_for_job(second.id).items()}
    assert duplicate_keys == original_keys
    assert store.latest_analysis(duplicate.id).raw_events == store.latest_analysis(original.id).raw_events


def test_cache_entry_with_missing_file_is_ignored(store, storage, clock):
    separator = FakeSeparator()
    engines = make_engines(separator=separator)
    new_project(store, clock)
    first = run(store, storage, clock, engines)
    storage.delete(store.artifacts_for_job(first.id)[ArtifactKind.DRUMS_STEM].storage_key)
    new_project(store, clock)

    second = run(store, storage, clock, engines)

    assert second.status == JobStatus.COMPLETED
    assert separator.calls == 2


def test_committed_artifact_whose_file_vanished_is_recomputed(store, storage, clock):
    new_project(store, clock)
    extractor = FakeExtractor()
    first = run(store, storage, clock, make_engines(extractor=extractor, separator=FakeSeparator(error=RuntimeError("x"))))
    storage.delete(store.artifacts_for_job(first.id)[ArtifactKind.SOURCE_AUDIO].storage_key)
    clock.advance(31)

    second = run(store, storage, clock, make_engines(extractor=extractor))

    assert second.status == JobStatus.COMPLETED
    assert extractor.calls == 2


def test_permanent_error_fails_immediately(store, storage, clock):
    new_project(store, clock)

    job = run(store, storage, clock, make_engines(extractor=FakeExtractor(error=AudioExtractionError("video unavailable"))))

    assert job.status == JobStatus.FAILED
    assert job.error == "video unavailable"
    assert job.attempts == 1


def test_insufficient_beats_fails_with_message(store, storage, clock):
    new_project(store, clock)

    job = run(store, storage, clock, make_engines(beat_detector=FakeBeatDetector(FOUR_BEATS[:1])))

    assert job.status == JobStatus.FAILED
    assert job.error == "Beat detection found only 1 beat(s); tempo mapping requires at least 2"


def test_transient_error_schedules_retry_with_backoff(store, storage, clock):
    new_project(store, clock)
    started = clock()

    job = run(store, storage, clock, make_engines(transcriber=FakeTranscriber(error=RuntimeError("boom"))))

    assert job.status == JobStatus.TRANSCRIBING
    assert job.error == "Unexpected error: boom"
    assert job.available_at == started + timedelta(seconds=30)
    assert job.lease_owner is None


def test_transient_error_on_last_attempt_fails_job(store, storage, clock):
    new_project(store, clock)
    engines = make_engines(transcriber=FakeTranscriber(error=RuntimeError("boom")))
    run(store, storage, clock, engines)
    clock.advance(30)
    run(store, storage, clock, engines)
    clock.advance(60)

    job = run(store, storage, clock, engines)

    assert job.status == JobStatus.FAILED
    assert job.error == "Unexpected error: boom"
    assert job.attempts == 3


def test_deleted_project_job_is_failed_without_running(store, storage, clock):
    project, _ = new_project(store, clock)
    store.soft_delete_project(project.id, clock())
    extractor = FakeExtractor()

    job = run(store, storage, clock, make_engines(extractor=extractor))

    assert job.status == JobStatus.FAILED
    assert job.error == "Project was deleted"
    assert extractor.calls == 0


def test_stop_request_abandons_between_stages_after_committing_output(store, storage, clock):
    _, job = new_project(store, clock)
    stop = {"requested": False}
    extractor = FakeExtractor(on_call=lambda: stop.update(requested=True))

    with pytest.raises(JobAbandoned):
        run(store, storage, clock, make_engines(extractor=extractor), should_stop=lambda: stop["requested"])

    assert ArtifactKind.SOURCE_AUDIO in store.artifacts_for_job(job.id)
    assert store.get_job(job.id).status == JobStatus.DOWNLOADED


def test_lost_lease_propagates_and_commits_nothing(store, storage, clock):
    _, job = new_project(store, clock)

    def steal():
        store.claim_next_job("thief", 300, clock() + timedelta(days=1))

    with pytest.raises(LeaseLostError):
        run(store, storage, clock, make_engines(extractor=FakeExtractor(on_call=steal)))

    assert store.artifacts_for_job(job.id) == {}
    assert store.get_job(job.id).lease_owner == "thief"
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.pipeline.runner'`.

- [ ] **Step 4: Implement the runner**

`backend/app/pipeline/runner.py`:
```python
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from app.audio_extraction import AudioExtractor
from app.beat_detection import BeatDetector
from app.media_source import MediaSourceValidator
from app.persistence.models import (
    Artifact,
    ArtifactKind,
    CacheEntry,
    Job,
    JobStatus,
    LeaseLostError,
    NewAnalysis,
    NewArtifact,
    Project,
    Stage,
)
from app.persistence.serialization import events_from_json_bytes, events_to_json_bytes
from app.persistence.store import Store
from app.pipeline.errors import backoff_seconds, is_permanent
from app.pipeline.tempo_mapping import map_tempo
from app.pipeline.version import PIPELINE_VERSION
from app.stem_separation import StemSeparator
from app.storage import ArtifactStorage, artifact_key
from app.tempo_estimation import TempoEstimator
from app.transcription import DrumTranscriber

logger = logging.getLogger(__name__)

_FILENAMES = {
    ArtifactKind.SOURCE_AUDIO: "source.wav",
    ArtifactKind.DRUMS_STEM: "drums.wav",
    ArtifactKind.ACCOMPANIMENT_STEM: "accompaniment.wav",
    ArtifactKind.RAW_TRANSCRIPTION: "raw_transcription.json",
}

StageOutputs = list[tuple[ArtifactKind, Path]]


@dataclass(frozen=True)
class PipelineEngines:
    source_validator: MediaSourceValidator
    extractor: AudioExtractor
    separator: StemSeparator
    transcriber: DrumTranscriber
    tempo_estimator: TempoEstimator
    beat_detector: BeatDetector


@dataclass(frozen=True)
class JobContext:
    store: Store
    storage: ArtifactStorage
    engines: PipelineEngines
    owner: str
    retry_base_seconds: int
    clock: Callable[[], datetime]
    should_stop: Callable[[], bool] = field(default=lambda: False)


class JobAbandoned(Exception):
    """Raised between stages when the worker is stopping or has lost its
    lease; committed stages stay, the rest resumes on the next claim."""


def process_job(job: Job, ctx: JobContext) -> None:
    """Runs every stage that has no committed output yet, then maps tempo
    and completes the job. Idempotent: each stage's output is written to
    storage and committed (with its cache entry and status) before the
    next stage starts, so re-running after any crash only redoes the stage
    that was in flight."""
    project = ctx.store.get_project(job.project_id)
    if project is None or project.deleted_at is not None:
        ctx.store.fail_job(job.id, ctx.owner, "Project was deleted", ctx.clock())
        return

    try:
        _run_stages(job, project, ctx)
    except (JobAbandoned, LeaseLostError):
        raise
    except Exception as error:  # noqa: BLE001 - every failure must end in fail or retry
        _handle_failure(job, ctx, error)


def _handle_failure(job: Job, ctx: JobContext, error: Exception) -> None:
    now = ctx.clock()
    if is_permanent(error):
        logger.info("Job %s failed permanently: %s", job.id, error)
        ctx.store.fail_job(job.id, ctx.owner, str(error), now)
        return

    message = f"Unexpected error: {error}"
    logger.exception("Job %s crashed on attempt %d/%d", job.id, job.attempts, job.max_attempts)
    if job.attempts >= job.max_attempts:
        ctx.store.fail_job(job.id, ctx.owner, message, now)
    else:
        delay = backoff_seconds(job.attempts, ctx.retry_base_seconds)
        ctx.store.schedule_retry(job.id, ctx.owner, message, now + timedelta(seconds=delay), now)


def _checkpoint(job: Job, ctx: JobContext) -> None:
    if ctx.should_stop():
        raise JobAbandoned(job.id)


def _live_artifacts(job: Job, ctx: JobContext) -> dict[ArtifactKind, Artifact]:
    return {
        kind: artifact
        for kind, artifact in ctx.store.artifacts_for_job(job.id).items()
        if artifact.pruned_at is None and ctx.storage.exists(artifact.storage_key)
    }


def _run_stages(job: Job, project: Project, ctx: JobContext) -> None:
    artifacts = _live_artifacts(job, ctx)

    if not {ArtifactKind.DRUMS_STEM, ArtifactKind.ACCOMPANIMENT_STEM} <= artifacts.keys():
        if ArtifactKind.SOURCE_AUDIO not in artifacts:
            artifacts |= _obtain(
                Stage.EXTRACT, job, project, ctx, JobStatus.DOWNLOADING, JobStatus.DOWNLOADED,
                lambda staging: _extract(project, ctx, staging),
            )
            _checkpoint(job, ctx)
        artifacts |= _obtain(
            Stage.SEPARATE, job, project, ctx, JobStatus.SEPARATING_STEMS, JobStatus.STEMS_SEPARATED,
            lambda staging: _separate(artifacts[ArtifactKind.SOURCE_AUDIO], ctx, staging),
        )
        _checkpoint(job, ctx)

    if ArtifactKind.RAW_TRANSCRIPTION not in artifacts:
        artifacts |= _obtain(
            Stage.TRANSCRIBE, job, project, ctx, JobStatus.TRANSCRIBING, JobStatus.TRANSCRIBED,
            lambda staging: _transcribe(artifacts[ArtifactKind.DRUMS_STEM], ctx, staging),
        )
        _checkpoint(job, ctx)

    _map_tempo_and_complete(job, artifacts, ctx)


def _obtain(
    stage: Stage,
    job: Job,
    project: Project,
    ctx: JobContext,
    running: JobStatus,
    done: JobStatus,
    produce: Callable[[Path], StageOutputs],
) -> dict[ArtifactKind, Artifact]:
    cached = ctx.store.get_cache_entry(project.source_key, stage, PIPELINE_VERSION)
    if cached is not None and all(ctx.storage.exists(a.storage_key) for a in cached.artifacts):
        logger.info("Job %s reusing cached %s output", job.id, stage.value)
        created = ctx.store.commit_stage(job.id, ctx.owner, done, cached.artifacts, None, ctx.clock())
        return {artifact.kind: artifact for artifact in created}

    ctx.store.set_job_status(job.id, ctx.owner, running, ctx.clock())
    with ctx.storage.staging_dir() as staging:
        descriptors = tuple(_store_output(job, kind, path, ctx) for kind, path in produce(staging))
    entry = CacheEntry(source_key=project.source_key, stage=stage, pipeline_version=PIPELINE_VERSION, artifacts=descriptors)
    created = ctx.store.commit_stage(job.id, ctx.owner, done, descriptors, entry, ctx.clock())
    return {artifact.kind: artifact for artifact in created}


def _store_output(job: Job, kind: ArtifactKind, path: Path, ctx: JobContext) -> NewArtifact:
    stored = ctx.storage.put(artifact_key(job.project_id, job.id, _FILENAMES[kind]), path)
    return NewArtifact(kind=kind, storage_key=stored.key, size_bytes=stored.size_bytes, sha256=stored.sha256)


def _extract(project: Project, ctx: JobContext, staging: Path) -> StageOutputs:
    source = ctx.engines.source_validator.parse(project.source_url)
    result = ctx.engines.extractor.extract(source, staging)
    if result.title and project.title == project.source_url:
        ctx.store.set_project_title(project.id, result.title, ctx.clock())
    return [(ArtifactKind.SOURCE_AUDIO, result.audio_path)]


def _separate(source_audio: Artifact, ctx: JobContext, staging: Path) -> StageOutputs:
    stems = ctx.engines.separator.separate(ctx.storage.path(source_audio.storage_key), staging)
    return [(ArtifactKind.DRUMS_STEM, stems.drums_path), (ArtifactKind.ACCOMPANIMENT_STEM, stems.accompaniment_path)]


def _transcribe(drums: Artifact, ctx: JobContext, staging: Path) -> StageOutputs:
    events = ctx.engines.transcriber.transcribe(ctx.storage.path(drums.storage_key))
    output = staging / "raw_transcription.json"
    output.write_bytes(events_to_json_bytes(events))
    return [(ArtifactKind.RAW_TRANSCRIPTION, output)]


def _map_tempo_and_complete(job: Job, artifacts: dict[ArtifactKind, Artifact], ctx: JobContext) -> None:
    ctx.store.set_job_status(job.id, ctx.owner, JobStatus.MAPPING_TEMPO, ctx.clock())
    raw_events = events_from_json_bytes(ctx.storage.read_bytes(artifacts[ArtifactKind.RAW_TRANSCRIPTION].storage_key))
    drums_path = ctx.storage.path(artifacts[ArtifactKind.DRUMS_STEM].storage_key)
    result = map_tempo(drums_path, raw_events, ctx.engines.tempo_estimator, ctx.engines.beat_detector)
    ctx.store.complete_job(
        job.id,
        ctx.owner,
        NewAnalysis(
            pipeline_version=PIPELINE_VERSION,
            tempo_bpm=result.tempo_bpm,
            tempo_map=result.tempo_map,
            beats=result.beats,
            events=result.events,
            raw_events=raw_events,
        ),
        ctx.clock(),
    )
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_runner.py -v --cov=app.pipeline.runner --cov-report=term-missing`
Expected: all passed; runner coverage 100%.

- [ ] **Step 6: Commit (checkpoint)**

```bash
git add backend/app/pipeline/runner.py backend/tests/fakes.py backend/tests/test_runner.py
git commit -m "feat(backend): add idempotent job runner with stage cache and retry policy"
```

---

### Task 11: Pruner (artifact lifecycle)

**Files:**
- Create: `backend/app/worker/__init__.py` (empty), `backend/app/worker/pruner.py`, `backend/tests/test_pruner.py`

**Interfaces:**
- Consumes: `Store.disposable_storage_keys/mark_storage_keys_pruned/purge_deleted_projects/maintenance_lock`, `ArtifactStorage.delete/delete_stale_temp/total_bytes`, `Settings`, `sample_analysis` from `tests/test_store_contract.py`.
- Produces: `PruneReport(skipped: bool, deleted_keys=0, purged_projects=0, removed_temp=0, total_bytes=0)` and `prune(store, storage, now, settings) -> PruneReport`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_pruner.py`:
```python
import logging
import os
from datetime import timedelta

import pytest

from app.config import Settings
from app.persistence.memory import InMemoryStore
from app.persistence.models import ArtifactKind, JobStatus, NewArtifact
from app.storage import LocalArtifactStorage
from app.worker.pruner import prune
from tests.fakes import FakeClock
from tests.test_store_contract import sample_analysis

OWNER = "w"


@pytest.fixture
def env(tmp_path):
    return InMemoryStore(), LocalArtifactStorage(tmp_path / "s"), FakeClock()


def settings(**overrides):
    return Settings(_env_file=None, **overrides)


def job_with_files(store, storage, clock):
    project, job = store.create_project_with_job(
        source_kind="youtube", source_url="u", source_key="youtube:a", title="t", max_attempts=3, now=clock()
    )
    store.claim_next_job(OWNER, 300, clock())
    descriptors = []
    for kind in (ArtifactKind.SOURCE_AUDIO, ArtifactKind.DRUMS_STEM):
        stored = storage.put_bytes(f"projects/{project.id}/{job.id}/{kind.value}", b"data")
        descriptors.append(NewArtifact(kind, stored.key, stored.size_bytes, stored.sha256))
    store.commit_stage(job.id, OWNER, JobStatus.STEMS_SEPARATED, descriptors, None, clock())
    return project, job


def test_removes_source_audio_after_completion_but_keeps_stems(env):
    store, storage, clock = env
    _, job = job_with_files(store, storage, clock)
    store.complete_job(job.id, OWNER, sample_analysis(), clock())

    report = prune(store, storage, clock(), settings())

    artifacts = store.artifacts_for_job(job.id)
    assert report.deleted_keys == 1
    assert not storage.exists(artifacts[ArtifactKind.SOURCE_AUDIO].storage_key)
    assert artifacts[ArtifactKind.SOURCE_AUDIO].pruned_at == clock()
    assert storage.exists(artifacts[ArtifactKind.DRUMS_STEM].storage_key)


def test_failed_job_files_removed_only_after_retention(env):
    store, storage, clock = env
    _, job = job_with_files(store, storage, clock)
    store.fail_job(job.id, OWNER, "boom", clock())

    early = prune(store, storage, clock() + timedelta(days=6), settings(failed_job_retention_days=7))
    late = prune(store, storage, clock() + timedelta(days=8), settings(failed_job_retention_days=7))

    assert early.deleted_keys == 0
    assert late.deleted_keys == 2


def test_soft_deleted_project_files_and_rows_are_purged(env):
    store, storage, clock = env
    project, job = job_with_files(store, storage, clock)
    keys = [a.storage_key for a in store.artifacts_for_job(job.id).values()]
    store.soft_delete_project(project.id, clock())

    report = prune(store, storage, clock(), settings())

    assert report.purged_projects == 1
    assert store.get_project(project.id) is None
    assert not any(storage.exists(key) for key in keys)


def test_skips_when_another_pruner_holds_the_lock(env):
    store, storage, clock = env

    with store.maintenance_lock():
        report = prune(store, storage, clock(), settings())

    assert report.skipped is True


def test_removes_stale_temp_entries(env, tmp_path):
    store, storage, clock = env
    stale = tmp_path / "s" / "tmp" / "old.part"
    stale.write_bytes(b"x")
    long_ago = (clock() - timedelta(days=2)).timestamp()
    os.utime(stale, (long_ago, long_ago))

    report = prune(store, storage, clock(), settings())

    assert report.removed_temp == 1
    assert not stale.exists()


def test_warns_when_storage_exceeds_threshold(env, caplog):
    store, storage, clock = env
    storage.put_bytes("k/big.bin", b"0123456789")

    with caplog.at_level(logging.WARNING, logger="app.worker.pruner"):
        report = prune(store, storage, clock(), settings(storage_warn_bytes=5))

    assert report.total_bytes == 10
    assert "above STORAGE_WARN_BYTES" in caplog.text
```
Note: the pruner compares file mtimes against the fake clock's `now`. `FakeClock` starts at 2026-09-24 12:00 UTC, which is close to real "now", so fresh files written during a test count as recent. Keep it that way. If the clock is ever moved far into the future, pass real-time-relative values in the temp tests instead.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_pruner.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.worker'`.

- [ ] **Step 3: Implement**

`backend/app/worker/pruner.py`:
```python
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.config import Settings
from app.persistence.store import Store
from app.storage import ArtifactStorage

logger = logging.getLogger(__name__)

_TEMP_RETENTION = timedelta(hours=24)


@dataclass(frozen=True)
class PruneReport:
    skipped: bool
    deleted_keys: int = 0
    purged_projects: int = 0
    removed_temp: int = 0
    total_bytes: int = 0


def prune(store: Store, storage: ArtifactStorage, now: datetime, settings: Settings) -> PruneReport:
    """Applies the retention rules in docs/PERSISTENCE.md. Files are deleted
    before their rows are marked pruned, so a crash in between only means
    the next run re-deletes (missing files are fine) and then marks them."""
    with store.maintenance_lock() as acquired:
        if not acquired:
            return PruneReport(skipped=True)

        failed_before = now - timedelta(days=settings.failed_job_retention_days)
        keys = store.disposable_storage_keys(failed_before=failed_before)
        for key in sorted(keys):
            storage.delete(key)
        store.mark_storage_keys_pruned(keys, now)
        purged = store.purge_deleted_projects()
        removed_temp = storage.delete_stale_temp(now - _TEMP_RETENTION)
        total = storage.total_bytes()

    if total > settings.storage_warn_bytes:
        logger.warning("Artifact storage uses %d bytes, above STORAGE_WARN_BYTES=%d", total, settings.storage_warn_bytes)
    logger.info("Pruned %d storage keys, purged %d projects, removed %d temp entries", len(keys), purged, removed_temp)
    return PruneReport(skipped=False, deleted_keys=len(keys), purged_projects=purged, removed_temp=removed_temp, total_bytes=total)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_pruner.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit (checkpoint)**

```bash
git add backend/app/worker backend/tests/test_pruner.py
git commit -m "feat(backend): add artifact pruner with retention rules and advisory lock"
```

---

### Task 12: Worker process: heartbeat, claim loop, graceful stop, entrypoint

**Files:**
- Create: `backend/app/worker/heartbeat.py`, `backend/app/worker/worker.py`, `backend/app/worker/factory.py`, `backend/app/worker/__main__.py`, `backend/tests/test_heartbeat.py`, `backend/tests/test_worker.py`, `backend/tests/test_worker_factory.py`, `backend/tests/test_worker_integration.py`

**Interfaces:**
- Consumes: `process_job`, `JobContext`, `JobAbandoned`, `PipelineEngines`, `prune`, `Settings`, `utc_now`, `create_postgres_store`, `LocalArtifactStorage`.
- Produces:
  - `LeaseHeartbeat(store, job_id, owner, lease_seconds, interval_seconds, clock=utc_now)`: context manager with `.lost: bool`
  - `Worker(*, store, storage, engines, settings, clock=utc_now, owner=None, jitter=random.uniform)` with public attributes `store`, `storage`, `engines`, `settings`, `owner` and methods `run_once() -> bool`, `maybe_prune()`, `run_forever()`, `stop()`
  - `default_owner() -> str`
  - `app.worker.factory.default_engines() -> PipelineEngines` and `build_worker(settings) -> Worker`

Note: the spec's "startup cleanup of temp files older than the lease" is dropped. Another live worker's staging directory can legitimately be older than a lease (Demucs runs up to 600 s), so deleting it would corrupt that run. Temp cleanup happens only in the pruner, at 24 h. This is documented in `docs/PERSISTENCE.md`.

- [ ] **Step 1: Write the failing heartbeat tests**

`backend/tests/test_heartbeat.py`:
```python
import time
from datetime import timedelta

from app.persistence.memory import InMemoryStore
from app.worker.heartbeat import LeaseHeartbeat
from tests.fakes import FakeClock


def claimed_job(store, clock):
    store.create_project_with_job(source_kind="youtube", source_url="u", source_key="k", title="t", max_attempts=3, now=clock())
    return store.claim_next_job("w", 300, clock())


def wait_for(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.005)
    return condition()


def test_heartbeat_extends_the_lease_while_running():
    store, clock = InMemoryStore(), FakeClock()
    job = claimed_job(store, clock)
    clock.advance(100)

    with LeaseHeartbeat(store, job.id, "w", 300, 0.01, clock=clock) as heartbeat:
        extended = wait_for(lambda: store.get_job(job.id).lease_expires_at == clock() + timedelta(seconds=300))

    assert extended
    assert heartbeat.lost is False


def test_heartbeat_flags_a_lost_lease_and_stops():
    store, clock = InMemoryStore(), FakeClock()
    job = claimed_job(store, clock)
    clock.advance(301)
    store.claim_next_job("thief", 300, clock())

    with LeaseHeartbeat(store, job.id, "w", 300, 0.01, clock=clock) as heartbeat:
        lost = wait_for(lambda: heartbeat.lost)

    assert lost


class FlakyStore:
    def __init__(self):
        self.calls = 0

    def extend_lease(self, *args):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("db blip")
        return True


def test_heartbeat_survives_transient_store_errors():
    store = FlakyStore()

    with LeaseHeartbeat(store, "j", "w", 300, 0.01, clock=FakeClock()) as heartbeat:
        recovered = wait_for(lambda: store.calls >= 2)

    assert recovered
    assert heartbeat.lost is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_heartbeat.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.worker.heartbeat'`.

- [ ] **Step 3: Implement the heartbeat**

`backend/app/worker/heartbeat.py`:
```python
import logging
import threading
from collections.abc import Callable
from datetime import datetime

from app.clock import utc_now
from app.persistence.store import Store

logger = logging.getLogger(__name__)


class LeaseHeartbeat:
    """Extends a claimed job's lease every `interval_seconds` on a daemon
    thread while the job runs. If an extension is refused (the lease
    expired and another worker reclaimed the job) `lost` becomes True and
    the runner abandons the job at its next stage checkpoint."""

    def __init__(
        self,
        store: Store,
        job_id: str,
        owner: str,
        lease_seconds: int,
        interval_seconds: float,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._job_id = job_id
        self._owner = owner
        self._lease_seconds = lease_seconds
        self._interval = interval_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"heartbeat-{job_id}")
        self.lost = False

    def __enter__(self) -> "LeaseHeartbeat":
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                extended = self._store.extend_lease(self._job_id, self._owner, self._lease_seconds, self._clock())
            except Exception:  # noqa: BLE001 - a DB blip must not kill the heartbeat; the lease has slack
                logger.exception("Heartbeat for job %s failed; retrying", self._job_id)
                continue
            if not extended:
                logger.warning("Lease on job %s was lost", self._job_id)
                self.lost = True
                return
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_heartbeat.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write the failing worker and factory tests**

`backend/tests/test_worker.py`:
```python
import threading
import time
from datetime import timedelta

import pytest

from app.config import Settings
from app.persistence.memory import InMemoryStore
from app.persistence.models import ArtifactKind, JobStatus
from app.storage import LocalArtifactStorage
from app.worker import worker as worker_module
from app.worker.worker import Worker, default_owner
from tests.fakes import FakeClock, FakeExtractor, make_engines


def settings(**overrides):
    values = {"heartbeat_seconds": 0.01, "poll_interval_seconds": 0.01}
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def parts(tmp_path):
    return InMemoryStore(), LocalArtifactStorage(tmp_path / "s"), FakeClock()


def enqueue(store, clock):
    return store.create_project_with_job(
        source_kind="youtube", source_url="https://youtu.be/dQw4w9WgXcQ", source_key="youtube:dQw4w9WgXcQ",
        title="https://youtu.be/dQw4w9WgXcQ", max_attempts=3, now=clock(),
    )


def make_worker(store, storage, clock, engines=None, **setting_overrides):
    return Worker(
        store=store, storage=storage, engines=engines or make_engines(), settings=settings(**setting_overrides),
        clock=clock, owner="w1", jitter=lambda low, high: 0.0,
    )


def test_default_owner_is_unique_per_call():
    assert default_owner() != default_owner()


def test_worker_generates_an_owner_when_none_is_given(parts):
    store, storage, clock = parts

    worker = Worker(store=store, storage=storage, engines=make_engines(), settings=settings())

    assert worker.owner


def test_run_once_returns_false_when_queue_is_empty(parts):
    store, storage, clock = parts

    assert make_worker(store, storage, clock).run_once() is False


def test_run_once_processes_a_job_to_completion(parts):
    store, storage, clock = parts
    project, job = enqueue(store, clock)

    processed = make_worker(store, storage, clock).run_once()

    assert processed is True
    assert store.get_job(job.id).status == JobStatus.COMPLETED
    assert store.latest_analysis(project.id) is not None


def test_job_past_max_attempts_is_failed_without_running(parts):
    store, storage, clock = parts
    _, job = enqueue(store, clock)
    for _ in range(3):
        store.claim_next_job("crashed", 300, clock())
        clock.advance(301)
    extractor = FakeExtractor()

    make_worker(store, storage, clock, make_engines(extractor=extractor)).run_once()

    failed = store.get_job(job.id)
    assert failed.status == JobStatus.FAILED
    assert failed.error == "Exceeded maximum attempts"
    assert extractor.calls == 0


def test_stop_during_a_job_releases_the_lease_after_the_current_stage(parts):
    store, storage, clock = parts
    _, job = enqueue(store, clock)
    holder = {}
    worker = make_worker(store, storage, clock, make_engines(extractor=FakeExtractor(on_call=lambda: holder["w"].stop())))
    holder["w"] = worker

    worker.run_once()

    released = store.get_job(job.id)
    assert released.lease_owner is None
    assert released.status == JobStatus.DOWNLOADED
    assert ArtifactKind.SOURCE_AUDIO in store.artifacts_for_job(job.id)
    assert store.claim_next_job("w2", 300, clock()).id == job.id


def test_lost_lease_is_logged_not_raised(parts, caplog):
    store, storage, clock = parts
    _, job = enqueue(store, clock)

    def steal():
        store.claim_next_job("thief", 300, clock() + timedelta(days=1))

    make_worker(store, storage, clock, make_engines(extractor=FakeExtractor(on_call=steal))).run_once()

    assert store.get_job(job.id).lease_owner == "thief"
    assert "Lost lease" in caplog.text


def test_maybe_prune_runs_at_most_once_per_interval(parts, monkeypatch):
    store, storage, clock = parts
    calls = []
    monkeypatch.setattr(worker_module, "prune", lambda *args: calls.append(args))
    worker = make_worker(store, storage, clock, prune_interval_seconds=3600)

    worker.maybe_prune()
    worker.maybe_prune()
    clock.advance(3600)
    worker.maybe_prune()

    assert len(calls) == 2


def test_run_forever_drains_the_queue_until_stopped(parts):
    store, storage, clock = parts
    _, job = enqueue(store, clock)
    worker = make_worker(store, storage, clock)
    thread = threading.Thread(target=worker.run_forever)

    thread.start()
    deadline = time.monotonic() + 5
    while store.get_job(job.id).status != JobStatus.COMPLETED and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()
    thread.join(timeout=5)

    assert store.get_job(job.id).status == JobStatus.COMPLETED
    assert not thread.is_alive()
```

`backend/tests/test_worker_factory.py`:
```python
from app.config import Settings
from app.demucs_stem_separator import DemucsStemSeparator
from app.persistence.postgres import PostgresStore
from app.storage import LocalArtifactStorage
from app.worker.factory import build_worker, default_engines
from app.youtube_audio_extractor import YtDlpAudioExtractor


def test_default_engines_use_production_adapters():
    engines = default_engines()

    assert isinstance(engines.extractor, YtDlpAudioExtractor)
    assert isinstance(engines.separator, DemucsStemSeparator)


def test_build_worker_wires_postgres_store_and_local_storage(tmp_path):
    settings = Settings(_env_file=None, storage_root=tmp_path, database_url="postgresql+psycopg://u:p@localhost:1/x")

    worker = build_worker(settings)

    assert isinstance(worker.store, PostgresStore)
    assert isinstance(worker.storage, LocalArtifactStorage)
    assert worker.storage.root == tmp_path
```

- [ ] **Step 6: Run to verify they fail**

Run: `uv run pytest tests/test_worker.py tests/test_worker_factory.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.worker.worker'`.

- [ ] **Step 7: Implement the worker, factory and entrypoint**

`backend/app/worker/worker.py`:
```python
import logging
import os
import random
import socket
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from app.clock import utc_now
from app.config import Settings
from app.persistence.models import LeaseLostError
from app.persistence.store import Store
from app.pipeline.runner import JobAbandoned, JobContext, PipelineEngines, process_job
from app.storage import ArtifactStorage
from app.worker.heartbeat import LeaseHeartbeat
from app.worker.pruner import prune

logger = logging.getLogger(__name__)


def default_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class Worker:
    """Claims one job at a time from the Store queue and processes it. Run
    one Worker per OS process; WORKER_CONCURRENCY processes bound how many
    heavy pipelines run at once."""

    def __init__(
        self,
        *,
        store: Store,
        storage: ArtifactStorage,
        engines: PipelineEngines,
        settings: Settings,
        clock: Callable[[], datetime] = utc_now,
        owner: str | None = None,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.store = store
        self.storage = storage
        self.engines = engines
        self.settings = settings
        self.owner = owner or default_owner()
        self._clock = clock
        self._jitter = jitter
        self._stop = threading.Event()
        self._next_prune_at: datetime | None = None

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> bool:
        job = self.store.claim_next_job(self.owner, self.settings.lease_seconds, self._clock())
        if job is None:
            return False

        # attempts only exceeds max_attempts here when the previous attempt
        # died without recording anything (killed process -> lease expiry).
        if job.attempts > job.max_attempts:
            self.store.fail_job(job.id, self.owner, job.error or "Exceeded maximum attempts", self._clock())
            return True

        logger.info("Worker %s claimed job %s (attempt %d)", self.owner, job.id, job.attempts)
        with LeaseHeartbeat(
            self.store, job.id, self.owner, self.settings.lease_seconds, self.settings.heartbeat_seconds, self._clock
        ) as heartbeat:
            context = JobContext(
                store=self.store,
                storage=self.storage,
                engines=self.engines,
                owner=self.owner,
                retry_base_seconds=self.settings.retry_base_seconds,
                clock=self._clock,
                should_stop=lambda: self._stop.is_set() or heartbeat.lost,
            )
            try:
                process_job(job, context)
            except JobAbandoned:
                if not heartbeat.lost:
                    self.store.release_lease(job.id, self.owner, self._clock())
                logger.info("Worker %s abandoned job %s", self.owner, job.id)
            except LeaseLostError:
                logger.warning("Lost lease on job %s; another worker owns it now", job.id)
        return True

    def maybe_prune(self) -> None:
        now = self._clock()
        if self._next_prune_at is not None and now < self._next_prune_at:
            return
        self._next_prune_at = now + timedelta(seconds=self.settings.prune_interval_seconds)
        prune(self.store, self.storage, now, self.settings)

    def run_forever(self) -> None:
        logger.info("Worker %s started", self.owner)
        while not self._stop.is_set():
            self.maybe_prune()
            if not self.run_once():
                interval = self.settings.poll_interval_seconds
                self._stop.wait(interval + self._jitter(0.0, interval / 2))
        logger.info("Worker %s stopped", self.owner)
```
Note: `test_lost_lease_is_logged_not_raised` passes the store's `LeaseLostError` through `process_job` (the thief's claim happens inside the extractor, so the following `commit_stage` raises).

`backend/app/worker/factory.py`:
```python
from app.config import Settings
from app.demucs_stem_separator import DemucsStemSeparator
from app.drumscript_transcriber import DrumScriptTranscriber
from app.librosa_beat_detector import LibrosaBeatDetector
from app.librosa_tempo_estimator import LibrosaTempoEstimator
from app.persistence.postgres import create_postgres_store
from app.pipeline.runner import PipelineEngines
from app.storage import LocalArtifactStorage
from app.worker.worker import Worker
from app.youtube_audio_extractor import YtDlpAudioExtractor
from app.youtube_source import YouTubeSourceValidator


def default_engines() -> PipelineEngines:
    return PipelineEngines(
        source_validator=YouTubeSourceValidator(),
        extractor=YtDlpAudioExtractor(),
        separator=DemucsStemSeparator(),
        transcriber=DrumScriptTranscriber(),
        tempo_estimator=LibrosaTempoEstimator(),
        beat_detector=LibrosaBeatDetector(),
    )


def build_worker(settings: Settings) -> Worker:
    return Worker(
        store=create_postgres_store(settings.database_url),
        storage=LocalArtifactStorage(settings.storage_root),
        engines=default_engines(),
        settings=settings,
    )
```

`backend/app/worker/__main__.py`:
```python
"""`python -m app.worker`: starts WORKER_CONCURRENCY worker processes.

This module is OS-process and signal glue around build_worker and
Worker.run_forever (both unit-tested). It is exercised by running the
worker, not by pytest, hence the no-cover pragmas."""

import logging
import multiprocessing
import signal

from app.config import get_settings
from app.worker.factory import build_worker


def run_worker_process() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    worker = build_worker(get_settings())
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: worker.stop())
    worker.run_forever()


def main() -> None:  # pragma: no cover - spawns OS processes
    concurrency = get_settings().worker_concurrency
    if concurrency <= 1:
        run_worker_process()
        return

    processes = [
        multiprocessing.Process(target=run_worker_process, name=f"drumscore-worker-{index}")
        for index in range(concurrency)
    ]
    for process in processes:
        process.start()

    def forward(*_: object) -> None:
        for process in processes:
            process.terminate()  # SIGTERM -> each child's graceful stop

    signal.signal(signal.SIGTERM, forward)
    for process in processes:
        process.join()


if __name__ == "__main__":  # pragma: no cover
    main()
```

- [ ] **Step 8: Run to verify the unit tests pass**

Run: `uv run pytest tests/test_heartbeat.py tests/test_worker.py tests/test_worker_factory.py -v`
Expected: all passed.

- [ ] **Step 9: Write and run the Postgres integration tests (the restart story)**

`backend/tests/test_worker_integration.py`:
```python
import pytest

from app.config import Settings
from app.persistence.models import JobStatus
from app.storage import LocalArtifactStorage
from app.worker.worker import Worker
from tests.fakes import FakeClock, FakeExtractor, FakeSeparator, FakeTranscriber, make_engines

pytestmark = pytest.mark.integration


class SimulatedCrash(BaseException):
    """Escapes process_job's `except Exception`, like the process being killed mid-stage."""


def settings():
    return Settings(_env_file=None, heartbeat_seconds=3600, poll_interval_seconds=0.01)


def enqueue(store, clock, video_id):
    url = f"https://youtu.be/{video_id}"
    return store.create_project_with_job(
        source_kind="youtube", source_url=url, source_key=f"youtube:{video_id}", title=url, max_attempts=3, now=clock()
    )


def test_job_survives_a_worker_crash_and_resumes_on_another_worker(postgres_store, tmp_path):
    clock = FakeClock()
    storage = LocalArtifactStorage(tmp_path)
    project, job = enqueue(postgres_store, clock, "dQw4w9WgXcQ")
    extractor, separator = FakeExtractor(), FakeSeparator()
    crashing = Worker(
        store=postgres_store, storage=storage, settings=settings(), clock=clock, owner="a",
        engines=make_engines(extractor=extractor, separator=separator, transcriber=FakeTranscriber(error=SimulatedCrash())),
    )
    with pytest.raises(SimulatedCrash):
        crashing.run_once()
    clock.advance(301)
    survivor = Worker(
        store=postgres_store, storage=storage, settings=settings(), clock=clock, owner="b",
        engines=make_engines(extractor=extractor, separator=separator),
    )

    survivor.run_once()

    finished = postgres_store.get_job(job.id)
    assert finished.status == JobStatus.COMPLETED
    assert finished.attempts == 2
    assert (extractor.calls, separator.calls) == (1, 1)
    assert postgres_store.latest_analysis(project.id) is not None


def test_two_workers_process_two_jobs_once_each(postgres_store, tmp_path):
    clock = FakeClock()
    storage = LocalArtifactStorage(tmp_path)
    enqueue(postgres_store, clock, "aaaaaaaaaaa")
    enqueue(postgres_store, clock, "bbbbbbbbbbb")
    separator = FakeSeparator()
    workers = [
        Worker(store=postgres_store, storage=storage, settings=settings(), clock=clock, owner=name,
               engines=make_engines(separator=separator))
        for name in ("a", "b")
    ]

    results = [worker.run_once() for worker in workers] + [worker.run_once() for worker in workers]

    assert results == [True, True, False, False]
    assert separator.calls == 2
    assert {s.latest_job_status for s in postgres_store.list_live_projects()} == {JobStatus.COMPLETED}
```

Run: `uv run pytest tests/test_worker_integration.py -v`
Expected: 2 passed.

- [ ] **Step 10: Commit (checkpoint)**

```bash
git add backend/app/worker backend/tests/test_heartbeat.py backend/tests/test_worker.py backend/tests/test_worker_factory.py backend/tests/test_worker_integration.py
git commit -m "feat(backend): add lease-heartbeat worker process with graceful stop"
```

---

### Task 13: Projects API replaces the jobs API

**Files:**
- Create: `backend/app/api/schemas.py`, `backend/app/api/projects.py`, `backend/tests/test_projects_api.py`, `backend/tests/test_main.py`
- Modify: `backend/app/main.py`
- Delete: `backend/app/jobs.py`, `backend/app/job_processor.py`, `backend/app/job_cleanup.py`, `backend/app/api/jobs.py`, `backend/tests/test_jobs.py`, `backend/tests/test_job_processor.py`, `backend/tests/test_job_cleanup.py`, `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `Store`, `ArtifactStorage`, `YouTubeSourceValidator`, `Settings`, `utc_now`, `build_event_diagnostics`, `upgrade_to_head`, `process_job`/`JobContext` (tests only).
- Produces: the HTTP contract below, used by the frontend from Task 14 on. Dependency getters for overrides: `get_store`, `get_storage`, `get_source_validator`, `get_clock`, `get_app_settings`.

| call | success | errors |
|---|---|---|
| `POST /api/projects` `{url}` `?force=true` | 201 `{project: Project, job: JobSummary}` | 409 `{detail, existing_project_id}`, 422 `{detail}` |
| `GET /api/projects` | 200 `[{id, title, source_url, updated_at, latest_job_status, has_edits}]` | |
| `GET /api/projects/{id}` | 200 `Project` | 404 |
| `DELETE /api/projects/{id}` | 204 | 404 |
| `POST /api/projects/{id}/retry` | 202 `JobSummary` | 404, 409 |
| `GET /api/projects/{id}/analysis` | 200 `{tempo_bpm, events[], beats[]}` (unchanged shape) | 404, 409 |
| `GET /api/projects/{id}/diagnostics` | 200 (unchanged shape) | 404, 409 |
| `GET /api/projects/{id}/audio/{drums\|accompaniment}` | 200 `audio/wav` | 404, 409, 410, 422 |
| `GET /api/projects/{id}/score` | 200 `{version, score}` | 404 |
| `PUT /api/projects/{id}/score` `{score, base_version}` | 201 `{version}` | 404, 409 `{detail, latest_version}`, 422 |

`JobSummary` = `{id, status, attempts, max_attempts, error, created_at, finished_at}`; `Project` = `{id, title, source_url, created_at, updated_at, latest_job: JobSummary | null}`.

- [ ] **Step 1: Move the response models into `schemas.py`**

Create `backend/app/api/schemas.py`. Move these classes **verbatim** from `backend/app/api/jobs.py`, with the imports they need: `TempoPointResponse`, `BeatPointResponse`, `TempoMapResponse`, `DrumEventResponse`, `AnalysisResponse`, `EventDiagnosticResponse`, `DiagnosticsResponse`. Then add:
```python
from datetime import datetime
from typing import Any

from app.persistence.models import Job, JobStatus, Project, ProjectSummary


class JobSummaryResponse(BaseModel):
    id: str
    status: JobStatus
    attempts: int
    max_attempts: int
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None

    @classmethod
    def from_job(cls, job: Job) -> "JobSummaryResponse":
        return cls(
            id=job.id,
            status=job.status,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            error=job.error,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )


class ProjectResponse(BaseModel):
    id: str
    title: str
    source_url: str
    created_at: datetime
    updated_at: datetime
    latest_job: JobSummaryResponse | None = None

    @classmethod
    def build(cls, project: Project, job: Job | None) -> "ProjectResponse":
        return cls(
            id=project.id,
            title=project.title,
            source_url=project.source_url,
            created_at=project.created_at,
            updated_at=project.updated_at,
            latest_job=JobSummaryResponse.from_job(job) if job else None,
        )


class CreateProjectRequest(BaseModel):
    url: str


class CreateProjectResponse(BaseModel):
    project: ProjectResponse
    job: JobSummaryResponse


class DuplicateProjectResponse(BaseModel):
    detail: str
    existing_project_id: str


class ProjectListItemResponse(BaseModel):
    id: str
    title: str
    source_url: str
    updated_at: datetime
    latest_job_status: JobStatus | None = None
    has_edits: bool

    @classmethod
    def from_summary(cls, summary: ProjectSummary) -> "ProjectListItemResponse":
        return cls(
            id=summary.project.id,
            title=summary.project.title,
            source_url=summary.project.source_url,
            updated_at=summary.project.updated_at,
            latest_job_status=summary.latest_job_status,
            has_edits=summary.has_edits,
        )


class SavedScoreResponse(BaseModel):
    version: int
    score: dict[str, Any]


class SaveScoreRequest(BaseModel):
    score: dict[str, Any]
    base_version: int | None = None


class SaveScoreResponse(BaseModel):
    version: int


class ScoreConflictResponse(BaseModel):
    detail: str
    latest_version: int | None = None
```
Put all imports together at the top of the file.

- [ ] **Step 2: Write the failing API tests**

`backend/tests/test_projects_api.py`:
```python
import pytest
from fastapi.testclient import TestClient

from app.api.projects import get_app_settings, get_clock, get_source_validator, get_storage, get_store
from app.audio_extraction import AudioExtractionError
from app.config import Settings
from app.main import app
from app.persistence.memory import InMemoryStore
from app.persistence.models import ArtifactKind
from app.pipeline.runner import JobContext, process_job
from app.storage import LocalArtifactStorage
from app.youtube_source import YouTubeSourceValidator
from tests.fakes import FakeClock, FakeExtractor, make_engines

URL = "https://youtu.be/dQw4w9WgXcQ"
OTHER_URL = "https://youtu.be/aaaaaaaaaaa"
MISSING = "00000000-0000-0000-0000-000000000000"


def override(store, storage, clock):
    app.dependency_overrides.update({
        get_store: lambda: store,
        get_storage: lambda: storage,
        get_source_validator: YouTubeSourceValidator,
        get_clock: lambda: clock,
        get_app_settings: lambda: Settings(_env_file=None),
    })


class Harness:
    def __init__(self, store, storage, clock):
        self.store, self.storage, self.clock = store, storage, clock
        self.client = TestClient(app)

    def process_next(self, engines=None):
        job = self.store.claim_next_job("w", 300, self.clock())
        process_job(job, JobContext(self.store, self.storage, engines or make_engines(), "w", 30, self.clock))
        return self.store.get_job(job.id)

    def create(self, url=URL, force=False):
        return self.client.post("/api/projects" + ("?force=true" if force else ""), json={"url": url})

    def completed_project(self, url=URL):
        project_id = self.create(url).json()["project"]["id"]
        self.process_next()
        return project_id


@pytest.fixture
def harness(tmp_path):
    store, storage, clock = InMemoryStore(), LocalArtifactStorage(tmp_path / "s"), FakeClock()
    override(store, storage, clock)
    yield Harness(store, storage, clock)
    app.dependency_overrides.clear()


def test_create_enqueues_a_project_without_running_the_pipeline(harness):
    response = harness.create()

    body = response.json()
    assert response.status_code == 201
    assert body["project"]["title"] == URL
    assert body["project"]["source_url"] == URL
    assert body["job"]["status"] == "queued"
    assert body["project"]["latest_job"]["id"] == body["job"]["id"]
    assert harness.store.get_job(body["job"]["id"]).attempts == 0


def test_create_rejects_unsupported_urls(harness):
    response = harness.create("https://example.com/song")

    assert response.status_code == 422
    assert "not a supported YouTube URL" in response.json()["detail"]


def test_duplicate_source_reports_existing_project(harness):
    first = harness.create().json()["project"]["id"]

    response = harness.create("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert response.status_code == 409
    assert response.json()["existing_project_id"] == first


def test_forced_duplicate_creates_new_project_with_existing_title(harness):
    first = harness.completed_project()

    response = harness.create(force=True)

    assert response.status_code == 201
    assert response.json()["project"]["id"] != first
    assert response.json()["project"]["title"] == "Fake Song"


def test_list_returns_live_projects_with_status(harness):
    project_id = harness.completed_project()
    other = harness.create(OTHER_URL).json()["project"]["id"]
    harness.client.delete(f"/api/projects/{other}")

    response = harness.client.get("/api/projects")

    assert response.status_code == 200
    assert [(p["id"], p["latest_job_status"], p["has_edits"]) for p in response.json()] == [
        (project_id, "completed", False)
    ]


def test_get_project_and_404(harness):
    project_id = harness.create().json()["project"]["id"]

    found = harness.client.get(f"/api/projects/{project_id}")
    missing = harness.client.get(f"/api/projects/{MISSING}")

    assert found.status_code == 200
    assert found.json()["latest_job"]["status"] == "queued"
    assert missing.status_code == 404


def test_delete_soft_deletes_and_hides_project(harness):
    project_id = harness.create().json()["project"]["id"]

    deleted = harness.client.delete(f"/api/projects/{project_id}")
    again = harness.client.delete(f"/api/projects/{project_id}")

    assert deleted.status_code == 204
    assert again.status_code == 404
    assert harness.client.get(f"/api/projects/{project_id}").status_code == 404


def test_analysis_is_409_until_completed_then_returns_contract_shape(harness):
    project_id = harness.create().json()["project"]["id"]

    early = harness.client.get(f"/api/projects/{project_id}/analysis")
    harness.process_next()
    ready = harness.client.get(f"/api/projects/{project_id}/analysis")

    assert early.status_code == 409
    assert "job status is queued" in early.json()["detail"]
    body = ready.json()
    assert body["tempo_bpm"] == 120.0
    assert {e["id"] for e in body["events"]} == {"e1", "e2"}
    assert body["events"][0]["time"] == 0.5 + 1e-9
    assert body["events"][0]["measure"] is not None
    assert len(body["beats"]) == 4


def test_diagnostics_before_and_after_completion(harness):
    project_id = harness.create().json()["project"]["id"]

    early = harness.client.get(f"/api/projects/{project_id}/diagnostics")
    harness.process_next()
    ready = harness.client.get(f"/api/projects/{project_id}/diagnostics")

    assert early.status_code == 409
    assert ready.status_code == 200
    assert ready.json()["events"][0]["source_time"] == 0.5 + 1e-9


@pytest.mark.parametrize("stem, content", [("drums", b"fake drums"), ("accompaniment", b"fake accompaniment")])
def test_audio_is_served_from_storage(harness, stem, content):
    project_id = harness.completed_project()

    response = harness.client.get(f"/api/projects/{project_id}/audio/{stem}")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "audio/wav"


def test_audio_409_before_ready_and_422_for_unknown_stem(harness):
    project_id = harness.create().json()["project"]["id"]

    assert harness.client.get(f"/api/projects/{project_id}/audio/drums").status_code == 409
    assert harness.client.get(f"/api/projects/{project_id}/audio/vocals").status_code == 422


def test_audio_409_when_analysis_has_no_stem_artifact(harness):
    project_id = harness.completed_project()
    job = harness.store.latest_job(project_id)
    harness.store._artifacts = {k: a for k, a in harness.store._artifacts.items() if a.job_id != job.id}

    assert harness.client.get(f"/api/projects/{project_id}/audio/drums").status_code == 409


def test_audio_410_when_pruned(harness):
    project_id = harness.completed_project()
    job = harness.store.latest_job(project_id)
    key = harness.store.artifacts_for_job(job.id)[ArtifactKind.DRUMS_STEM].storage_key
    harness.store.mark_storage_keys_pruned({key}, harness.clock())

    assert harness.client.get(f"/api/projects/{project_id}/audio/drums").status_code == 410


def test_responses_never_expose_storage_locations(harness, tmp_path):
    project_id = harness.completed_project()

    bodies = [
        harness.client.get("/api/projects").text,
        harness.client.get(f"/api/projects/{project_id}").text,
        harness.client.get(f"/api/projects/{project_id}/analysis").text,
    ]

    assert not any(str(tmp_path) in body or "projects/" in body for body in bodies)


def test_retry_requeues_failed_job_only(harness):
    project_id = harness.create().json()["project"]["id"]
    not_failed = harness.client.post(f"/api/projects/{project_id}/retry")
    harness.process_next(make_engines(extractor=FakeExtractor(error=AudioExtractionError("gone"))))

    retried = harness.client.post(f"/api/projects/{project_id}/retry")

    assert not_failed.status_code == 409
    assert retried.status_code == 202
    assert retried.json()["status"] == "queued"
    assert retried.json()["attempts"] == 0


def test_score_lifecycle(harness):
    project_id = harness.completed_project()
    score = {"measures": [[{"type": "rest", "id": "r1", "position": {"measure": 1, "beat": 1, "subdivision": 0}, "duration": "w"}]]}

    missing = harness.client.get(f"/api/projects/{project_id}/score")
    first = harness.client.put(f"/api/projects/{project_id}/score", json={"score": score, "base_version": None})
    loaded = harness.client.get(f"/api/projects/{project_id}/score")
    stale = harness.client.put(f"/api/projects/{project_id}/score", json={"score": score, "base_version": None})
    second = harness.client.put(f"/api/projects/{project_id}/score", json={"score": score, "base_version": 1})

    assert missing.status_code == 404
    assert first.status_code == 201
    assert first.json() == {"version": 1}
    assert loaded.json() == {"version": 1, "score": score}
    assert stale.status_code == 409
    assert stale.json()["latest_version"] == 1
    assert second.json() == {"version": 2}
    assert harness.client.get("/api/projects").json()[0]["has_edits"] is True


def test_score_save_validation(harness):
    project_id = harness.completed_project()
    queued = harness.create(OTHER_URL).json()["project"]["id"]

    malformed = harness.client.put(f"/api/projects/{project_id}/score", json={"score": {"bars": []}})
    not_ready = harness.client.put(f"/api/projects/{queued}/score", json={"score": {"measures": []}})
    unknown = harness.client.put(f"/api/projects/{MISSING}/score", json={"score": {"measures": []}})

    assert malformed.status_code == 422
    assert not_ready.status_code == 409
    assert unknown.status_code == 404


@pytest.mark.integration
def test_project_survives_restart_with_saved_edits(postgres_store, migrated_postgres_url, tmp_path):
    from app.persistence.postgres import create_postgres_store

    storage, clock = LocalArtifactStorage(tmp_path / "s"), FakeClock()
    try:
        override(postgres_store, storage, clock)
        before = TestClient(app)
        project_id = before.post("/api/projects", json={"url": URL}).json()["project"]["id"]
        job = postgres_store.claim_next_job("w", 300, clock())
        process_job(job, JobContext(postgres_store, storage, make_engines(), "w", 30, clock))
        before.put(f"/api/projects/{project_id}/score", json={"score": {"measures": [["edited"]]}, "base_version": None})

        restarted_store = create_postgres_store(migrated_postgres_url)
        override(restarted_store, storage, clock)
        after = TestClient(app)
        analysis = after.get(f"/api/projects/{project_id}/analysis")
        score = after.get(f"/api/projects/{project_id}/score")
        audio = after.get(f"/api/projects/{project_id}/audio/drums")
        restarted_store.engine.dispose()
    finally:
        app.dependency_overrides.clear()

    assert analysis.status_code == 200
    assert score.json() == {"version": 1, "score": {"measures": [["edited"]]}}
    assert audio.content == b"fake drums"
```
Note: `test_audio_409_when_analysis_has_no_stem_artifact` reaches into the in-memory store's private dict to simulate a missing artifact row. This is the only test that does so. It is kept because the 409 branch is otherwise unreachable through the public API.

`backend/tests/test_main.py`:
```python
from fastapi.testclient import TestClient

from app import main
from app.config import Settings


def test_startup_runs_migrations_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None, database_url="postgresql+psycopg://x"))
    monkeypatch.setattr(main, "upgrade_to_head", calls.append)

    with TestClient(main.app):
        pass

    assert calls == ["postgresql+psycopg://x"]


def test_startup_skips_migrations_when_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None, run_migrations_on_startup=False))
    monkeypatch.setattr(main, "upgrade_to_head", calls.append)

    with TestClient(main.app):
        pass

    assert calls == []
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_projects_api.py tests/test_main.py -v -m "not integration"`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.api.projects'`.

- [ ] **Step 4: Implement the router**

`backend/app/api/projects.py`:
```python
import logging
from collections.abc import Callable
from datetime import datetime
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse

from app.api.schemas import (
    AnalysisResponse,
    BeatPointResponse,
    CreateProjectRequest,
    CreateProjectResponse,
    DiagnosticsResponse,
    DrumEventResponse,
    DuplicateProjectResponse,
    EventDiagnosticResponse,
    JobSummaryResponse,
    ProjectListItemResponse,
    ProjectResponse,
    SavedScoreResponse,
    SaveScoreRequest,
    SaveScoreResponse,
    ScoreConflictResponse,
)
from app.clock import utc_now
from app.config import Settings, get_settings
from app.diagnostics import build_event_diagnostics
from app.media_source import InvalidSourceUrlError, MediaSourceValidator
from app.persistence.models import Analysis, ArtifactKind, JobStatus, Project, ScoreVersionConflictError
from app.persistence.postgres import create_postgres_store
from app.persistence.store import Store
from app.storage import ArtifactStorage, LocalArtifactStorage
from app.youtube_source import YouTubeSourceValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

_STEM_KINDS = {"drums": ArtifactKind.DRUMS_STEM, "accompaniment": ArtifactKind.ACCOMPANIMENT_STEM}


# The getters below are the production wiring. Tests replace every one of
# them through app.dependency_overrides, so their bodies only run in the
# real server.
@lru_cache
def get_store() -> Store:  # pragma: no cover - production wiring, overridden in tests
    return create_postgres_store(get_settings().database_url)


@lru_cache
def get_storage() -> ArtifactStorage:  # pragma: no cover - production wiring, overridden in tests
    return LocalArtifactStorage(get_settings().storage_root)


def get_source_validator() -> MediaSourceValidator:  # pragma: no cover - production wiring, overridden in tests
    return YouTubeSourceValidator()


def get_clock() -> Callable[[], datetime]:  # pragma: no cover - production wiring, overridden in tests
    return utc_now


def get_app_settings() -> Settings:  # pragma: no cover - production wiring, overridden in tests
    return get_settings()


def _live_project(store: Store, project_id: str) -> Project:
    project = store.get_project(project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _require_analysis(store: Store, project: Project, what: str) -> Analysis:
    analysis = store.latest_analysis(project.id)
    if analysis is None:
        job = store.latest_job(project.id)
        status = job.status.value if job else "unknown"
        raise HTTPException(status_code=409, detail=f"{what} not available yet: job status is {status}")
    return analysis


@router.post("", status_code=201, response_model=CreateProjectResponse, responses={409: {"model": DuplicateProjectResponse}})
def create_project(
    request: CreateProjectRequest,
    force: bool = False,
    store: Store = Depends(get_store),
    validator: MediaSourceValidator = Depends(get_source_validator),
    settings: Settings = Depends(get_app_settings),
    clock: Callable[[], datetime] = Depends(get_clock),
):
    url = request.url.strip()
    try:
        source = validator.parse(url)
    except InvalidSourceUrlError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    source_key = f"{source.provider}:{source.external_id}"
    existing = store.find_live_project_by_source_key(source_key)
    if existing is not None and not force:
        return JSONResponse(
            status_code=409,
            content={"detail": "A project for this song already exists", "existing_project_id": existing.id},
        )

    project, job = store.create_project_with_job(
        source_kind=source.provider,
        source_url=url,
        source_key=source_key,
        title=existing.title if existing else url,
        max_attempts=settings.max_attempts,
        now=clock(),
    )
    logger.info("Created project %s (job %s, correlation %s)", project.id, job.id, job.correlation_id)
    return CreateProjectResponse(project=ProjectResponse.build(project, job), job=JobSummaryResponse.from_job(job))


@router.get("", response_model=list[ProjectListItemResponse])
def list_projects(store: Store = Depends(get_store)) -> list[ProjectListItemResponse]:
    return [ProjectListItemResponse.from_summary(summary) for summary in store.list_live_projects()]


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, store: Store = Depends(get_store)) -> ProjectResponse:
    project = _live_project(store, project_id)
    return ProjectResponse.build(project, store.latest_job(project.id))


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str, store: Store = Depends(get_store), clock: Callable[[], datetime] = Depends(get_clock)
) -> Response:
    _live_project(store, project_id)
    store.soft_delete_project(project_id, clock())
    return Response(status_code=204)


@router.post("/{project_id}/retry", status_code=202, response_model=JobSummaryResponse)
def retry_project(
    project_id: str, store: Store = Depends(get_store), clock: Callable[[], datetime] = Depends(get_clock)
) -> JobSummaryResponse:
    project = _live_project(store, project_id)
    job = store.latest_job(project.id)
    if job is None or job.status != JobStatus.FAILED:
        status = job.status.value if job else "unknown"
        raise HTTPException(status_code=409, detail=f"Only a failed job can be retried; current status is {status}")
    return JobSummaryResponse.from_job(store.requeue_failed_job(job.id, clock()))


@router.get("/{project_id}/analysis", response_model=AnalysisResponse)
def get_analysis(project_id: str, store: Store = Depends(get_store)) -> AnalysisResponse:
    analysis = _require_analysis(store, _live_project(store, project_id), "Analysis")
    return AnalysisResponse(
        tempo_bpm=analysis.tempo_bpm,
        events=[DrumEventResponse.from_event(event) for event in analysis.events],
        beats=[BeatPointResponse.from_domain(beat) for beat in analysis.beats],
    )


@router.get("/{project_id}/diagnostics", response_model=DiagnosticsResponse)
def get_diagnostics(project_id: str, store: Store = Depends(get_store)) -> DiagnosticsResponse:
    analysis = _require_analysis(store, _live_project(store, project_id), "Diagnostics")
    diagnostics = build_event_diagnostics(analysis.raw_events, analysis.events, analysis.tempo_bpm, beats=analysis.beats)
    return DiagnosticsResponse(
        tempo_bpm=analysis.tempo_bpm,
        events=[EventDiagnosticResponse.from_diagnostic(d) for d in diagnostics],
    )


@router.get("/{project_id}/audio/{stem}")
def get_audio(
    project_id: str,
    stem: Literal["drums", "accompaniment"],
    store: Store = Depends(get_store),
    storage: ArtifactStorage = Depends(get_storage),
) -> FileResponse:
    analysis = _require_analysis(store, _live_project(store, project_id), "Audio")
    artifact = store.artifacts_for_job(analysis.job_id).get(_STEM_KINDS[stem])
    if artifact is None:
        raise HTTPException(status_code=409, detail="Audio not available yet")
    if artifact.pruned_at is not None or not storage.exists(artifact.storage_key):
        raise HTTPException(status_code=410, detail="Audio has been removed; re-process the project")
    return FileResponse(storage.path(artifact.storage_key), media_type="audio/wav")


@router.get("/{project_id}/score", response_model=SavedScoreResponse)
def get_score(project_id: str, store: Store = Depends(get_store)) -> SavedScoreResponse:
    project = _live_project(store, project_id)
    saved = store.latest_score(project.id)
    if saved is None:
        raise HTTPException(status_code=404, detail="No saved score for this project")
    return SavedScoreResponse(version=saved.version, score=saved.score)


@router.put("/{project_id}/score", status_code=201, response_model=SaveScoreResponse, responses={409: {"model": ScoreConflictResponse}})
def save_score(
    project_id: str,
    request: SaveScoreRequest,
    store: Store = Depends(get_store),
    clock: Callable[[], datetime] = Depends(get_clock),
):
    project = _live_project(store, project_id)
    if not isinstance(request.score.get("measures"), list):
        raise HTTPException(status_code=422, detail="Invalid score: expected an object with a measures array")
    analysis = _require_analysis(store, project, "Score saving")
    try:
        saved = store.save_score(project.id, analysis.id, request.score, request.base_version, clock())
    except ScoreVersionConflictError as conflict:
        return JSONResponse(
            status_code=409,
            content={"detail": "A newer version of this score was saved elsewhere", "latest_version": conflict.latest_version},
        )
    return SaveScoreResponse(version=saved.version)
```

- [ ] **Step 5: Rewire `main.py` and delete the legacy job path**

`backend/app/main.py`:
```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.projects import router as projects_router
from app.config import get_settings
from app.persistence.migrations import upgrade_to_head

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=True,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.run_migrations_on_startup:
        upgrade_to_head(settings.database_url)
    yield


app = FastAPI(title="Drumscore API", lifespan=lifespan)
app.include_router(projects_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def get_health() -> dict[str, str]:
    return {"status": "ok"}
```

Delete the legacy modules and their tests. Use `git rm` if commits are authorized, otherwise plain `rm`:
```bash
rm backend/app/jobs.py backend/app/job_processor.py backend/app/job_cleanup.py backend/app/api/jobs.py backend/tests/test_jobs.py backend/tests/test_job_processor.py backend/tests/test_job_cleanup.py backend/tests/test_jobs_api.py
```
Run: `grep -rn "app.jobs\|job_processor\|job_cleanup\|app.api.jobs\|JobStore\|PipelineConcurrencyLimiter" backend/app backend/tests`
Expected: no output.

- [ ] **Step 6: Run the whole backend suite with coverage**

Run: `uv run pytest --cov=app --cov-report=term-missing`
Expected: everything passes (Docker running). For each new module, the only uncovered lines are the documented `# pragma: no cover` production wiring and process glue. Add tests for anything else that is uncovered.

- [ ] **Step 7: Commit (checkpoint)**

```bash
git add -A backend
git commit -m "feat(backend): replace in-memory jobs API with persistent projects API"
```

---

### Task 14: Frontend API client for projects

**Files:**
- Create: `frontend/lib/api/types.ts`, `frontend/lib/api/projects.ts`, `frontend/lib/api/__mocks__/projects.ts`, `frontend/lib/api/__tests__/projects.test.ts`
- Modify: `frontend/lib/api/jobs.ts` (re-export the moved types until Task 18 deletes it), plus every file importing types from `@/lib/api/jobs` (listed below)

**Interfaces:**
- Produces (`types.ts`): `DrumInstrument`, `AnalysisEvent`, `Beat`, `Analysis`, moved verbatim from `jobs.ts`.
- Produces (`projects.ts`):
  - types `JobStatus` (`"queued" | "downloading" | "downloaded" | "separating_stems" | "stems_separated" | "transcribing" | "transcribed" | "mapping_tempo" | "completed" | "failed"`), `JobSummary`, `Project`, `ProjectListItem`, `CreatedProject`, `SavedScore`, `Stem`
  - errors `NotFoundError`, `DuplicateProjectError(message, existingProjectId)`, `ScoreConflictError(message, latestVersion)`
  - functions `createProject(baseUrl, url, { force? })`, `listProjects(baseUrl)`, `getProject(baseUrl, id)`, `deleteProject(baseUrl, id)`, `retryProject(baseUrl, id)`, `getAnalysis(baseUrl, id)`, `getSavedScore(baseUrl, id): Promise<SavedScore | null>`, `saveScore(baseUrl, id, score: unknown, baseVersion: number | null): Promise<number>`, `audioUrl(baseUrl, id, stem): string`
- Produces (`__mocks__/projects.ts`): `jest.fn()` for every function (`audioUrl` keeps the real implementation), and the real error classes.

- [ ] **Step 1: Move the shared types**

Create `frontend/lib/api/types.ts` by moving `DrumInstrument`, `AnalysisEvent`, `Beat` and `Analysis` verbatim out of `frontend/lib/api/jobs.ts`. In `jobs.ts`, replace those four definitions with:
```ts
import type { Analysis } from "./types";

export type { Analysis, AnalysisEvent, Beat, DrumInstrument } from "./types";
```
Point every other type-only importer at the new module (JobForm and its tests keep `jobs.ts` until Task 18):
```bash
cd frontend
for f in components/Player.tsx components/__tests__/DrumScore.test.tsx lib/audio/metronomeScheduling.ts lib/audio/PracticeTransport.ts lib/audio/__tests__/metronomeScheduling.test.ts lib/audio/__tests__/PracticeTransport.test.ts lib/notation/instrumentNotation.ts lib/notation/__fixtures__/grooves.ts lib/score/buildScore.ts lib/score/transformations.ts lib/score/types.ts lib/score/useScoreEditor.ts lib/score/__fixtures__/lowConfidenceGroove.ts lib/score/__tests__/buildScore.test.ts lib/score/__tests__/transformations.test.ts lib/score/__tests__/useScoreEditor.test.ts; do sed -i 's#@/lib/api/jobs#@/lib/api/types#' "$f"; done
pnpm exec tsc --noEmit && pnpm test
```
Expected: type-check clean, all existing tests pass.

- [ ] **Step 2: Write the failing client tests**

`frontend/lib/api/__tests__/projects.test.ts`:
```ts
import {
  audioUrl,
  createProject,
  deleteProject,
  DuplicateProjectError,
  getAnalysis,
  getProject,
  getSavedScore,
  listProjects,
  NotFoundError,
  retryProject,
  saveScore,
  ScoreConflictError,
} from "../projects";

const BASE = "http://localhost:8000";

function respond(status: number, body?: unknown) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: body === undefined ? () => Promise.reject(new Error("no body")) : () => Promise.resolve(body),
  } as Response);
}

describe("createProject", () => {
  it("should post the URL and return the created project", async () => {
    respond(201, { project: { id: "p1" }, job: { id: "j1", status: "queued" } });

    const result = await createProject(BASE, "https://youtu.be/x");

    expect(result.project.id).toBe("p1");
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: "https://youtu.be/x" }),
    });
  });

  it("should add the force flag when asked", async () => {
    respond(201, { project: { id: "p2" }, job: { id: "j2" } });

    await createProject(BASE, "https://youtu.be/x", { force: true });

    expect((global.fetch as jest.Mock).mock.calls[0][0]).toBe(`${BASE}/api/projects?force=true`);
  });

  it("should throw a DuplicateProjectError carrying the existing project id", async () => {
    respond(409, { detail: "A project for this song already exists", existing_project_id: "p1" });

    const error = await createProject(BASE, "https://youtu.be/x").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(DuplicateProjectError);
    expect((error as DuplicateProjectError).existingProjectId).toBe("p1");
  });

  it("should throw the backend detail for other errors", async () => {
    respond(422, { detail: "'x' is not a supported YouTube URL" });

    await expect(createProject(BASE, "x")).rejects.toThrow("'x' is not a supported YouTube URL");
  });
});

describe("listProjects", () => {
  it("should return the project list", async () => {
    respond(200, [{ id: "p1", title: "Song" }]);

    const result = await listProjects(BASE);

    expect(result).toEqual([{ id: "p1", title: "Song" }]);
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects`);
  });
});

describe("getProject", () => {
  it("should return the project", async () => {
    respond(200, { id: "p1", latest_job: { status: "completed" } });

    const result = await getProject(BASE, "p1");

    expect(result.latest_job?.status).toBe("completed");
  });

  it("should throw NotFoundError on 404", async () => {
    respond(404, { detail: "Project not found" });

    await expect(getProject(BASE, "p1")).rejects.toBeInstanceOf(NotFoundError);
  });

  it("should fall back to a generic message when the error body is not JSON", async () => {
    respond(500);

    await expect(getProject(BASE, "p1")).rejects.toThrow("Request failed (500)");
  });
});

describe("deleteProject", () => {
  it("should send DELETE and resolve on 204", async () => {
    respond(204);

    await deleteProject(BASE, "p1");

    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects/p1`, { method: "DELETE" });
  });

  it("should throw when deletion fails", async () => {
    respond(404, { detail: "Project not found" });

    await expect(deleteProject(BASE, "p1")).rejects.toBeInstanceOf(NotFoundError);
  });
});

describe("retryProject", () => {
  it("should post to the retry endpoint", async () => {
    respond(202, { id: "j1", status: "queued" });

    const result = await retryProject(BASE, "p1");

    expect(result.status).toBe("queued");
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects/p1/retry`, { method: "POST" });
  });
});

describe("getAnalysis", () => {
  it("should fetch the project analysis", async () => {
    respond(200, { tempo_bpm: 120, events: [], beats: [] });

    const result = await getAnalysis(BASE, "p1");

    expect(result.tempo_bpm).toBe(120);
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects/p1/analysis`);
  });
});

describe("getSavedScore", () => {
  it("should return the saved score", async () => {
    respond(200, { version: 3, score: { measures: [] } });

    const result = await getSavedScore(BASE, "p1");

    expect(result).toEqual({ version: 3, score: { measures: [] } });
  });

  it("should return null when nothing was saved", async () => {
    respond(404, { detail: "No saved score for this project" });

    const result = await getSavedScore(BASE, "p1");

    expect(result).toBeNull();
  });
});

describe("saveScore", () => {
  it("should put the score with its base version and return the new version", async () => {
    respond(201, { version: 2 });

    const version = await saveScore(BASE, "p1", { measures: [] }, 1);

    expect(version).toBe(2);
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/api/projects/p1/score`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ score: { measures: [] }, base_version: 1 }),
    });
  });

  it("should throw ScoreConflictError with the latest version on 409", async () => {
    respond(409, { detail: "A newer version of this score was saved elsewhere", latest_version: 4 });

    const error = await saveScore(BASE, "p1", { measures: [] }, 1).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ScoreConflictError);
    expect((error as ScoreConflictError).latestVersion).toBe(4);
  });

  it("should default the latest version to null when the conflict body lacks it", async () => {
    respond(409, {});

    const error = await saveScore(BASE, "p1", { measures: [] }, null).catch((e: unknown) => e);

    expect((error as ScoreConflictError).latestVersion).toBeNull();
  });
});

describe("audioUrl", () => {
  it("should build the stem URL", () => {
    expect(audioUrl(BASE, "p1", "drums")).toBe(`${BASE}/api/projects/p1/audio/drums`);
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `pnpm test lib/api/__tests__/projects.test.ts`
Expected: FAIL, `Cannot find module '../projects'`.

- [ ] **Step 4: Implement the client and its mock**

`frontend/lib/api/projects.ts`:
```ts
import type { Analysis } from "./types";

export type JobStatus =
  | "queued"
  | "downloading"
  | "downloaded"
  | "separating_stems"
  | "stems_separated"
  | "transcribing"
  | "transcribed"
  | "mapping_tempo"
  | "completed"
  | "failed";

export interface JobSummary {
  id: string;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Project {
  id: string;
  title: string;
  source_url: string;
  created_at: string;
  updated_at: string;
  latest_job: JobSummary | null;
}

export interface ProjectListItem {
  id: string;
  title: string;
  source_url: string;
  updated_at: string;
  latest_job_status: JobStatus | null;
  has_edits: boolean;
}

export interface CreatedProject {
  project: Project;
  job: JobSummary;
}

export interface SavedScore {
  version: number;
  score: unknown;
}

export type Stem = "drums" | "accompaniment";

export class NotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotFoundError";
  }
}

export class DuplicateProjectError extends Error {
  constructor(
    message: string,
    readonly existingProjectId: string,
  ) {
    super(message);
    this.name = "DuplicateProjectError";
  }
}

export class ScoreConflictError extends Error {
  constructor(
    message: string,
    readonly latestVersion: number | null,
  ) {
    super(message);
    this.name = "ScoreConflictError";
  }
}

const JSON_HEADERS = { "Content-Type": "application/json" };

type ErrorBody = { detail?: string; existing_project_id?: string; latest_version?: number | null };

async function readErrorBody(response: Response): Promise<ErrorBody> {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

async function failure(response: Response): Promise<never> {
  const body = await readErrorBody(response);
  const message = body.detail ?? `Request failed (${response.status})`;
  throw response.status === 404 ? new NotFoundError(message) : new Error(message);
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    return failure(response);
  }
  return response.json();
}

export async function createProject(
  baseUrl: string,
  url: string,
  options: { force?: boolean } = {},
): Promise<CreatedProject> {
  const query = options.force ? "?force=true" : "";
  const response = await fetch(`${baseUrl}/api/projects${query}`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ url }),
  });
  if (response.status === 409) {
    const body = await readErrorBody(response);
    throw new DuplicateProjectError(body.detail ?? "Project already exists", String(body.existing_project_id));
  }
  return parse<CreatedProject>(response);
}

export async function listProjects(baseUrl: string): Promise<ProjectListItem[]> {
  return parse<ProjectListItem[]>(await fetch(`${baseUrl}/api/projects`));
}

export async function getProject(baseUrl: string, id: string): Promise<Project> {
  return parse<Project>(await fetch(`${baseUrl}/api/projects/${id}`));
}

export async function deleteProject(baseUrl: string, id: string): Promise<void> {
  const response = await fetch(`${baseUrl}/api/projects/${id}`, { method: "DELETE" });
  if (!response.ok) {
    await failure(response);
  }
}

export async function retryProject(baseUrl: string, id: string): Promise<JobSummary> {
  return parse<JobSummary>(await fetch(`${baseUrl}/api/projects/${id}/retry`, { method: "POST" }));
}

export async function getAnalysis(baseUrl: string, id: string): Promise<Analysis> {
  return parse<Analysis>(await fetch(`${baseUrl}/api/projects/${id}/analysis`));
}

export async function getSavedScore(baseUrl: string, id: string): Promise<SavedScore | null> {
  const response = await fetch(`${baseUrl}/api/projects/${id}/score`);
  if (response.status === 404) {
    return null;
  }
  return parse<SavedScore>(response);
}

export async function saveScore(
  baseUrl: string,
  id: string,
  score: unknown,
  baseVersion: number | null,
): Promise<number> {
  const response = await fetch(`${baseUrl}/api/projects/${id}/score`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ score, base_version: baseVersion }),
  });
  if (response.status === 409) {
    const body = await readErrorBody(response);
    throw new ScoreConflictError(
      body.detail ?? "A newer version of this score was saved elsewhere",
      body.latest_version ?? null,
    );
  }
  const body = await parse<{ version: number }>(response);
  return body.version;
}

export function audioUrl(baseUrl: string, id: string, stem: Stem): string {
  return `${baseUrl}/api/projects/${id}/audio/${stem}`;
}
```

`frontend/lib/api/__mocks__/projects.ts`:
```ts
const actual = jest.requireActual<typeof import("../projects")>("../projects");

export const NotFoundError = actual.NotFoundError;
export const DuplicateProjectError = actual.DuplicateProjectError;
export const ScoreConflictError = actual.ScoreConflictError;
export const audioUrl = jest.fn(actual.audioUrl);
export const createProject = jest.fn();
export const listProjects = jest.fn();
export const getProject = jest.fn();
export const deleteProject = jest.fn();
export const retryProject = jest.fn();
export const getAnalysis = jest.fn();
export const getSavedScore = jest.fn();
export const saveScore = jest.fn();
```

- [ ] **Step 5: Run to verify it passes**

Run: `pnpm test lib/api && pnpm exec tsc --noEmit && pnpm lint`
Expected: all green.

- [ ] **Step 6: Commit (checkpoint)**

```bash
git add frontend/lib/api frontend/components frontend/lib/audio frontend/lib/notation frontend/lib/score
git commit -m "feat(frontend): add projects API client and move shared API types"
```

---

### Task 15: `useScoreEditor`: saved score and dirty tracking

**Files:**
- Modify: `frontend/lib/score/useScoreEditor.ts`
- Test: `frontend/lib/score/__tests__/useScoreEditor.test.ts` (append a new `describe`)

**Interfaces:**
- Produces: `useScoreEditor(events: AnalysisEvent[], initialScore: Score | null = null): ScoreEditor`. `ScoreEditor` gains `isDirty: boolean` (the current score is not the last saved/loaded score) and `markSaved(score: Score): void`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/lib/score/__tests__/useScoreEditor.test.ts` (add `act`/`renderHook` imports from `@testing-library/react` if they are not already imported, and `Score`/`AnalysisEvent` types):
```ts
const SAVE_EVENTS: AnalysisEvent[] = [
  { id: "e1", time: 0, instrument: "kick", confidence: null, provenance: "drumscript", measure: 1, beat: 1, subdivision: 0 },
];

const SAVED_SCORE: Score = {
  measures: [[{ type: "rest", id: "saved-rest", position: { measure: 1, beat: 1, subdivision: 0 }, duration: "w" }]],
};

describe("useScoreEditor saved state", () => {
  it("should start from the initial score when one is provided", () => {
    const { result } = renderHook(() => useScoreEditor(SAVE_EVENTS, SAVED_SCORE));

    expect(result.current.score).toBe(SAVED_SCORE);
  });

  it("should not be dirty before any edit", () => {
    const { result } = renderHook(() => useScoreEditor(SAVE_EVENTS));

    expect(result.current.isDirty).toBe(false);
  });

  it("should become dirty after an edit", () => {
    const { result } = renderHook(() => useScoreEditor(SAVE_EVENTS));

    act(() => result.current.addHit({ measure: 1, beat: 2, subdivision: 0 }, "snare"));

    expect(result.current.isDirty).toBe(true);
  });

  it("should be clean after marking the current score as saved", () => {
    const { result } = renderHook(() => useScoreEditor(SAVE_EVENTS));
    act(() => result.current.addHit({ measure: 1, beat: 2, subdivision: 0 }, "snare"));

    act(() => result.current.markSaved(result.current.score));

    expect(result.current.isDirty).toBe(false);
  });

  it("should stay dirty when an older score is marked saved", () => {
    const { result } = renderHook(() => useScoreEditor(SAVE_EVENTS));
    act(() => result.current.addHit({ measure: 1, beat: 2, subdivision: 0 }, "snare"));
    const snapshot = result.current.score;
    act(() => result.current.addHit({ measure: 1, beat: 3, subdivision: 0 }, "kick"));

    act(() => result.current.markSaved(snapshot));

    expect(result.current.isDirty).toBe(true);
  });

  it("should be clean again after undoing back to the saved score", () => {
    const { result } = renderHook(() => useScoreEditor(SAVE_EVENTS));
    act(() => result.current.addHit({ measure: 1, beat: 2, subdivision: 0 }, "snare"));

    act(() => result.current.undo());

    expect(result.current.isDirty).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `pnpm test lib/score/__tests__/useScoreEditor.test.ts`
Expected: new tests FAIL (`isDirty` undefined, initial score ignored).

- [ ] **Step 3: Implement**

In `frontend/lib/score/useScoreEditor.ts`:

1. Extend the interfaces and action union:
```ts
export interface ScoreEditor {
  score: Score;
  addHit: (position: MusicalPosition, instrument: DrumInstrument) => void;
  deleteHit: (hitId: string) => void;
  moveHit: (hitId: string, newPosition: MusicalPosition) => void;
  changeInstrument: (hitId: string, newInstrument: DrumInstrument) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  // True while `score` differs (by identity) from the last score loaded
  // or passed to markSaved - undoing back to that score makes it clean.
  isDirty: boolean;
  markSaved: (score: Score) => void;
}

interface EditorState {
  score: Score;
  savedScore: Score;
  undoStack: Score[];
  redoStack: Score[];
  trackedEvents: AnalysisEvent[];
}

type EditorAction =
  | { type: "apply-edit"; next: Score }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "reset"; events: AnalysisEvent[]; score: Score }
  | { type: "mark-saved"; score: Score };
```
2. In `editorReducer`, change the `reset` case and add `mark-saved`:
```ts
    case "reset":
      return { score: action.score, savedScore: action.score, undoStack: [], redoStack: [], trackedEvents: action.events };
    case "mark-saved":
      return { ...state, savedScore: action.score };
```
3. Replace `initEditorState` and the hook signature and return value:
```ts
function initEditorState({ events, initialScore }: { events: AnalysisEvent[]; initialScore: Score | null }): EditorState {
  const score = initialScore ?? buildInitialScore(events);
  return { score, savedScore: score, undoStack: [], redoStack: [], trackedEvents: events };
}

export function useScoreEditor(events: AnalysisEvent[], initialScore: Score | null = null): ScoreEditor {
  const [state, dispatch] = useReducer(editorReducer, { events, initialScore }, initEditorState);
  const { score, savedScore, undoStack, redoStack } = state;
```
and add to the returned object:
```ts
    isDirty: score !== savedScore,
    markSaved: (saved) => dispatch({ type: "mark-saved", score: saved }),
```
(The existing `reset` dispatch for new events is unchanged. A genuinely different song rebuilds from its events and counts as clean.)

- [ ] **Step 4: Run to verify they pass**

Run: `pnpm test lib/score && pnpm exec tsc --noEmit`
Expected: all green.

- [ ] **Step 5: Commit (checkpoint)**

```bash
git add frontend/lib/score/useScoreEditor.ts frontend/lib/score/__tests__/useScoreEditor.test.ts
git commit -m "feat(frontend): track saved score and dirty state in useScoreEditor"
```

---

### Task 16: Player: project audio URLs and saving

**Files:**
- Modify: `frontend/components/Player.tsx`, `frontend/components/__tests__/Player.test.tsx`

**Interfaces:**
- Consumes: `audioUrl`, `ScoreConflictError` (`@/lib/api/projects`), `useScoreEditor(events, initialScore)` with `isDirty`/`markSaved`.
- Produces: `Player` props become `{ apiBaseUrl, projectId, events, beats?, createAudioContext?, initialScore?: Score | null, onSave?: (score: Score) => Promise<void>, onReloadRequested?: () => void }` (`jobId` is removed). Save controls render only when `onSave` is given.

- [ ] **Step 1: Update existing tests for the rename**

In `frontend/components/__tests__/Player.test.tsx`, replace every `jobId="job-1"` with `projectId="project-1"`. Replace any `/api/jobs/job-1/` in expectations with `/api/projects/project-1/`.

- [ ] **Step 2: Write the failing save tests**

Append to `frontend/components/__tests__/Player.test.tsx` (import `ScoreConflictError` from `@/lib/api/projects` and `waitFor` from `@testing-library/react`; reuse the file's existing `fakeContextFactory` and audio mocks, which already make the player reach "ready"):
```tsx
describe("Player saving", () => {
  function renderWithSave(onSave = jest.fn().mockResolvedValue(undefined), onReloadRequested = jest.fn()) {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        projectId="project-1"
        events={[]}
        createAudioContext={fakeContextFactory}
        onSave={onSave}
        onReloadRequested={onReloadRequested}
      />,
    );
    return { onSave, onReloadRequested };
  }

  it("should not render save controls without an onSave handler", () => {
    render(<Player apiBaseUrl="http://localhost:8000" projectId="project-1" events={[]} createAudioContext={fakeContextFactory} />);

    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("should load audio from the project's stem URLs", () => {
    renderWithSave();

    expect(loadAudioBuffer).toHaveBeenCalledWith("http://localhost:8000/api/projects/project-1/audio/drums", expect.anything());
    expect(loadAudioBuffer).toHaveBeenCalledWith("http://localhost:8000/api/projects/project-1/audio/accompaniment", expect.anything());
  });

  it("should disable Save until the score has unsaved changes", () => {
    renderWithSave();

    const save = screen.getByRole("button", { name: "Save" });

    expect(save).toBeDisabled();
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  });

  it("should save the edited score and show it as saved", async () => {
    const { onSave } = renderWithSave();
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ measures: expect.any(Array) }));
    expect(await screen.findByText("All changes saved")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("should save with Ctrl+S", async () => {
    const { onSave } = renderWithSave();
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));

    fireEvent.keyDown(window, { key: "s", ctrlKey: true });

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  });

  it("should ignore Ctrl+S when there is nothing to save", () => {
    const { onSave } = renderWithSave();

    fireEvent.keyDown(window, { key: "s", metaKey: true });
    fireEvent.keyDown(window, { key: "x", ctrlKey: true });

    expect(onSave).not.toHaveBeenCalled();
  });

  it("should warn before leaving the page with unsaved changes", () => {
    renderWithSave();
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));
    const event = new Event("beforeunload", { cancelable: true });

    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
  });

  it("should not warn before leaving when everything is saved", () => {
    renderWithSave();
    const event = new Event("beforeunload", { cancelable: true });

    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
  });

  it("should show a save error and keep the changes unsaved", async () => {
    renderWithSave(jest.fn().mockRejectedValue(new Error("Network down")));
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Network down");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reload" })).not.toBeInTheDocument();
  });

  it("should offer a reload when a newer version was saved elsewhere", async () => {
    const { onReloadRequested } = renderWithSave(
      jest.fn().mockRejectedValue(new ScoreConflictError("A newer version was saved elsewhere", 3)),
    );
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    fireEvent.click(await screen.findByRole("button", { name: "Reload" }));

    expect(onReloadRequested).toHaveBeenCalled();
  });

  it("should use a generic message when a non-Error is thrown", async () => {
    renderWithSave(jest.fn().mockRejectedValue("nope"));
    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Save failed.");
  });

  it("should start from the provided initial score", () => {
    const initialScore = {
      measures: [[{ type: "note" as const, id: "n1", position: { measure: 1, beat: 1, subdivision: 0 }, duration: "w", hits: [{ id: "h1", sourceEventId: null, time: null, instrument: "snare" as const, confidence: null, provenance: "manual" }] }]],
    };

    render(<Player apiBaseUrl="http://localhost:8000" projectId="project-1" events={[]} createAudioContext={fakeContextFactory} initialScore={initialScore} />);

    expect(screen.getByRole("option", { name: /snare/i })).toBeInTheDocument();
  });
});
```
(The last test relies on the "Select hit to edit" `<select>` listing the initial score's hits. If `collectHits`' label format doesn't contain the instrument name, assert on whatever label it produces for hit `h1`. Read `collectHits` in `Player.tsx` first.)

- [ ] **Step 3: Run to verify they fail**

Run: `pnpm test components/__tests__/Player.test.tsx`
Expected: new tests FAIL (no Save button; audio loaded from `/api/jobs/...`).

- [ ] **Step 4: Implement**

In `frontend/components/Player.tsx`:

1. Imports: add `import { audioUrl, ScoreConflictError } from "@/lib/api/projects";`.
2. Props:
```ts
interface PlayerProps {
  apiBaseUrl: string;
  projectId: string;
  events: AnalysisEvent[];
  beats?: Beat[];
  createAudioContext?: () => DecodableAudioContext;
  initialScore?: Score | null;
  onSave?: (score: Score) => Promise<void>;
  onReloadRequested?: () => void;
}

type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved" }
  | { status: "error"; message: string; conflict: boolean };

// jsdom cannot reload the page, so tests always pass their own handler.
/* istanbul ignore next */
function reloadPage(): void {
  window.location.reload();
}
```
3. Destructure the new props (`projectId`, `initialScore = null`, `onSave`, `onReloadRequested = reloadPage`). Change `useScoreEditor(events)` to `useScoreEditor(events, initialScore)`. Replace `jobId` with `projectId` everywhere: the two `loadAudioBuffer` URLs become `audioUrl(apiBaseUrl, projectId, "drums")` and `audioUrl(apiBaseUrl, projectId, "accompaniment")`, and update the console message and the effect deps `[apiBaseUrl, projectId]`.
4. Add the save logic after `const hits = useMemo(...)`:
```tsx
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });

  const handleSave = useCallback(async () => {
    if (!onSave || !editor.isDirty || saveState.status === "saving") {
      return;
    }
    const snapshot = editor.score;
    setSaveState({ status: "saving" });
    try {
      await onSave(snapshot);
      editor.markSaved(snapshot);
      setSaveState({ status: "saved" });
    } catch (error) {
      setSaveState({
        status: "error",
        message: error instanceof Error ? error.message : "Save failed.",
        conflict: error instanceof ScoreConflictError,
      });
    }
  }, [editor, onSave, saveState.status]);

  const handleSaveRef = useRef(handleSave);
  useEffect(() => {
    handleSaveRef.current = handleSave;
  }, [handleSave]);

  useEffect(() => {
    if (!onSave) {
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void handleSaveRef.current();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onSave]);

  useEffect(() => {
    if (!editor.isDirty) {
      return;
    }
    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [editor.isDirty]);
```
5. Render the save section immediately above `<DrumScore … />`:
```tsx
      {onSave && (
        <div aria-label="Save score" role="group">
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={!editor.isDirty || saveState.status === "saving"}
          >
            {saveState.status === "saving" ? "Saving..." : "Save"}
          </button>
          {editor.isDirty && <span>Unsaved changes</span>}
          {!editor.isDirty && saveState.status === "saved" && <span>All changes saved</span>}
          {saveState.status === "error" && (
            <p role="alert">
              {saveState.message}
              {saveState.conflict && (
                <button type="button" onClick={onReloadRequested}>
                  Reload
                </button>
              )}
            </p>
          )}
        </div>
      )}
```
(If the Save button's accessible name clashes with an existing button, keep the exact label "Save". The tests query `{ name: "Save" }` exactly.)

- [ ] **Step 5: Run to verify they pass**

Run: `pnpm test components && pnpm exec tsc --noEmit && pnpm lint`
Expected: all green. Keep `JobForm.tsx` compiling in the meantime: change its `<Player jobId={job.id} …>` to `<Player projectId={job.id} …>` (it is deleted in Task 18).

- [ ] **Step 6: Commit (checkpoint)**

```bash
git add frontend/components/Player.tsx frontend/components/__tests__/Player.test.tsx frontend/components/JobForm.tsx
git commit -m "feat(frontend): add explicit score saving with dirty tracking to Player"
```

---

### Task 17: `ProjectView` and the `/projects/[id]` page

**Files:**
- Create: `frontend/components/ProjectView.tsx`, `frontend/components/__tests__/ProjectView.test.tsx`, `frontend/app/projects/[id]/page.tsx`, `frontend/app/projects/[id]/__tests__/page.test.tsx`

**Interfaces:**
- Consumes: the `projects.ts` client (mocked via `__mocks__`), `fromJSON`/`toJSON` from `@/lib/score/serialization`, `Player`.
- Produces: `<ProjectView apiBaseUrl projectId />`. It polls `getProject` right away and then every 2 s until the status is `completed`/`failed`. It tolerates 2 consecutive poll errors (3rd gives up) and stops on 404. On `completed` it loads `getAnalysis` + `getSavedScore` in parallel and renders `Player` with `initialScore` (saved score or `null`) and `onSave`, which calls `saveScore(..., toJSON(score), currentVersion)` and advances the version. On `failed` it shows the error and a "Retry processing" button.

Read `frontend/node_modules/next/dist/docs/01-app/01-getting-started/03-layouts-and-pages.md` ("Dynamic Segments") before writing the page. In this Next version `params` is a `Promise`.

- [ ] **Step 1: Write the failing tests**

`frontend/components/__tests__/ProjectView.test.tsx`:
```tsx
import { act, fireEvent, render, screen } from "@testing-library/react";

import { getAnalysis, getProject, getSavedScore, NotFoundError, retryProject, saveScore } from "@/lib/api/projects";
import ProjectView from "../ProjectView";

jest.mock("@/lib/api/projects");
jest.mock("@/components/Player", () => {
  return function MockPlayer({
    projectId,
    events,
    initialScore,
    onSave,
  }: {
    projectId: string;
    events: unknown[];
    initialScore: unknown;
    onSave: (score: unknown) => Promise<void>;
  }) {
    return (
      <div data-testid="player" data-project-id={projectId} data-events={events.length} data-initial={JSON.stringify(initialScore)}>
        <button type="button" onClick={() => void onSave({ measures: [["edited"]] })}>
          mock-save
        </button>
      </div>
    );
  };
});

const BASE = "http://localhost:8000";
const ANALYSIS = { tempo_bpm: 120, events: [{ id: "e1" }], beats: [] };

function project(status: string, error: string | null = null) {
  return { id: "p1", title: "My Song", source_url: "u", created_at: "", updated_at: "", latest_job: { id: "j1", status, attempts: 1, max_attempts: 3, error, created_at: "", finished_at: null } };
}

async function flush() {
  await act(async () => {});
}

async function tick() {
  await act(async () => {
    jest.advanceTimersByTime(2000);
  });
}

describe("ProjectView", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it("should show progress while processing and the player once completed", async () => {
    (getProject as jest.Mock)
      .mockResolvedValueOnce(project("separating_stems"))
      .mockResolvedValueOnce(project("completed"));
    (getAnalysis as jest.Mock).mockResolvedValue(ANALYSIS);
    (getSavedScore as jest.Mock).mockResolvedValue(null);

    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(screen.getByRole("heading", { name: "My Song" })).toBeInTheDocument();
    expect(screen.getByText("Separating drum stems...")).toBeInTheDocument();

    await tick();

    const player = await screen.findByTestId("player");
    expect(player).toHaveAttribute("data-events", "1");
    expect(player).toHaveAttribute("data-initial", "null");
  });

  it("should load the saved score instead of rebuilding from the analysis", async () => {
    (getProject as jest.Mock).mockResolvedValue(project("completed"));
    (getAnalysis as jest.Mock).mockResolvedValue(ANALYSIS);
    (getSavedScore as jest.Mock).mockResolvedValue({ version: 4, score: { measures: [["saved"]] } });

    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(await screen.findByTestId("player")).toHaveAttribute("data-initial", JSON.stringify({ measures: [["saved"]] }));
  });

  it("should save with the loaded version and then with the returned one", async () => {
    (getProject as jest.Mock).mockResolvedValue(project("completed"));
    (getAnalysis as jest.Mock).mockResolvedValue(ANALYSIS);
    (getSavedScore as jest.Mock).mockResolvedValue({ version: 4, score: { measures: [] } });
    (saveScore as jest.Mock).mockResolvedValueOnce(5).mockResolvedValueOnce(6);
    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();
    const save = await screen.findByRole("button", { name: "mock-save" });

    fireEvent.click(save);
    await flush();
    fireEvent.click(save);
    await flush();

    expect(saveScore).toHaveBeenNthCalledWith(1, BASE, "p1", { measures: [["edited"]] }, 4);
    expect(saveScore).toHaveBeenNthCalledWith(2, BASE, "p1", { measures: [["edited"]] }, 5);
  });

  it("should show the failure and requeue on retry", async () => {
    (getProject as jest.Mock)
      .mockResolvedValueOnce(project("failed", "video unavailable"))
      .mockResolvedValueOnce(project("queued"));
    (retryProject as jest.Mock).mockResolvedValue({ id: "j1", status: "queued" });
    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent("video unavailable");

    fireEvent.click(screen.getByRole("button", { name: "Retry processing" }));
    await flush();

    expect(retryProject).toHaveBeenCalledWith(BASE, "p1");
    expect(screen.getByText("Queued, waiting for a worker...")).toBeInTheDocument();
  });

  it("should show an error when the retry request fails", async () => {
    (getProject as jest.Mock).mockResolvedValue(project("failed", "boom"));
    (retryProject as jest.Mock).mockRejectedValue(new Error("Only a failed job can be retried"));
    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    fireEvent.click(screen.getByRole("button", { name: "Retry processing" }));
    await flush();

    expect(screen.getByText("Only a failed job can be retried")).toBeInTheDocument();
  });

  it("should show not found for a deleted or unknown project", async () => {
    (getProject as jest.Mock).mockRejectedValue(new NotFoundError("Project not found"));

    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent("Project not found");
  });

  it("should retry transient poll errors and give up after three in a row", async () => {
    (getProject as jest.Mock).mockRejectedValue(new Error("offline"));

    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(screen.getByText("Lost connection, retrying...")).toBeInTheDocument();

    await tick();
    await tick();

    expect(screen.getByRole("alert")).toHaveTextContent("Lost connection to the server");
    expect(getProject).toHaveBeenCalledTimes(3);
  });

  it("should show a load error when the analysis cannot be fetched", async () => {
    (getProject as jest.Mock).mockResolvedValue(project("completed"));
    (getAnalysis as jest.Mock).mockRejectedValue(new Error("Analysis not available yet"));
    (getSavedScore as jest.Mock).mockResolvedValue(null);

    render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent("Analysis not available yet");
  });

  it("should stop polling after unmount", async () => {
    (getProject as jest.Mock).mockResolvedValue(project("queued"));
    const { unmount } = render(<ProjectView apiBaseUrl={BASE} projectId="p1" />);
    await flush();

    unmount();
    await tick();

    expect(getProject).toHaveBeenCalledTimes(1);
  });
});
```

`frontend/app/projects/[id]/__tests__/page.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";

import ProjectPage from "../page";

jest.mock("@/components/ProjectView", () => {
  return function MockProjectView({ apiBaseUrl, projectId }: { apiBaseUrl: string; projectId: string }) {
    return <div data-testid="project-view" data-api-base-url={apiBaseUrl} data-project-id={projectId} />;
  };
});

describe("ProjectPage", () => {
  it("should render the project view for the route id", async () => {
    render(await ProjectPage({ params: Promise.resolve({ id: "p1" }) }));

    expect(screen.getByTestId("project-view")).toHaveAttribute("data-project-id", "p1");
    expect(screen.getByTestId("project-view")).toHaveAttribute("data-api-base-url", "http://localhost:8000");
  });

  it("should link back to the project library", async () => {
    render(await ProjectPage({ params: Promise.resolve({ id: "p1" }) }));

    expect(screen.getByRole("link", { name: /all projects/i })).toHaveAttribute("href", "/");
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `pnpm test components/__tests__/ProjectView.test.tsx "app/projects"`
Expected: FAIL, modules not found.

- [ ] **Step 3: Implement**

`frontend/components/ProjectView.tsx`:
```tsx
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import Player from "@/components/Player";
import {
  getAnalysis,
  getProject,
  getSavedScore,
  NotFoundError,
  retryProject,
  saveScore,
  type JobStatus,
  type Project,
} from "@/lib/api/projects";
import type { Analysis } from "@/lib/api/types";
import { fromJSON, toJSON } from "@/lib/score/serialization";
import type { Score } from "@/lib/score/types";

interface ProjectViewProps {
  apiBaseUrl: string;
  projectId: string;
}

const POLL_INTERVAL_MS = 2000;
const MAX_CONSECUTIVE_POLL_FAILURES = 3;

const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Queued, waiting for a worker...",
  downloading: "Downloading audio...",
  downloaded: "Audio downloaded, starting stem separation...",
  separating_stems: "Separating drum stems...",
  stems_separated: "Stems separated, starting transcription...",
  transcribing: "Transcribing drum hits...",
  transcribed: "Drum hits transcribed, starting tempo mapping...",
  mapping_tempo: "Mapping tempo and beats...",
  completed: "Done.",
  failed: "Failed.",
};

interface LoadedProject {
  analysis: Analysis;
  initialScore: Score | null;
}

export default function ProjectView({ apiBaseUrl, projectId }: ProjectViewProps) {
  const [project, setProject] = useState<Project | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [connectionIssue, setConnectionIssue] = useState(false);
  const [pollingGaveUp, setPollingGaveUp] = useState(false);
  const [loaded, setLoaded] = useState<LoadedProject | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pollGeneration, setPollGeneration] = useState(0);
  const versionRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let failures = 0;
    let handle: ReturnType<typeof setTimeout> | null = null;

    async function loadResult() {
      try {
        const [analysis, saved] = await Promise.all([
          getAnalysis(apiBaseUrl, projectId),
          getSavedScore(apiBaseUrl, projectId),
        ]);
        if (cancelled) {
          return;
        }
        versionRef.current = saved?.version ?? null;
        setLoaded({ analysis, initialScore: saved ? fromJSON(saved.score) : null });
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load project.");
        }
      }
    }

    async function poll() {
      try {
        const current = await getProject(apiBaseUrl, projectId);
        if (cancelled) {
          return;
        }
        failures = 0;
        setConnectionIssue(false);
        setProject(current);
        const status = current.latest_job?.status;
        if (status === "completed") {
          await loadResult();
          return;
        }
        if (status === "failed") {
          return;
        }
      } catch (err) {
        if (cancelled) {
          return;
        }
        if (err instanceof NotFoundError) {
          setNotFound(true);
          return;
        }
        failures += 1;
        console.error(`[ProjectView] poll ${failures}/${MAX_CONSECUTIVE_POLL_FAILURES} failed for project ${projectId}:`, err);
        if (failures >= MAX_CONSECUTIVE_POLL_FAILURES) {
          setConnectionIssue(false);
          setPollingGaveUp(true);
          return;
        }
        setConnectionIssue(true);
      }
      handle = setTimeout(poll, POLL_INTERVAL_MS);
    }

    void poll();

    return () => {
      cancelled = true;
      if (handle) {
        clearTimeout(handle);
      }
    };
  }, [apiBaseUrl, projectId, pollGeneration]);

  const handleSave = useCallback(
    async (score: Score) => {
      versionRef.current = await saveScore(apiBaseUrl, projectId, toJSON(score), versionRef.current);
    },
    [apiBaseUrl, projectId],
  );

  async function handleRetry() {
    try {
      await retryProject(apiBaseUrl, projectId);
      setError(null);
      setPollGeneration((generation) => generation + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retry failed.");
    }
  }

  if (notFound) {
    return <p role="alert">Project not found. It may have been deleted.</p>;
  }

  const job = project?.latest_job ?? null;

  return (
    <div style={{ width: "100%" }}>
      {project ? <h2>{project.title}</h2> : <p>Loading project...</p>}
      {connectionIssue && <p>Lost connection, retrying...</p>}
      {pollingGaveUp && (
        <p role="alert">Lost connection to the server. Status may be out of date — reload the page to check again.</p>
      )}
      {job?.status === "failed" && (
        <div>
          <p role="alert">{job.error ?? STATUS_LABELS.failed}</p>
          <button type="button" onClick={() => void handleRetry()}>
            Retry processing
          </button>
        </div>
      )}
      {job && job.status !== "failed" && !loaded && <p>{STATUS_LABELS[job.status]}</p>}
      {error && <p role="alert">{error}</p>}
      {loaded && (
        <Player
          apiBaseUrl={apiBaseUrl}
          projectId={projectId}
          events={loaded.analysis.events}
          beats={loaded.analysis.beats}
          initialScore={loaded.initialScore}
          onSave={handleSave}
        />
      )}
    </div>
  );
}
```
(`fromJSON` takes `unknown` and returns `Score`, matching `SavedScore.score: unknown`. `toJSON(score)` returns `unknown`, matching `saveScore`'s `score: unknown`.)

`frontend/app/projects/[id]/page.tsx`:
```tsx
import Link from "next/link";

import ProjectView from "@/components/ProjectView";
import styles from "../../page.module.css";

export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <Link href="/">← All projects</Link>
        <ProjectView apiBaseUrl={apiBaseUrl} projectId={id} />
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `pnpm test components/__tests__/ProjectView.test.tsx "app/projects" && pnpm exec tsc --noEmit && pnpm lint`
Expected: all green. If the retry test shows the old "failed" alert (state ordering), make sure `handleRetry` bumps `pollGeneration` so the effect re-polls. The second mocked `getProject` returns `queued`.

- [ ] **Step 5: Commit (checkpoint)**

```bash
git add frontend/components/ProjectView.tsx frontend/components/__tests__/ProjectView.test.tsx "frontend/app/projects"
git commit -m "feat(frontend): add project page with processing progress, saved-score load and save"
```

---

### Task 18: Home page: submit form with duplicate dialog, project library, remove legacy job UI

**Files:**
- Create: `frontend/components/NewProjectForm.tsx`, `frontend/components/ProjectLibrary.tsx`, `frontend/__mocks__/next/navigation.ts`, `frontend/components/__tests__/NewProjectForm.test.tsx`, `frontend/components/__tests__/ProjectLibrary.test.tsx`
- Modify: `frontend/app/page.tsx`, `frontend/app/__tests__/page.test.tsx`, `frontend/components/__tests__/EndToEndFlow.test.tsx` (rewrite)
- Delete: `frontend/components/JobForm.tsx`, `frontend/components/__tests__/JobForm.test.tsx`, `frontend/lib/api/jobs.ts`, `frontend/lib/api/__tests__/jobs.test.ts`

**Interfaces:**
- Produces: `<NewProjectForm apiBaseUrl />`, which navigates with `router.push("/projects/<id>")` after creation and shows a dialog on duplicates. `<ProjectLibrary apiBaseUrl />` lists projects with links, status text and delete. Mock `frontend/__mocks__/next/navigation.ts` exports `mockPush` and `useRouter`.

- [ ] **Step 1: Add the navigation mock**

`frontend/__mocks__/next/navigation.ts`:
```ts
export const mockPush = jest.fn();

export const useRouter = jest.fn(() => ({
  push: mockPush,
  replace: jest.fn(),
  back: jest.fn(),
  forward: jest.fn(),
  refresh: jest.fn(),
  prefetch: jest.fn(),
}));
```

- [ ] **Step 2: Write the failing component tests**

`frontend/components/__tests__/NewProjectForm.test.tsx`:
```tsx
import { act, fireEvent, render, screen } from "@testing-library/react";
import * as navigation from "next/navigation";

import { createProject, DuplicateProjectError } from "@/lib/api/projects";
import NewProjectForm from "../NewProjectForm";

jest.mock("next/navigation");
jest.mock("@/lib/api/projects");

const mockPush = (navigation as unknown as { mockPush: jest.Mock }).mockPush;
const BASE = "http://localhost:8000";

async function submit(url: string) {
  fireEvent.change(screen.getByLabelText(/youtube url/i), { target: { value: url } });
  fireEvent.click(screen.getByRole("button", { name: /generate drum score/i }));
  await act(async () => {});
}

describe("NewProjectForm", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("should create a project and open it", async () => {
    (createProject as jest.Mock).mockResolvedValue({ project: { id: "p1" }, job: { id: "j1" } });
    render(<NewProjectForm apiBaseUrl={BASE} />);

    await submit("  https://youtu.be/x  ");

    expect(createProject).toHaveBeenCalledWith(BASE, "https://youtu.be/x", { force: false });
    expect(mockPush).toHaveBeenCalledWith("/projects/p1");
  });

  it("should ask for a URL when the field is empty", async () => {
    render(<NewProjectForm apiBaseUrl={BASE} />);

    await submit("   ");

    expect(screen.getByRole("alert")).toHaveTextContent("Please enter a YouTube URL.");
    expect(createProject).not.toHaveBeenCalled();
  });

  it("should show the backend error", async () => {
    (createProject as jest.Mock).mockRejectedValue(new Error("'x' is not a supported YouTube URL"));
    render(<NewProjectForm apiBaseUrl={BASE} />);

    await submit("x");

    expect(screen.getByRole("alert")).toHaveTextContent("'x' is not a supported YouTube URL");
  });

  it("should show a generic error for non-Error failures", async () => {
    (createProject as jest.Mock).mockRejectedValue("nope");
    render(<NewProjectForm apiBaseUrl={BASE} />);

    await submit("https://youtu.be/x");

    expect(screen.getByRole("alert")).toHaveTextContent("Failed to create project.");
  });

  it("should offer to open the existing project for a duplicate song", async () => {
    (createProject as jest.Mock).mockRejectedValue(new DuplicateProjectError("exists", "p-old"));
    render(<NewProjectForm apiBaseUrl={BASE} />);
    await submit("https://youtu.be/x");

    fireEvent.click(screen.getByRole("button", { name: "Open existing" }));

    expect(screen.getByRole("dialog", { name: "Song already processed" })).toBeInTheDocument();
    expect(mockPush).toHaveBeenCalledWith("/projects/p-old");
  });

  it("should process a duplicate anyway when asked", async () => {
    (createProject as jest.Mock)
      .mockRejectedValueOnce(new DuplicateProjectError("exists", "p-old"))
      .mockResolvedValueOnce({ project: { id: "p-new" }, job: { id: "j2" } });
    render(<NewProjectForm apiBaseUrl={BASE} />);
    await submit("https://youtu.be/x");

    fireEvent.click(screen.getByRole("button", { name: "Process anyway" }));
    await act(async () => {});

    expect(createProject).toHaveBeenLastCalledWith(BASE, "https://youtu.be/x", { force: true });
    expect(mockPush).toHaveBeenCalledWith("/projects/p-new");
  });
});
```

`frontend/components/__tests__/ProjectLibrary.test.tsx`:
```tsx
import { act, fireEvent, render, screen } from "@testing-library/react";

import { deleteProject, listProjects } from "@/lib/api/projects";
import ProjectLibrary from "../ProjectLibrary";

jest.mock("@/lib/api/projects");

const BASE = "http://localhost:8000";

function item(id: string, title: string, status: string | null, hasEdits = false) {
  return { id, title, source_url: "u", updated_at: "", latest_job_status: status, has_edits: hasEdits };
}

describe("ProjectLibrary", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(window, "confirm").mockReturnValue(true);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("should list projects with links, status and edit marker", async () => {
    (listProjects as jest.Mock).mockResolvedValue([
      item("p1", "Song A", "completed", true),
      item("p2", "Song B", "transcribing"),
      item("p3", "Song C", "failed"),
      item("p4", "Song D", null),
    ]);

    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    expect(screen.getByRole("link", { name: "Song A" })).toHaveAttribute("href", "/projects/p1");
    expect(screen.getByText(/Ready/)).toBeInTheDocument();
    expect(screen.getByText(/edited/)).toBeInTheDocument();
    expect(screen.getByText(/Processing/)).toBeInTheDocument();
    expect(screen.getByText(/Failed/)).toBeInTheDocument();
  });

  it("should show a loading state and then an empty state", async () => {
    (listProjects as jest.Mock).mockResolvedValue([]);

    render(<ProjectLibrary apiBaseUrl={BASE} />);

    expect(screen.getByText("Loading projects...")).toBeInTheDocument();
    await act(async () => {});
    expect(screen.getByText(/No projects yet/)).toBeInTheDocument();
  });

  it("should show an error when the list cannot be loaded", async () => {
    (listProjects as jest.Mock).mockRejectedValue(new Error("offline"));

    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    expect(screen.getByRole("alert")).toHaveTextContent("offline");
  });

  it("should delete a project after confirmation", async () => {
    (listProjects as jest.Mock).mockResolvedValue([item("p1", "Song A", "completed")]);
    (deleteProject as jest.Mock).mockResolvedValue(undefined);
    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    fireEvent.click(screen.getByRole("button", { name: "Delete Song A" }));
    await act(async () => {});

    expect(deleteProject).toHaveBeenCalledWith(BASE, "p1");
    expect(screen.queryByRole("link", { name: "Song A" })).not.toBeInTheDocument();
  });

  it("should keep the project when deletion is not confirmed", async () => {
    (window.confirm as jest.Mock).mockReturnValue(false);
    (listProjects as jest.Mock).mockResolvedValue([item("p1", "Song A", "completed")]);
    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    fireEvent.click(screen.getByRole("button", { name: "Delete Song A" }));

    expect(deleteProject).not.toHaveBeenCalled();
  });

  it("should show an error when deletion fails", async () => {
    (listProjects as jest.Mock).mockResolvedValue([item("p1", "Song A", "completed")]);
    (deleteProject as jest.Mock).mockRejectedValue(new Error("Project not found"));
    render(<ProjectLibrary apiBaseUrl={BASE} />);
    await act(async () => {});

    fireEvent.click(screen.getByRole("button", { name: "Delete Song A" }));
    await act(async () => {});

    expect(screen.getByRole("alert")).toHaveTextContent("Project not found");
  });
});
```

Replace `frontend/app/__tests__/page.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";

import Home from "../page";

jest.mock("@/components/NewProjectForm", () => {
  return function MockNewProjectForm({ apiBaseUrl }: { apiBaseUrl: string }) {
    return <div data-testid="new-project-form" data-api-base-url={apiBaseUrl} />;
  };
});
jest.mock("@/components/ProjectLibrary", () => {
  return function MockProjectLibrary({ apiBaseUrl }: { apiBaseUrl: string }) {
    return <div data-testid="project-library" data-api-base-url={apiBaseUrl} />;
  };
});

describe("Home", () => {
  it("should render the page heading and description", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { name: /drumscore/i })).toBeInTheDocument();
    expect(screen.getByText(/generate playable drum notation/i)).toBeInTheDocument();
  });

  it("should render the submit form and the library with the configured API base URL", () => {
    render(<Home />);

    expect(screen.getByTestId("new-project-form")).toHaveAttribute("data-api-base-url", "http://localhost:8000");
    expect(screen.getByTestId("project-library")).toHaveAttribute("data-api-base-url", "http://localhost:8000");
  });
});
```

- [ ] **Step 3: Run to verify they fail**

Run: `pnpm test components/__tests__/NewProjectForm.test.tsx components/__tests__/ProjectLibrary.test.tsx app/__tests__/page.test.tsx`
Expected: FAIL, modules not found.

- [ ] **Step 4: Implement**

`frontend/components/NewProjectForm.tsx`:
```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createProject, DuplicateProjectError } from "@/lib/api/projects";

interface NewProjectFormProps {
  apiBaseUrl: string;
}

interface Duplicate {
  url: string;
  existingProjectId: string;
}

export default function NewProjectForm({ apiBaseUrl }: NewProjectFormProps) {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<Duplicate | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(targetUrl: string, force: boolean) {
    setSubmitting(true);
    try {
      const created = await createProject(apiBaseUrl, targetUrl, { force });
      router.push(`/projects/${created.project.id}`);
    } catch (err) {
      if (err instanceof DuplicateProjectError) {
        setDuplicate({ url: targetUrl, existingProjectId: err.existingProjectId });
        setError(null);
      } else {
        setError(err instanceof Error ? err.message : "Failed to create project.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = url.trim();
    setDuplicate(null);
    if (!trimmed) {
      setError("Please enter a YouTube URL.");
      return;
    }
    void submit(trimmed, false);
  }

  return (
    <div style={{ width: "100%" }}>
      <form onSubmit={handleSubmit}>
        <label htmlFor="youtube-url">YouTube URL</label>
        <input id="youtube-url" type="text" value={url} onChange={(event) => setUrl(event.target.value)} />
        <button type="submit" disabled={submitting}>
          Generate drum score
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
      {duplicate && (
        <div role="dialog" aria-label="Song already processed">
          <p>This song already has a project.</p>
          <button type="button" onClick={() => router.push(`/projects/${duplicate.existingProjectId}`)}>
            Open existing
          </button>
          <button type="button" onClick={() => void submit(duplicate.url, true)}>
            Process anyway
          </button>
        </div>
      )}
    </div>
  );
}
```

`frontend/components/ProjectLibrary.tsx`:
```tsx
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { deleteProject, listProjects, type JobStatus, type ProjectListItem } from "@/lib/api/projects";

interface ProjectLibraryProps {
  apiBaseUrl: string;
}

function statusText(status: JobStatus | null): string {
  if (status === "completed") {
    return "Ready";
  }
  if (status === "failed") {
    return "Failed";
  }
  return status ? "Processing" : "";
}

export default function ProjectLibrary({ apiBaseUrl }: ProjectLibraryProps) {
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listProjects(apiBaseUrl)
      .then((items) => {
        if (!cancelled) {
          setProjects(items);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load projects.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  async function handleDelete(project: ProjectListItem) {
    if (!window.confirm(`Delete "${project.title}"? This cannot be undone.`)) {
      return;
    }
    try {
      await deleteProject(apiBaseUrl, project.id);
      setProjects((current) => (current ?? []).filter((p) => p.id !== project.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete project.");
    }
  }

  return (
    <section aria-labelledby="library-heading" style={{ width: "100%" }}>
      <h2 id="library-heading">My projects</h2>
      {error && <p role="alert">{error}</p>}
      {projects === null && !error && <p>Loading projects...</p>}
      {projects?.length === 0 && <p>No projects yet. Submit a YouTube URL to start one.</p>}
      {projects && projects.length > 0 && (
        <ul>
          {projects.map((project) => (
            <li key={project.id}>
              <Link href={`/projects/${project.id}`}>{project.title}</Link>{" "}
              <span>
                {statusText(project.latest_job_status)}
                {project.has_edits && " · edited"}
              </span>{" "}
              <button type="button" aria-label={`Delete ${project.title}`} onClick={() => void handleDelete(project)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```
(The error-message fallbacks for non-`Error` rejections are covered by adding one `mockRejectedValue("x")` case per component if coverage reports them. Add those tests rather than excluding the lines.)

`frontend/app/page.tsx`:
```tsx
import NewProjectForm from "@/components/NewProjectForm";
import ProjectLibrary from "@/components/ProjectLibrary";
import styles from "./page.module.css";

export default function Home() {
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1>Drumscore</h1>
        <p>Generate playable drum notation from a song.</p>
        <NewProjectForm apiBaseUrl={apiBaseUrl} />
        <ProjectLibrary apiBaseUrl={apiBaseUrl} />
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Rewrite the end-to-end flow test and delete the legacy UI**

Rewrite `frontend/components/__tests__/EndToEndFlow.test.tsx`. Keep its `FakeGainNode`, `FakeBufferSource` and `FakeAudioContext` classes and its `beforeEach`/`afterEach`, but mock `@/lib/api/projects` instead of `@/lib/api/jobs` and drive `ProjectView`:
```tsx
import { act, fireEvent, render, screen } from "@testing-library/react";

import { getAnalysis, getProject, getSavedScore, saveScore } from "@/lib/api/projects";
import ProjectView from "../ProjectView";

jest.mock("@/lib/api/projects");

// FakeGainNode / FakeBufferSource / FakeAudioContext: unchanged from the previous version of this file.

function project(status: string) {
  return { id: "project-1", title: "Song", source_url: "u", created_at: "", updated_at: "", latest_job: { id: "j1", status, attempts: 1, max_attempts: 3, error: null, created_at: "", finished_at: null } };
}

describe("End-to-end flow", () => {
  // beforeEach / afterEach: unchanged (fake AudioContext, fetch returning an ArrayBuffer, fake timers).

  it("should go from a processing project to a playable score whose edits can be saved", async () => {
    (getProject as jest.Mock)
      .mockResolvedValueOnce(project("transcribing"))
      .mockResolvedValueOnce(project("completed"));
    (getAnalysis as jest.Mock).mockResolvedValue({
      tempo_bpm: 120,
      events: [{ id: "e1", time: 0, instrument: "kick", confidence: null, provenance: "drumscript", measure: 1, beat: 1, subdivision: 0 }],
      beats: [],
    });
    (getSavedScore as jest.Mock).mockResolvedValue(null);
    (saveScore as jest.Mock).mockResolvedValue(1);

    render(<ProjectView apiBaseUrl="http://localhost:8000" projectId="project-1" />);
    await act(async () => {});
    expect(screen.getByText("Transcribing drum hits...")).toBeInTheDocument();
    await act(async () => {
      jest.advanceTimersByTime(2000);
    });
    jest.useRealTimers();

    const playButton = await screen.findByRole("button", { name: /play/i });
    const scoreContainer = screen.getByTestId("drum-score");
    expect(scoreContainer.querySelectorAll(".vf-stavenote").length).toBeGreaterThan(0);
    fireEvent.click(playButton);
    expect(await screen.findByRole("button", { name: /pause/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add hit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("All changes saved")).toBeInTheDocument();
    expect(saveScore).toHaveBeenCalledWith("http://localhost:8000", "project-1", expect.objectContaining({ measures: expect.any(Array) }), null);
  });
});
```
The two `// … unchanged` lines stand for code you copy over from the existing file. Do not leave those comments in the final test (the testing rules forbid comments in tests).

Delete the legacy job UI:
```bash
rm frontend/components/JobForm.tsx frontend/components/__tests__/JobForm.test.tsx frontend/lib/api/jobs.ts frontend/lib/api/__tests__/jobs.test.ts
```
Run: `grep -rn "lib/api/jobs\|JobForm" frontend/app frontend/components frontend/lib`
Expected: no output.

- [ ] **Step 6: Run the full frontend suite**

Run: `pnpm test --coverage && pnpm lint && pnpm exec tsc --noEmit && pnpm build`
Expected: all green. New files show 100% coverage apart from the documented `istanbul ignore` in `Player.tsx`.

- [ ] **Step 7: Commit (checkpoint)**

```bash
git add -A frontend
git commit -m "feat(frontend): add project library and duplicate-aware submit form, remove job UI"
```

---

### Task 19: Documentation, full verification and hand-off

**Files:**
- Create: `docs/PERSISTENCE.md`
- Modify: `docs/ARCHITECTURE_V1.md` ("Jobs and persistence" section), `TECHNICAL_DEBT.md`, `README.md` (run instructions)

- [ ] **Step 1: Write `docs/PERSISTENCE.md`**

Write it with these sections and facts (all taken from the spec and this plan):
1. **Overview**: Postgres holds projects, jobs (also the queue), artifacts, analyses, score_versions and stage_cache. Files live under `STORAGE_ROOT` and are referenced by relative keys `projects/<project_id>/<job_id>/<file>`. Diagram: API → Postgres ← workers → storage.
2. **Schema**: one table per section, with columns copied from `backend/app/persistence/tables.py`, plus a note that `tables.py` is the source of truth and `tests/test_migrations.py` enforces migration parity.
3. **Job state machine**: `queued → downloading → downloaded → separating_stems → stems_separated → transcribing → transcribed → mapping_tempo → completed`, and any state → `failed`. A cached stage jumps straight to its "done" status. Retry resets a failed job to `queued` with attempts 0.
4. **Claim and lease semantics**: the claim SQL; lease 300 s with a 60 s heartbeat; a lost lease leads to `JobAbandoned`/`LeaseLostError`; SIGTERM makes a worker stop after the current stage and release its lease; `attempts > max_attempts` at claim time means fail.
5. **Failure policy**: which errors are permanent (list `PERMANENT_ERRORS`); backoff `30·2^(n-1)` s; `MAX_ATTEMPTS=3`.
6. **Idempotency and cache**: stage output is written to tmp, fsync'd and renamed, and only then is the row committed in the same transaction as the cache entry and status. A cache entry is keyed by `(source_key, stage, PIPELINE_VERSION)`; bump `PIPELINE_VERSION` when engines change. A duplicate project links the same storage keys.
7. **Retention**: the pruner runs hourly under an advisory lock. Source audio is removed after completion; failed jobs' files after `FAILED_JOB_RETENTION_DAYS`; soft-deleted projects are purged; temp files after 24 h; a warning is logged above `STORAGE_WARN_BYTES`. A key is deleted only when every row referencing it is disposable. There is no startup temp sweep, because a live worker's staging directory can be older than one lease.
8. **Migrations workflow**: `cd backend && uv run alembic revision -m "<change>"`, then write upgrade/downgrade, then `uv run pytest tests/test_migrations.py`. Dev applies migrations on API startup; production (Slice C) runs `uv run alembic upgrade head` as an explicit step with `RUN_MIGRATIONS_ON_STARTUP=false`.
9. **Configuration**: the env var table from `app/config.py` with defaults.
10. **Score versions**: every save appends a version; optimistic concurrency via `base_version`; the backend validates only `measures` is an array.

- [ ] **Step 2: Update the architecture doc, debt log and README**

In `docs/ARCHITECTURE_V1.md`, replace the "Jobs and persistence" section body with:
```markdown
## Jobs and persistence
Projects, jobs, artifacts, analyses, score versions and the stage cache are persisted in Postgres behind the `Store` protocol (`backend/app/persistence`). The API only enqueues. Separate `python -m app.worker` processes claim jobs with `FOR UPDATE SKIP LOCKED` leases, run each pipeline stage, and commit its output (written atomically to `ArtifactStorage`) before starting the next, so any crash resumes at the first stage without output. Retries are idempotent; stage outputs are reused across projects of the same source via a `PIPELINE_VERSION`-keyed cache. A pruner applies retention rules. Details: `docs/PERSISTENCE.md`.

Storage distinguishes source audio, stems, raw transcription diagnostics, analysis/score data and user edits.
```

In `TECHNICAL_DEBT.md`:
- Append "**Superseded (Epic 6 Slice A):** replaced by the pruner's retention rules, see docs/PERSISTENCE.md" under "Disk cleanup for job files".
- Append "**Superseded (Epic 6 Slice A):** worker process count (`WORKER_CONCURRENCY`) bounds concurrent pipelines" under "No concurrency limit on heavy pipeline jobs".
- Add new entries, each with the repo's usual Found in / Problem / Fix would involve structure:
  1. *Orphaned stage files*: a crash between `storage.put` and `commit_stage` leaves a file at the job's key with no row. A rerun of the same job overwrites it, but a job that is never retried leaks it until someone cleans storage manually.
  2. *Unbounded score history*: `score_versions` keeps every save and has no cap or compaction.
  3. *No authentication*: v1 relies on deployment-level access control (private network / reverse-proxy auth). Anyone who can reach the API can delete projects.
  4. *Correlation IDs are stored but not yet propagated to logs*: this is Slice B (#84).

In `README.md` add a "Running locally" section:
````markdown
## Running locally
```bash
docker compose -f docker-compose.dev.yml up -d          # Postgres 18
cd backend && cp .env.example .env
uv run uvicorn app.main:app --reload                     # API (applies migrations on startup)
uv run python -m app.worker                              # workers (separate terminal)
cd ../frontend && pnpm dev                               # http://localhost:3000
```
Tests: `cd backend && uv run pytest` (needs Docker; `-m "not integration"` skips Postgres tests) and `cd frontend && pnpm test`.
````

- [ ] **Step 3: Full automated verification**

Run (Docker running):
```bash
cd backend && uv run pytest --cov=app --cov-report=term-missing
cd ../frontend && pnpm test --coverage && pnpm lint && pnpm exec tsc --noEmit && pnpm build
```
Expected: every suite green. Record the pass counts for the PR description.

- [ ] **Step 4: Manual restart-survival check (the Epic exit gate for this slice)**

1. Start Postgres, the API, one worker (`WORKER_CONCURRENCY=1`) and the frontend as in the README.
2. Submit a real YouTube song. On the project page, wait until the status reads "Separating drum stems...".
3. Kill the worker process (Ctrl+C for a graceful stop, then repeat with a hard kill via Task Manager / `kill -9`). Restart it.
   - Graceful stop: the job resumes as soon as the worker restarts.
   - Hard kill: the job resumes after the lease expires (≤5 min; set `LEASE_SECONDS=30` in `.env` to make the check fast).
   - In both cases the download is not repeated (worker log: no second "Downloading").
4. When the project completes, make an edit, press Save (and try Ctrl+S), and confirm the "unsaved changes" browser warning fires before saving.
5. Restart the API **and** the worker, reload the project page, and confirm the edit is still there and that no processing happened again.
6. Submit the same URL again, choose "Process anyway", and confirm it completes almost instantly (the cache is used) with the same notation.
7. Delete that duplicate from the library. After the next prune (restart the worker to trigger one immediately), the original project's stems still play.

Report every step's outcome honestly. Any failure goes through `superpowers:systematic-debugging` before a fix.

- [ ] **Step 5: Commit docs (checkpoint) and hand off**

```bash
git add docs/PERSISTENCE.md docs/ARCHITECTURE_V1.md TECHNICAL_DEBT.md README.md
git commit -m "docs: document persistence, queue, retention and local setup"
```
Then use `superpowers:finishing-a-development-branch`. Per the user's global rules, pushing and opening the PR (`git push -u origin v1-6a_persistence-queue-storage`, `gh pr create`, body closing #80–#83 and ending with the required attribution line) happens only when the user asks.
