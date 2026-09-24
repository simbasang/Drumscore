# Epic 6 Slice A — Persistence, Durable Queue, Storage & Idempotency

Covers issues #80 (V1-029), #81 (V1-030), #82 (V1-031) and #83 (V1-032) of Epic 6 (#33).
Slice B (#84 observability/limits) and Slice C (#85 containers/deployment, #86 E2E/release) get their own specs.

## Decisions

| Topic | Decision |
|---|---|
| Deployment target | Single host, Postgres |
| Ownership | No accounts. Single-user app with a "My projects" library. Access control comes from the deployment (private network / reverse-proxy auth) |
| Retention | Projects are kept until the user deletes them. Downloaded source audio is pruned after success, failed-job files after N days |
| Duplicate source | API reports the existing project. The UI offers "Open existing" or "Process anyway". Stage outputs are reused through a cache |
| Queue | A queue table in our own Postgres schema, claimed with `FOR UPDATE SKIP LOCKED` under leases. Workers run as a separate process |
| Stack | SQLAlchemy 2, Alembic, psycopg 3, testcontainers (latest stable versions, checked on PyPI when added) |

## Current state (replaced by this slice)

- `app/jobs.py`: in-memory `JobStore` holding domain results directly on a frozen `Job` dataclass. Everything is lost on restart.
- `app/api/jobs.py`: the API runs `run_pipeline` in FastAPI `BackgroundTasks`, capped by `PipelineConcurrencyLimiter` (2).
- `app/job_cleanup.py`: deletes every job and its files after 24 h.
- The API exposes absolute filesystem paths (`audio_path`, `drums_path`, `accompaniment_path`).
- Corrected scores (Epic 5) are never saved. `frontend/lib/score/serialization.ts` exists but nothing uses it.
- The frontend is a single page (`app/page.tsx` + `JobForm`) keyed by an in-memory job ID.

## Data model (#80)

Postgres tables, managed by SQLAlchemy 2 models and Alembic migrations.

### `projects`
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| title | text | set to the URL at creation. The extract stage replaces it with the video title if the extractor reports one (the extractor contract gains an optional `title`) |
| source_kind | text | `youtube` |
| source_url | text | as submitted |
| source_key | text, indexed, not unique | normalized source identity (YouTube video ID). Not unique because "Process anyway" creates a second project |
| created_at, updated_at | timestamptz | |
| deleted_at | timestamptz null | soft delete. The pruner hard-deletes |

### `jobs` (also the queue)
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| project_id | uuid fk → projects (cascade) | |
| status | text | existing `JobStatus` values plus `completed` |
| attempts | int | incremented on each claim |
| max_attempts | int | default 3 |
| available_at | timestamptz | used for backoff |
| lease_owner | text null | worker identity (`host:pid:uuid`) |
| lease_expires_at | timestamptz null | |
| error | text null | |
| correlation_id | uuid | added now, used by Slice B logging |
| created_at, updated_at, finished_at | timestamptz | |

A project has many jobs over time. Its analysis comes from its latest `completed` job.

### `artifacts`
| column | type | notes |
|---|---|---|
| id | uuid pk | |
| project_id, job_id | uuid fk | |
| kind | text | `source_audio`, `drums_stem`, `accompaniment_stem`, `raw_transcription` |
| storage_key | text | relative to `STORAGE_ROOT`, never absolute |
| size_bytes | bigint | |
| sha256 | text | |
| created_at | timestamptz | |
| pruned_at | timestamptz null | set when the pruner removes the file |

### `analyses`
One row per completed job: `id`, `project_id`, `job_id` (unique), `pipeline_version`, `tempo_bpm`, `tempo_map` (JSONB), `beats` (JSONB), `events` (JSONB), `raw_events` (JSONB), `created_at`.
The JSONB is serialized from the application's own dataclasses (`DrumEvent`, `BeatPoint`, `TempoMap`). No third-party types are stored. Source timestamps (`DrumEvent.time`) round-trip exactly (floats stored as JSON numbers, round-trip tested).

### `score_versions`
`id`, `project_id`, `analysis_id`, `version` (int, unique per project, increasing), `score` (JSONB, the application-owned `Score` from `frontend/lib/score/types.ts`), `created_at`.
Every save adds a row, and the latest version is what gets loaded. The backend validates only the structure (an object with a `measures` array). It does not interpret score contents.

### `stage_cache` (#83)
`(source_key, stage, pipeline_version)` primary key → `artifact_ids` (for extract/separate) or `payload` (JSONB raw events, for transcribe), `created_at`.
`pipeline_version` is a constant in code that is bumped whenever an engine or its parameters change, so stale results are never reused.

### Repository boundary
`JobStore` is replaced by repository interfaces (`ProjectRepository`, `JobRepository`, `ArtifactRepository`, `AnalysisRepository`, `ScoreRepository`, `StageCache`) with a Postgres implementation and an in-memory fake for unit tests. Pipeline stage functions keep their shape and depend on the interfaces.

### Migration strategy
- Alembic owns the schema. Every schema change is a new revision with both upgrade and downgrade.
- Dev: the API runs `alembic upgrade head` on startup. Production: an explicit migration step (wired in Slice C).
- CI/integration tests: upgrade from empty, then a downgrade/upgrade round-trip.
- There is no data migration from MVP in-memory jobs, because they never survived a restart.

## Queue and workers (#81)

### Submit
`POST /api/projects {url}`: validate → `source_key`. If a non-deleted project with that `source_key` exists and `force` is not set, return `409 {existing_project_id}`. Otherwise create the project and a `queued` job (`available_at = now`) in one transaction and return `201 {project, job}`.
The API never runs the pipeline. `BackgroundTasks` and `PipelineConcurrencyLimiter` are removed.

### Worker process
`python -m app.worker`. Concurrency is the number of worker processes (`WORKER_CONCURRENCY`, default 2), each processing one job at a time. This bounds heavy Demucs runs the same way the semaphore used to.

Claim (one statement):
```sql
UPDATE jobs SET lease_owner = :me, lease_expires_at = now() + :lease,
                attempts = attempts + 1, updated_at = now()
WHERE id = (
  SELECT id FROM jobs
  WHERE status NOT IN ('completed', 'failed')
    AND available_at <= now()
    AND (lease_expires_at IS NULL OR lease_expires_at < now())
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1)
RETURNING *;
```
- Lease 5 min. A heartbeat thread extends it every 60 s while a stage runs. If an extension finds the lease has been lost, the worker abandons the job.
- If nothing is claimed: sleep 2 s ± jitter.
- A job belonging to a soft-deleted project is marked failed ("project deleted") and not processed.
- `attempts > max_attempts` at claim time → the job is marked `failed` with the last error.

### Stage execution and idempotency
Stages run in the current order: extract → separate → transcribe → tempo-map. Before each stage the worker looks for existing output in this order:
1. an artifact or analysis already committed for this job, then
2. a `stage_cache` hit for `(source_key, stage, pipeline_version)`. The cached artifacts are linked to this job (new artifact rows that point at the same storage keys, which are shared and reference-counted by rows when pruning).

If output is found, the stage is skipped. Otherwise it runs, writes its output to a temp path under `STORAGE_ROOT/tmp`, fsyncs, and atomically renames it into its final key. Only then does it commit the artifact row, the cache entry and the status transition in one transaction.
A crash therefore leaves either no row or a complete file, never a partial file that counts as done. The final stage writes the `analyses` row and sets `completed`.

Tempo-mapping keeps its current logic (quantization, measure floor shift) unchanged. It is only moved.

### Failure handling
- Expected domain failures (`AudioExtractionError` for invalid or unavailable media, `BeatDetectionError`, "fewer than 2 beats", …) → `failed` right away with the message.
- Unexpected exceptions → retried with `available_at = now + 30 s · 2^(attempts-1)` until `max_attempts`, then `failed`.
- Lease expiry (worker died) → reclaimed by any worker, which resumes at the first stage without output. There is no separate recovery sweep.
- `POST /api/projects/{id}/retry` (only when the latest job is `failed`) → the same job goes back to `queued`, with `attempts = 0`, error cleared and `available_at = now`. It resumes from the saved stage output.
- SIGTERM: the worker stops claiming, finishes or abandons the current stage, and releases its lease (`lease_expires_at = now`) so the job is picked up right away.
- On startup: delete temp files older than the lease duration.

## Durable storage and lifecycle (#82)

`ArtifactStorage` interface: `put(key, source_path)`, `open(key)`, `path(key)`, `delete(key)`, `exists(key)`. `LocalArtifactStorage` lives under `STORAGE_ROOT`. Keys look like `projects/<project_id>/<job_id>/<kind>.<ext>`.

The pruner runs hourly in the worker, guarded by `pg_try_advisory_lock` so only one worker runs it. It:
- deletes the `source_audio` file after its job has `completed` (sets `pruned_at`). If source audio is also held by `stage_cache`, the cache entry is dropped with it.
- deletes artifacts of `failed` jobs older than `FAILED_JOB_RETENTION_DAYS` (default 7)
- hard-deletes soft-deleted projects: rows (cascade) and every storage key no longer referenced by a live artifact row
- deletes temp files older than 24 h
- logs a warning when the total size of `STORAGE_ROOT` is above `STORAGE_WARN_BYTES`

`job_cleanup.py` and its 24 h delete-everything rule are removed.

## API (replaces `/api/jobs`)

| method & path | result |
|---|---|
| `POST /api/projects` `{url}` `?force=true` | `201 {project, job}`, `409 {existing_project_id}`, `422` invalid URL |
| `GET /api/projects` | library list: id, title, latest job status, updated_at, has_edits (excludes deleted) |
| `GET /api/projects/{id}` | project, latest job (status, attempts, error), progress stage |
| `DELETE /api/projects/{id}` | soft delete, `204` |
| `POST /api/projects/{id}/retry` | `202`, `409` if the latest job is not failed |
| `GET /api/projects/{id}/analysis` | same response shape as today's `/api/jobs/{id}/analysis` |
| `GET /api/projects/{id}/diagnostics` | same response shape as today |
| `GET /api/projects/{id}/audio/{drums\|accompaniment}` | file through `ArtifactStorage`; `409` not ready, `410` pruned |
| `GET /api/projects/{id}/score` | latest score version `{version, score}`, `404` if never saved |
| `PUT /api/projects/{id}/score` `{score, base_version}` | `201 {version}`, `409` if `base_version` is not the latest (`null` base = first save), `422` malformed |

Absolute paths are never returned. Unknown or deleted project → `404`.

## Frontend

- `/` becomes the submit form plus the "My projects" library (list, open, delete).
- A new `/projects/[id]` page hosts the existing processing/progress, player and editor. Reloading or bookmarking works.
- `lib/api/projects.ts` replaces `lib/api/jobs.ts` and keeps the polling hardening (tolerates transient errors, a definitive 404 ends polling). Shared types (`DrumInstrument`, `Analysis`, …) move with it.
- Duplicate `409` → a dialog with "Open existing" / "Process anyway".
- Load order on the project page: `GET /score` → if found, `fromJSON` it; if `404`, build from the analysis as today.
- Saving: an explicit Save button and Ctrl/Cmd+S call `PUT /score` with `toJSON(score)` and the loaded `base_version`. The page shows an unsaved-changes indicator and warns in `beforeunload` when changes are unsaved. On a `409` conflict it shows "A newer version was saved elsewhere" with a reload action (no auto-merge).

## Configuration

`DATABASE_URL`, `STORAGE_ROOT` (default `backend/data`), `WORKER_CONCURRENCY` (2), `LEASE_SECONDS` (300), `FAILED_JOB_RETENTION_DAYS` (7), `STORAGE_WARN_BYTES`. `docker-compose.dev.yml` provides Postgres only. Containerizing the API and worker belongs to Slice C.

## Testing

TDD, aiming for 100% coverage of new code.

Backend unit (in-memory fakes, fake clock, temp dirs):
- repository fakes honour the same contract as Postgres (a shared contract test suite runs against both)
- stage skip and cache lookup order, artifact commit after rename
- error classification, backoff math, max-attempts
- pruner rules (source audio after success, failed-job retention, soft-delete purge, temp cleanup, shared storage keys)
- analysis JSONB round-trip keeps `sourceTime` exactly
- tempo-mapping behaviour unchanged (existing tests move)

Backend integration (testcontainers Postgres):
- Alembic upgrade from empty and a downgrade/upgrade round-trip
- two workers racing: exactly one claims a job
- expired lease reclaimed; the job resumes at the first stage without output
- crash mid-stage (exception after the temp write, before commit) leaves no committed artifact
- restart story: worker killed mid-job → new worker completes it → project reloads with analysis and saved score
- duplicate-source 409 / force, and a forced project reuses cached stems (the separator fake is not called)
- score save / version conflict
- API via FastAPI `TestClient` with a real DB and fake engines

Frontend (Jest + RTL, API mocks in `__mocks__`): library list/open/delete, duplicate dialog, project page load order (saved vs built), save / dirty indicator / beforeunload / conflict flows, polling via the new client.

## Documentation

- New `docs/PERSISTENCE.md`: schema, job state machine, lease/claim semantics, migration workflow, retention rules, config.
- Update the "Jobs and persistence" section of `docs/ARCHITECTURE_V1.md`.
- `TECHNICAL_DEBT.md`: record newly found debt. Mark the MVP-011 cleanup and concurrency entries superseded.

## Out of scope

Structured logging, metrics and correlation propagation (Slice B, though the column exists now); resource/security limits (Slice B); API/worker containers, production deployment, E2E and release gate (Slice C); accounts; score version history UI; auto-merge of conflicting edits.
