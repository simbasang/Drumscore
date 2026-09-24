# Persistence, queue and storage (Epic 6 Slice A)

How projects, jobs, artifacts and scores are stored and processed once the MVP's
in-memory job store was replaced by Postgres-backed persistence, a durable lease-based
queue with separate worker processes, atomic artifact storage with lifecycle pruning,
and a stage cache. `backend/app/persistence/tables.py` is the schema's source of truth;
this doc is a human-readable mirror — if they disagree, the code is correct and this
doc is stale.

## 1. Overview

Postgres holds `projects`, `jobs` (which is also the queue), `artifacts`, `analyses`,
`score_versions` and `stage_cache`. Files live under `STORAGE_ROOT` and are referenced
by relative keys of the form `projects/<project_id>/<job_id>/<file>`
(`app.storage.artifact_key`); the API never returns or accepts absolute filesystem
paths.

```
   API  ---enqueues--->  Postgres  <---claims/commits---  workers
                             ^                                |
                             |                                v
                        (rows only)                       storage
                                                        (STORAGE_ROOT)
```

The API only creates projects/jobs and reads state; it never runs the pipeline.
Separate `python -m app.worker` processes claim jobs from Postgres and write files to
storage directly.

## 2. Schema

Copied from `backend/app/persistence/tables.py` (the source of truth;
`backend/tests/test_migrations.py` enforces that the Alembic migrations in
`backend/migrations` produce a schema identical to this metadata).

### `projects`

| Column        | Type                    | Nullable | Notes                          |
|---------------|-------------------------|----------|---------------------------------|
| `id`          | `Uuid`                  | no       | primary key                    |
| `title`       | `Text`                  | no       |                                 |
| `source_kind` | `Text`                  | no       | e.g. `youtube`                 |
| `source_url`  | `Text`                  | no       |                                 |
| `source_key`  | `Text`                  | no       | `"<provider>:<external_id>"`; indexed (`ix_projects_source_key`) |
| `created_at`  | `DateTime(timezone=True)` | no     |                                 |
| `updated_at`  | `DateTime(timezone=True)` | no     |                                 |
| `deleted_at`  | `DateTime(timezone=True)` | yes    | soft delete                    |

### `jobs`

| Column             | Type                    | Nullable | Notes                                             |
|--------------------|-------------------------|----------|-----------------------------------------------------|
| `id`                | `Uuid`                 | no       | primary key                                        |
| `project_id`        | `Uuid`                 | no       | FK `projects.id`, `ON DELETE CASCADE`; indexed (`ix_jobs_project_id`) |
| `status`            | `Text`                 | no       | see §3                                             |
| `attempts`          | `Integer`               | no       |                                                     |
| `max_attempts`      | `Integer`               | no       |                                                     |
| `available_at`      | `DateTime(timezone=True)` | no    | job is not claimable before this                   |
| `lease_owner`       | `Text`                 | yes      | claiming worker's identity                         |
| `lease_expires_at`  | `DateTime(timezone=True)` | yes   | see §4                                             |
| `error`             | `Text`                 | yes      | last failure message                               |
| `correlation_id`    | `Uuid`                 | no       | for cross-log correlation                          |
| `created_at`        | `DateTime(timezone=True)` | no    |                                                     |
| `updated_at`        | `DateTime(timezone=True)` | no    |                                                     |
| `finished_at`       | `DateTime(timezone=True)` | yes   | set on completion or failure                       |

Indexes: `ix_jobs_project_id`, and `ix_jobs_claim` on `(status, available_at)` to
support the claim query.

### `artifacts`

| Column        | Type                    | Nullable | Notes                                 |
|---------------|-------------------------|----------|-----------------------------------------|
| `id`          | `Uuid`                  | no       | primary key                            |
| `project_id`  | `Uuid`                  | no       | FK `projects.id`, `ON DELETE CASCADE`  |
| `job_id`      | `Uuid`                  | no       | FK `jobs.id`, `ON DELETE CASCADE`; indexed (`ix_artifacts_job_id`) |
| `kind`        | `Text`                  | no       | `source_audio` / `drums_stem` / `accompaniment_stem` / `raw_transcription` |
| `storage_key` | `Text`                  | no       | indexed (`ix_artifacts_storage_key`)   |
| `size_bytes`  | `BigInteger`            | no       |                                         |
| `sha256`      | `Text`                  | no       |                                         |
| `created_at`  | `DateTime(timezone=True)` | no    |                                         |
| `pruned_at`   | `DateTime(timezone=True)` | yes   | set once the pruner deletes the file   |

### `analyses`

| Column             | Type    | Nullable | Notes                                   |
|--------------------|---------|----------|-------------------------------------------|
| `id`               | `Uuid`  | no       | primary key                              |
| `project_id`       | `Uuid`  | no       | FK `projects.id`, `ON DELETE CASCADE`; indexed (`ix_analyses_project_id`) |
| `job_id`           | `Uuid`  | no       | FK `jobs.id`, `ON DELETE CASCADE`; unique (`uq_analyses_job_id`) |
| `pipeline_version` | `Text`  | no       |                                           |
| `tempo_bpm`        | `Double`| no       |                                           |
| `tempo_map`        | `JSONB` | no       |                                           |
| `beats`            | `JSONB` | no       |                                           |
| `events`           | `JSONB` | no       | quantized events                         |
| `raw_events`       | `JSONB` | no       | pre-quantization, for diagnostics        |
| `created_at`       | `DateTime(timezone=True)` | no |                                       |

### `score_versions`

| Column        | Type    | Nullable | Notes                                              |
|---------------|---------|----------|------------------------------------------------------|
| `id`          | `Uuid`  | no       | primary key                                          |
| `project_id`  | `Uuid`  | no       | FK `projects.id`, `ON DELETE CASCADE`                |
| `analysis_id` | `Uuid`  | no       | FK `analyses.id`, `ON DELETE CASCADE`                |
| `version`     | `Integer` | no     | unique with `project_id` (`uq_score_versions_project_version`) |
| `score`       | `JSONB` | no       | frontend's `Score` JSON                              |
| `created_at`  | `DateTime(timezone=True)` | no |                                                     |

### `stage_cache`

| Column             | Type    | Nullable | Notes                                          |
|--------------------|---------|----------|---------------------------------------------------|
| `source_key`        | `Text`  | no      | part of composite primary key (`pk_stage_cache`)  |
| `stage`             | `Text`  | no      | part of composite primary key                     |
| `pipeline_version`  | `Text`  | no      | part of composite primary key                     |
| `artifacts`         | `JSONB` | no      | serialized `NewArtifact` list                     |
| `created_at`        | `DateTime(timezone=True)` | no |                                                |

## 3. Job state machine

```
queued -> downloading -> downloaded -> separating_stems -> stems_separated
       -> transcribing -> transcribed -> mapping_tempo -> completed
```

Any state can transition to `failed`. A stage whose output is already cached (same
`(source_key, stage, PIPELINE_VERSION)`, see §6) skips straight to that stage's "done"
status (`downloaded` / `stems_separated` / `transcribed`) without re-running the engine;
when the stems are cached, extraction is skipped entirely (§6).
Retrying a failed job (`requeue_failed_job`) resets it to `queued` with `attempts = 0`,
clears `error`, `lease_owner`, `lease_expires_at` and `finished_at`.

Defined in `backend/app/persistence/models.py` (`JobStatus`); enforced by
`backend/app/pipeline/runner.py` (`_run_stages`).

## 4. Claim and lease semantics

A worker claims the oldest eligible job with:

```sql
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
```

(`backend/app/persistence/postgres.py`, `_CLAIM_SQL`.) `FOR UPDATE SKIP LOCKED` lets
multiple worker processes poll concurrently without blocking on each other.

- **Lease**: `LEASE_SECONDS` (default 300) from the claim/last heartbeat.
- **Heartbeat**: every `HEARTBEAT_SECONDS` (default 60), a background thread
  (`app/worker/heartbeat.py`, `LeaseHeartbeat`) extends the lease. If the extension is
  refused (another worker already reclaimed the job after expiry), the heartbeat sets
  `lost = True`.
- **Lost lease**: the pipeline runner checks `should_stop()` between stages
  (`_checkpoint`); if the heartbeat reports loss, it raises `JobAbandoned` (as it does
  when a stage raises after the loss was reported). A store
  write against a lease the caller no longer owns raises `LeaseLostError`
  (`_owned_update` in `postgres.py`) — both are caught in `Worker.run_once`, which logs
  and moves on without touching the job further (another worker now owns it).
- **SIGTERM / Ctrl+C / graceful stop**: the worker's signal handler calls
  `Worker.stop()`, which only sets a flag. The engine children (Demucs, DrumScript) are
  started outside the terminal's signal group (`app/engine_process.py`:
  `CREATE_NEW_PROCESS_GROUP` on Windows, a new session on POSIX), so the signal reaches
  the worker but not them, and the stage in flight either **finishes** or is
  **abandoned**:
  - if the stage finishes, its output is committed as usual and `should_stop()` is true
    at the next checkpoint (`_checkpoint`), so `process_job` raises `JobAbandoned`;
  - if the stage raises anything after the stop was requested (for example yt-dlp's
    in-process ffmpeg child, which does share the terminal's signals, dies with it),
    `process_job` does not classify the error: it raises `JobAbandoned` instead of
    failing the job or scheduling a retry.

  Either way the worker then releases its lease (`release_lease`, unless the lease was
  already lost), which makes the job claimable immediately and refunds the attempt the
  claim added. Committed stages stay; the next claim resumes after the last one. No
  stage output is ever half-written: files are renamed into place before their rows
  are committed (§6).
- **Attempts vs. `max_attempts`**: `attempts` is incremented on every claim and
  decremented again (floored at 0) by `release_lease`, so graceful stops and deploys do
  not use up attempts. If a worker is killed hard (no graceful stop), the lease simply
  expires and the job is reclaimed with `attempts` already incremented for the dead
  attempt. `Worker.run_once` fails a job outright, without running it, if
  `attempts > max_attempts` at claim time (this can only happen when the previous
  attempt died without recording anything).

## API admission limits

`POST /api/projects` and `POST /api/projects/{id}/retry` both refuse to
create/requeue work when the API is at its resource limits, checked in
`_admit_new_job` (`app/api/projects.py`) before the write: `507` when
`Store.live_artifact_bytes()` has reached `STORAGE_MAX_BYTES`, `503` (with
`Retry-After: 60`) when `Store.count_active_jobs()` has reached
`MAX_ACTIVE_JOBS`. See `docs/OPERATIONS.md#limits` for the full limits
table, exact response bodies, and the advisory-under-concurrency caveat.

## 5. Failure policy

Exceptions from `is_permanent()` (`backend/app/pipeline/errors.py`, `PERMANENT_ERRORS`)
fail the job immediately — retrying the same input cannot succeed:

- `AudioExtractionError`
- `StemSeparationError`
- `TranscriptionError`
- `TempoEstimationError`
- `BeatDetectionError`
- `InsufficientBeatsError`
- `InvalidSourceUrlError`

Any other exception is treated as transient. If `attempts >= max_attempts`, the job
fails; otherwise it's rescheduled with exponential backoff:
`RETRY_BASE_SECONDS * 2 ** (attempts - 1)` seconds (`backoff_seconds`), default base 30
s, `MAX_ATTEMPTS = 3` — so retries land at 30 s, 60 s, then fail.

## 6. Idempotency and cache

Each pipeline stage writes its output to a temp file under storage's `tmp/` directory,
`fsync`s it, and atomically renames it into its final key (`LocalArtifactStorage.put`)
before any database write happens. Only then is the job's status, the new `artifacts`
rows, and (if the stage produced a cacheable output) the `stage_cache` row committed
together in one transaction (`PostgresStore.commit_stage`). A crash at any point before
that commit leaves, at worst, an orphaned file with no row — never a row pointing at a
missing or partial file — so a re-run of `_run_stages` reliably detects (via
`_live_artifacts`) which stages still need to run.

A cache entry is keyed by `(source_key, stage, PIPELINE_VERSION)`
(`backend/app/pipeline/version.py`). Bump `PIPELINE_VERSION` whenever an extractor,
separator, transcriber, or tempo/beat engine (or its parameters) changes, so stale
cache entries are never reused. When a second project is created for a `source_key`
that already has cached stage output (a duplicate submission via `POST /api/projects`
with `force=true`), its job's stages reuse the same cache entries — its `artifacts`
rows are created pointing at the *same* `storage_key` strings as the original project's
artifacts, rather than re-running extraction/separation/transcription. When a usable
`separate` entry exists (all its files are present), the job skips extraction entirely
and links the cached stems, so a duplicate submitted after the pruner removed the
original's source audio (§7) does not download the song again. The duplicate keeps the
title `POST /api/projects` copied from the existing project.

The runner logs `Job <id> running stage <stage>` just before a stage's engine runs, and
`Job <id> reusing cached <stage> output` for a cache hit, so the worker log shows which
stages actually ran (for example, that a duplicate did not download again).

## 7. Retention

The pruner (`backend/app/worker/pruner.py`, invoked from `Worker.maybe_prune` every
`PRUNE_INTERVAL_SECONDS`, default 3600 s / hourly) runs under a Postgres advisory lock
(`maintenance_lock`, key `6021001`) so only one worker process performs it at a time;
other workers skip their turn if they can't acquire it.

Each run:

1. Computes disposable storage keys: a storage key is disposable only when **every**
   artifact row referencing it is disposable — the project is soft-deleted, or the
   artifact's job is `failed` and finished before `now - FAILED_JOB_RETENTION_DAYS`
   days, or the artifact is `source_audio` and its job is `completed` (source audio is
   removed once a job completes; stems and transcription output are not pruned on
   completion). This is `_DISPOSABLE_SQL`'s `GROUP BY storage_key HAVING bool_and(...)`.
2. Deletes each disposable key's file from storage, then marks the corresponding
   `artifacts.pruned_at` and drops any `stage_cache` entry referencing that key
   (`mark_storage_keys_pruned`). Files are deleted **before** their rows are marked
   pruned, so a crash in between only means the next run re-deletes (a missing file is
   a no-op) and then marks the rows — never the reverse, which could leave a row
   pointing at nothing without record of it.
3. Purges soft-deleted projects' rows outright (`purge_deleted_projects`; cascades to
   their jobs/artifacts/analyses/score_versions via `ON DELETE CASCADE`).
4. Deletes temp files/staging directories under storage's `tmp/` older than 24 hours
   (`delete_stale_temp`).
5. Logs a warning if total storage usage exceeds `STORAGE_WARN_BYTES` (default 50 GiB).

There is no startup temp sweep: a live worker process's staging directory
(`ArtifactStorage.staging_dir()`) can legitimately be older than one lease (e.g. a slow
stem-separation run), so sweeping temp files at startup could delete another worker's
in-progress output. Temp cleanup only ever happens from the pruner's 24-hour-old check.

## 8. Migrations workflow

Schema changes: edit `backend/app/persistence/tables.py` first, then:

```bash
cd backend
uv run alembic revision -m "<change>"
```

Write the generated revision's `upgrade()`/`downgrade()` by hand (Alembic's
autogenerate is not trusted blindly here), then verify:

```bash
uv run pytest tests/test_migrations.py
```

which checks migrations apply cleanly from empty, that the resulting schema matches
`tables.py`'s metadata exactly (`compare_metadata`), and that downgrade-then-upgrade
round-trips.

In development, the API applies migrations on startup (`RUN_MIGRATIONS_ON_STARTUP=true`
by default, `app/main.py`'s `lifespan` calling `upgrade_to_head`). In production (Slice
C), set `RUN_MIGRATIONS_ON_STARTUP=false` and run migrations as an explicit deploy step:

```bash
cd backend && uv run alembic upgrade head
```

## 9. Configuration

Env vars read by `backend/app/config.py` (`Settings`, also loadable from `backend/.env`;
see `backend/.env.example`). Two rules are validated at startup:

- A relative `STORAGE_ROOT` resolves against the `backend/` directory (the same place
  `backend/.env` is read from), not the process's working directory, so the API and the
  workers always use the same storage whatever directory they were started from.
- `HEARTBEAT_SECONDS` must be less than `LEASE_SECONDS`; otherwise the lease would
  expire between heartbeats and settings loading fails. When shortening the lease,
  shorten the heartbeat too.

| Env var                       | Default                                                              |
|--------------------------------|-----------------------------------------------------------------------|
| `DATABASE_URL`                 | `postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore`  |
| `STORAGE_ROOT`                 | `<backend>/data` (relative values resolve against `<backend>`)       |
| `WORKER_CONCURRENCY`           | `2`                                                                   |
| `LEASE_SECONDS`                | `300`                                                                 |
| `HEARTBEAT_SECONDS`            | `60` (must be less than `LEASE_SECONDS`)                              |
| `POLL_INTERVAL_SECONDS`        | `2.0`                                                                 |
| `MAX_ATTEMPTS`                 | `3`                                                                   |
| `RETRY_BASE_SECONDS`           | `30`                                                                  |
| `FAILED_JOB_RETENTION_DAYS`    | `7`                                                                   |
| `PRUNE_INTERVAL_SECONDS`       | `3600`                                                                |
| `STORAGE_WARN_BYTES`           | `53687091200` (50 * 1024^3)                                          |
| `RUN_MIGRATIONS_ON_STARTUP`    | `true`                                                                |

## 10. Score versions

Every `PUT /api/projects/{id}/score` appends a new `score_versions` row rather than
overwriting one (`PostgresStore.save_score`); `version` increments per project starting
at 1. Optimistic concurrency: the request carries `base_version`, and the save is
rejected with `ScoreVersionConflictError` (surfaced as `409` with the real
`latest_version`) unless `base_version` equals the current latest version for that
project — a row lock on the project (`SELECT ... FOR UPDATE`) serializes concurrent
saves so this check can't race. The backend validates only that `score["measures"]` is
a list (`app/api/projects.py`); it does not otherwise validate the `Score` JSON's
shape, which is the frontend's contract to keep.
