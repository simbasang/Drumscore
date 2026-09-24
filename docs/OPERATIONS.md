# Operations

How to run Drumscore's backend, what each environment variable does, how
secrets are kept out of logs and responses, what limits protect the API and
where they're enforced, the log format, and the structured event catalogue.
`backend/app/config.py` (`Settings`) is the source of truth for every value
below; if this doc and the code disagree, the code is correct and this doc
is stale.

## 1. Processes

Production runs these as containers (`docs/DEPLOYMENT.md`); the commands
below are the same processes run directly. Two kinds of process share one
Postgres database and one `STORAGE_ROOT`:

- **API** (one process):

  ```bash
  cd backend
  uv run uvicorn app.main:app --no-access-log
  ```

  `--no-access-log` disables uvicorn's own access log. The `http_request`
  event (§6) already records every request's method, path, status and
  duration; uvicorn's access logger would otherwise be routed into the same
  JSON stream (`configure_logging` sends `uvicorn`/`uvicorn.error`/
  `uvicorn.access` through the root handler) and duplicate every line.

- **Workers** (one or more processes; `WORKER_CONCURRENCY` of them is the
  usual deployment):

  ```bash
  cd backend
  uv run python -m app.worker
  ```

  Each worker process claims and runs one job at a time from the Postgres
  queue; running `WORKER_CONCURRENCY` processes bounds how many pipelines
  run concurrently (§4 of `docs/PERSISTENCE.md`).

- **Migrations** (one-shot, before the API/workers start; the API can also
  apply them itself when `RUN_MIGRATIONS_ON_STARTUP` is true):

  ```bash
  cd backend
  uv run python -m app.persistence.migrations
  ```

- **Readiness**: `GET /api/health` is liveness only; `GET /api/ready` and
  `python -m app.readiness api|worker` check the database (reachable, migrated
  to head), the storage root (writable) and, for a worker, the engines
  (`docs/DEPLOYMENT.md` §4).

## 2. Configuration

Every setting is read from the environment, or from `backend/.env` (see
`backend/.env.example` for development placeholders). Reading a relative
`STORAGE_ROOT` resolves it against the `backend/` directory, not the
process's working directory, so the API and every worker use the same
storage regardless of where they were started from.

| Variable | Default | Secret | Meaning |
|---|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore` | yes | Postgres connection string. |
| `STORAGE_ROOT` | `<backend>/data` | | Root directory for artifact storage; relative values resolve against `backend/`. |
| `WORKER_CONCURRENCY` | `2` | | Documented count of worker processes to run; not enforced by the code itself (§4). |
| `LEASE_SECONDS` | `300` | | How long a worker's claim on a job lasts before another worker can reclaim it. |
| `HEARTBEAT_SECONDS` | `60` | | How often a worker extends its lease while processing; must be less than `LEASE_SECONDS`. |
| `POLL_INTERVAL_SECONDS` | `2.0` | | How often an idle worker polls for the next claimable job. |
| `MAX_ATTEMPTS` | `3` | | Attempts a transient failure gets before the job is failed outright. |
| `RETRY_BASE_SECONDS` | `30` | | Base for the exponential retry backoff (`RETRY_BASE_SECONDS * 2 ** (attempts - 1)`). |
| `FAILED_JOB_RETENTION_DAYS` | `7` | | How long a failed job's artifacts are kept before the pruner disposes of them. |
| `PRUNE_INTERVAL_SECONDS` | `3600` | | How often a worker runs the storage/database pruner. |
| `STORAGE_WARN_BYTES` | `53687091200` (50 GiB) | | Logs a warning once total storage usage exceeds this; does not block anything. |
| `RUN_MIGRATIONS_ON_STARTUP` | `true` | | Whether the API applies Alembic migrations on startup. |
| `LOG_LEVEL` | `INFO` | | Root logger level. |
| `LOG_FORMAT` | `json` | | `json` or `text` (§5). |
| `MAX_SOURCE_DURATION_SECONDS` | `900` | | Longest source duration accepted before download starts. |
| `MAX_DOWNLOAD_BYTES` | `209715200` (200 MiB) | | Largest downloaded audio size accepted. |
| `MAX_REQUEST_BYTES` | `5242880` (5 MiB) | | Largest HTTP request body accepted by the API. |
| `MAX_ACTIVE_JOBS` | `20` | | Most jobs that may be queued or running at once before new jobs are refused. |
| `STORAGE_MAX_BYTES` | `107374182400` (100 GiB) | | Most live artifact bytes allowed before new jobs are refused. |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | | Browser origins allowed to call the API: the frontend's public URL(s), comma-separated or a JSON list. |

## 3. Secrets

`DATABASE_URL` is the only secret Drumscore holds. It is a Pydantic
`SecretStr`, so it never appears in a `repr()` (accidental logging of the
`Settings` object, a traceback, etc. prints `SecretStr('**********')`, not
the real value); code that needs the real string calls
`.get_secret_value()` explicitly at the point of use.

As a second layer, every log line — JSON or text — passes through
`app.observability.redaction.redact` before it is written: passwords in
`scheme://user:password@host` URLs and in libpq-style `password=...` pairs
are replaced with `***`, so even a connection string logged incidentally
(for example inside another exception's message) does not leak its
password.

`backend/.env` is git-ignored (`backend/.gitignore`) and must never be
committed. `backend/.env.example` holds only development placeholders — the
default local Postgres user/password above, never a real credential.
Production supplies secrets through the environment: the Compose stack
(`docs/DEPLOYMENT.md` §2) reads `POSTGRES_PASSWORD` from the git-ignored
`deploy/.env` and builds `DATABASE_URL` from it; no secret is baked into an
image.

`job.error` (the API's own error text, returned by `GET
/api/projects/{id}`) is sanitized before it is ever stored, via
`app.observability.redaction.sanitize_error_message`:

- known absolute directories are replaced with placeholders — the storage
  root becomes `<storage>`, the OS temp directory becomes `<tmp>`, the
  backend's own directory becomes `<app>`;
- any other absolute Windows or POSIX path becomes `<path>`;
- passwords are redacted the same way as in logs;
- the result is capped at 500 characters, keeping the first 200 characters,
  a `…`, and the last 299 characters (an engine's stderr usually ends with
  the actual error, so the tail is kept alongside the head).

The unsanitized, untruncated text is still written to the worker's own log
(`logger.exception(...)` in `app/pipeline/runner.py`) for diagnostics — only
the value stored on the job and returned by the API is sanitized.

## 4. Limits

Admission checks (`MAX_ACTIVE_JOBS`, `STORAGE_MAX_BYTES`) are **advisory
under concurrency**: `_admit_new_job` (`app/api/projects.py`) reads the
current count/usage and only then inserts a new job, with no lock across
the two steps, so two requests that both read a value just under the limit
can both be admitted — the queue or storage usage can briefly overshoot by
the number of concurrent requests. `STORAGE_MAX_BYTES` counts **live
artifact bytes**: `Store.live_artifact_bytes()` sums the size of distinct,
un-pruned artifact storage keys, not temp/staging files under storage's
`tmp/` directory. Project deletion is soft: a deleted project's
`live_artifact_bytes` contribution only drops once a worker's next prune
run marks its artifacts pruned (up to `PRUNE_INTERVAL_SECONDS` later, and
only if a worker is running), so the `507` response below can still occur
for a short time after enough projects have been "deleted" to bring usage
under the limit.

| Limit | Value | Enforced where | Response / error text |
|---|---|---|---|
| `MAX_SOURCE_DURATION_SECONDS` | 900 s (15 min) | `YtDlpAudioExtractor._check_limits`, from the source's metadata, before any download | Job fails permanently; `job.error` = `"Source is {mm:ss} long; the limit is 15:00"` |
| `MAX_DOWNLOAD_BYTES` | 200 MiB | `YtDlpAudioExtractor._check_limits` (metadata `filesize`/`filesize_approx`, before download) and yt-dlp's own `max_filesize` backstop during download (for sources with no size in their metadata) | Job fails permanently; `job.error` = `"Source audio is {N} MB; the limit is 200 MB"`, or (backstop) `"Audio extraction did not produce an output file (the download may exceed the 200 MB limit)"` |
| `MAX_REQUEST_BYTES` | 5 MiB | `RequestSizeLimitMiddleware`, on every HTTP request (declared `Content-Length` or bytes actually received) | `413`, body `{"detail": "Request body is larger than the 5242880-byte limit"}` |
| `MAX_ACTIVE_JOBS` | 20 | `_admit_new_job`, on `POST /api/projects` and `POST /api/projects/{id}/retry`, via `Store.count_active_jobs()` | `503`, `Retry-After: 60`, body `{"detail": "Too many jobs are queued or running; try again later"}` |
| `STORAGE_MAX_BYTES` | 100 GiB | `_admit_new_job`, on `POST /api/projects` and `POST /api/projects/{id}/retry`, via `Store.live_artifact_bytes()` | `507`, body `{"detail": "Storage is full; delete projects or raise STORAGE_MAX_BYTES"}` |
| URL length | 2048 characters | `CreateProjectRequest.url` (`Field(max_length=2048)`), on `POST /api/projects` | `422` (FastAPI/Pydantic validation error) |
| `WORKER_CONCURRENCY` | 2 processes | Deployment: run this many `python -m app.worker` processes | — (not enforced by application code; see §1) |
| Demucs subprocess timeout | 600 s | Hard-coded `_TIMEOUT_SECONDS` in `demucs_stem_separator.py` | Job fails permanently; `job.error` = `"Demucs timed out after 600 seconds"` |
| DrumScript subprocess timeout | 600 s | Hard-coded `_TIMEOUT_SECONDS` in `drumscript_transcriber.py` | Job fails permanently; `job.error` = `"Drum transcription timed out after 600 seconds"` |
| yt-dlp socket timeout | 30 s | `socket_timeout` option in `youtube_audio_extractor.py` | Download raises `yt_dlp.utils.DownloadError`; job fails permanently with `"Failed to download audio: ..."` |
| `LEASE_SECONDS` | 300 s | Worker claim/lease (`docs/PERSISTENCE.md` §4) | A lease past this age is reclaimable by another worker |
| `MAX_ATTEMPTS` | 3 | Transient-failure retry cap (`docs/PERSISTENCE.md` §5) | Job fails outright once `attempts >= max_attempts` |
| `STORAGE_WARN_BYTES` | 50 GiB | Pruner, each run (`docs/PERSISTENCE.md` §7) | Warning only — logs, never blocks admission |

## 5. Logs

`LOG_FORMAT` selects one of two single-line-per-record formats on stdout,
both passed through the same redaction as §3:

- `json` (default, production): one JSON object per line with keys `ts`
  (ISO-8601, millisecond precision, UTC), `level`, `logger`, `message`, any
  context fields, any event fields, and `exc` (a formatted traceback) when
  the record carries exception info.
- `text` (readable local logs; `backend/.env.example` sets this): a
  standard `%(asctime)s %(levelname)s %(name)s %(message)s` line, with any
  context/event fields appended as `key=value` pairs.

**Context fields** are bound for the duration of a request or a job (via
`app.observability.logging.log_context`, a `contextvars`-based binding
inherited by any thread spawned inside the block, including a worker's
heartbeat thread) and are copied onto every log record created inside that
scope, not just ones from explicit `log_event` calls:

- API: `request_id` (bound by `RequestContextMiddleware` for the life of
  each HTTP request).
- Workers: `job_id`, `correlation_id`, `project_id`, `worker` (bound by
  `Worker.run_once` for the life of one claimed job).

**To follow one job's full log trail**, filter on its `job_id`. The API's
own `project_created` and `job_requeued` events also carry `job_id` (and
`correlation_id`, `project_id`), so the job can be traced from the moment
it's created or requeued through every stage a worker runs for it.

## 6. Event catalogue

Structured events are emitted with `app.observability.logging.log_event`,
which sets the event name as the record's `message` and everything else as
top-level fields (merged with whatever context fields are bound, §5).

| Event | Emitted by | Fields | `outcome` values |
|---|---|---|---|
| `http_request` | `RequestContextMiddleware`, after every HTTP request | `method`, `path`, `status`, `duration_ms` | — |
| `project_created` | `POST /api/projects`, after a project and its first job are created | `source_key` (plus bound `project_id`, `job_id`, `correlation_id`) | — |
| `job_requeued` | `POST /api/projects/{id}/retry`, after a failed job is requeued | (bound `project_id`, `job_id`, `correlation_id`) | — |
| `stage_started` | `_timed_stage`, when a pipeline stage's engine is about to run | `stage` | — |
| `stage_finished` | `_timed_stage` (a stage that ran) or `_obtain` (a cache hit) | `stage`, `duration_ms`, `outcome` | `ran`, `cached` |
| `stage_failed` | `_timed_stage`, when a stage's engine raises | `stage`, `duration_ms`, `error_type`, `permanent` | — |
| `job_finished` | `Worker._log_finished`, once per claimed job | `outcome`, `duration_ms`, `attempt` | `completed`, `failed`, `retry_scheduled`, `abandoned`, `lease_lost` |
