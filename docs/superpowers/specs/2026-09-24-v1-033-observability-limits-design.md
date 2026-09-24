# V1-033 — Observability and resource/security limits (design)

Issue: #84 (part of EPIC 6, #33). Epic 6 Slice B.

## Goal

Make every job's processing traceable across the API and worker processes,
make stage timing and failures visible, bound expensive/untrusted work, and
keep secrets out of logs and API responses.

Acceptance criteria (from #84):

- Job ID correlates logs
- Stage timing/failure visible
- Input/concurrency/timeout/storage limits exist
- Secrets handled safely

## Decisions (agreed 2026-09-24)

- Structured **JSON logs to stdout**; stage metrics are structured log events,
  not a metrics endpoint. `LOG_FORMAT=text` keeps human-readable local logs.
- Limits in scope: source duration/size, API input size + URL length, active
  job cap, hard storage cap. Existing engine timeouts stay hard-coded and are
  documented, not made configurable.
- Secrets in scope: `DATABASE_URL` as a secret with log redaction, sanitized
  `job.error`, an operations doc with env/secret policy plus tests that keep
  it honest.
- The "Engine subprocess output is decoded with the Windows code page" debt is
  fixed here, because it makes a failing Demucs/DrumScript stage lose its
  error text, contradicting "stage failure visible".

Out of scope: Prometheus/metrics endpoint, tracing, per-client rate limiting,
authentication (recorded debt), configurable engine timeouts, frontend changes
(the frontend already shows an error response's `detail`).

## 1. Logging and correlation

New module `backend/app/observability/logging.py` (stdlib only):

- `configure_logging(level: str, fmt: Literal["json", "text"])` — installs one
  stdout handler on the root logger (replacing `basicConfig` in `app/main.py`
  and `app/worker/__main__.py`), with the context filter and the redaction
  applied by the formatter. Both formats include the bound context fields.
- `log_context(**fields)` — context manager that merges fields into a
  `ContextVar[dict[str, str]]` and restores the previous value on exit.
  Nested contexts merge; inner values win.
- `ContextFilter` — copies the current context onto each `LogRecord`
  (`record.context`).
- `JsonFormatter` — one JSON object per line:
  `ts` (ISO-8601 UTC), `level`, `logger`, `message`, the context fields,
  any structured `extra` fields passed as `extra={"fields": {...}}`, and
  `exc` (formatted traceback) when present. Non-JSON-serializable values are
  rendered with `str()`.
- `TextFormatter` — the current text format followed by `key=value` pairs of
  the context and extra fields.
- `log_event(logger, event, level=INFO, **fields)` — helper that logs
  `message=event` with `fields` as structured extras, so events are greppable
  by name (`"event": "stage_finished"`; `message` equals the event name).

Worker:

- `Worker.run_once` wraps processing of a claimed job in
  `log_context(job_id=..., correlation_id=..., project_id=..., worker=owner)`.
- `LeaseHeartbeat` starts its thread with `contextvars.copy_context().run`, so
  heartbeat logs carry the job's context.

API:

- `RequestContextMiddleware` (pure ASGI, `backend/app/observability/http.py`):
  takes `X-Request-ID` from the request if it is a safe token (≤ 64 chars of
  `[A-Za-z0-9._-]`), otherwise generates a UUID4 hex; binds `request_id` for
  the request; adds `X-Request-ID` to the response; logs `http_request` with
  `method`, `path`, `status`, `duration_ms` after the response completes.
  Documented recommendation: run uvicorn with `--no-access-log` (its access
  log would duplicate `http_request`).
- `create_project` and `retry_project` bind `project_id`, `job_id`,
  `correlation_id` before logging `project_created` / `job_requeued`.

## 2. Stage metrics

`backend/app/pipeline/runner.py` logs, via `log_event`:

| Event | Fields |
|---|---|
| `stage_started` | `stage` |
| `stage_finished` | `stage`, `duration_ms`, `outcome` (`ran` \| `cached`) |
| `stage_failed` | `stage`, `duration_ms`, `error_type`, `permanent` |
| `job_finished` | `outcome` (`completed` \| `failed` \| `retry_scheduled` \| `abandoned` \| `lease_lost`), `duration_ms`, `attempt` |

- Stages: `extract`, `separate`, `transcribe` (the existing `Stage` values)
  and `map_tempo`.
- `stage_failed` is logged by the stage that raised, then the exception
  propagates unchanged to the existing failure handling (no change to the
  permanent/transient classification).
- `job_finished` is logged by `Worker.run_once` (the only place that sees
  every outcome, including abandon and lease loss). `process_job` reports its
  outcome by return value (`completed` / `failed` / `retry_scheduled`);
  `abandoned` / `lease_lost` come from the existing exceptions.
- Durations use a monotonic clock injected through `JobContext`
  (`monotonic: Callable[[], float] = time.monotonic`) and `Worker`, so tests
  are deterministic.

## 3. Limits

New `Settings` fields (env var names in upper case):

| Setting | Default | Enforced in | Result |
|---|---|---|---|
| `max_source_duration_seconds` | 900 | `YtDlpAudioExtractor` | permanent `AudioExtractionError` |
| `max_download_bytes` | 200 MiB | `YtDlpAudioExtractor` | permanent `AudioExtractionError` |
| `max_request_bytes` | 5 MiB | `RequestSizeLimitMiddleware` | HTTP 413 |
| `max_active_jobs` | 20 | `POST /api/projects`, `POST /{id}/retry` | HTTP 503 + `Retry-After` |
| `storage_max_bytes` | 100 GiB | `POST /api/projects`, `POST /{id}/retry` | HTTP 507 |

Also: `CreateProjectRequest.url` gets `max_length=2048` (HTTP 422).
Validation: every new limit must be positive; `storage_warn_bytes` must not
exceed `storage_max_bytes`.

Source limits (`YtDlpAudioExtractor`, constructed with the limits by
`default_engines(settings)`):

1. `extract_info(url, download=False)` first.
2. Reject live streams (`is_live` true or `live_status` in `is_live`,
   `is_upcoming`): "Live streams are not supported".
3. Reject when `duration` exceeds the limit: "Source is 62:10 long; the limit
   is 15:00". Unknown duration is allowed (byte limit still applies).
4. Reject when `filesize` or `filesize_approx` of the selected format exceeds
   `max_download_bytes`.
5. Download via `process_ie_result(info, download=True)` with
   `max_filesize=max_download_bytes` as a backstop; if the download produced
   no file and the size limit is the reason, the error says so.

API limits:

- `RequestSizeLimitMiddleware` (pure ASGI): rejects with 413 when
  `Content-Length` exceeds the limit, and counts streamed body bytes so a
  chunked body without `Content-Length` is cut off at the limit too.
- New `Store` methods (memory + Postgres, covered by the store contract
  tests):
  - `count_active_jobs() -> int`: jobs whose status is not `completed`/`failed`
    and whose project is not soft-deleted.
  - `live_artifact_bytes() -> int`: sum of `size_bytes` over distinct
    `storage_key`s of unpruned artifacts (cache reuse makes several rows share
    one key).
- `_admit_new_job(store, settings)` helper used by create and retry: 507
  "Storage is full…" when `live_artifact_bytes() >= storage_max_bytes`, else
  503 "Too many jobs are queued…" with `Retry-After: 60` when
  `count_active_jobs() >= max_active_jobs`. Checked before any write. Order in
  create: URL validation (422), duplicate check (409), admission (507/503),
  creation. Order in retry: project lookup (404), failed-status check (409),
  admission, requeue. The check is advisory under
  concurrency (two requests can both pass at the limit); documented, bounded
  overshoot is acceptable.

Existing limits, documented in `docs/OPERATIONS.md`: `WORKER_CONCURRENCY`,
Demucs and DrumScript 600 s timeouts, yt-dlp 30 s socket timeout,
`LEASE_SECONDS`, `MAX_ATTEMPTS`, `STORAGE_WARN_BYTES`.

## 4. Secrets and safe errors

- `Settings.database_url` becomes `SecretStr`; `get_store`, `build_worker` and
  the migration call use `.get_secret_value()`. `repr(settings)` no longer
  shows the password.
- Redaction (`backend/app/observability/redaction.py`): `redact(text)` replaces
  the password in any `scheme://user:password@host` with `***`. Applied by
  both formatters to the final formatted message and traceback.
- `sanitize_error_message(message, roots)` (same module): replaces each known
  root (`STORAGE_ROOT`, the system temp dir, the backend dir) with a
  placeholder (`<storage>`, `<tmp>`, `<app>`), then any remaining absolute
  Windows (`C:\…`) or POSIX (`/a/b…`, not part of a URL) path with `<path>`,
  applies `redact`, and caps the result at 500 characters (`…` suffix).
  `runner._handle_failure` stores the sanitized message; the unsanitized one is
  logged. `JobContext` gets `error_roots: tuple[Path, ...]`.
- Engine subprocesses: both `subprocess.run` calls pass
  `encoding="utf-8", errors="replace"` (fixes the cp1252 debt), so a failed
  engine's stderr survives into the (sanitized) job error.
- `docs/OPERATIONS.md`: every environment variable (default, meaning, secret
  or not), all limits and timeouts, log format and fields, event catalogue,
  `.env` policy (never committed; `.env.example` holds only development
  placeholders), uvicorn `--no-access-log` recommendation.
- Tests: every `Settings` field is documented in `docs/OPERATIONS.md`;
  `backend/.gitignore` ignores `.env`; every key in `backend/.env.example` is
  a `Settings` field.

## Testing

TDD per unit. Unit tests for the logging module (context binding/nesting,
JSON shape, text shape, redaction in message and traceback), middlewares
(request ID accept/reject/generate, `http_request` event, 413 for header and
chunked body), extractor limits (fake `YoutubeDL`), store contract tests for
the two new queries (memory + Postgres), API tests for 503/507/422, runner and
worker tests asserting the stage/job events and context fields via `caplog`,
sanitizer tests, engine decoding tests with non-cp1252 bytes, and the doc/env
consistency tests. Full backend and frontend suites plus lint must stay green.

Manual check before the PR: run API + one worker against local Postgres,
submit a song, and confirm the JSON log trail for its `job_id` shows every
stage with durations across both processes.

## Docs and debt

- Update `docs/PERSISTENCE.md` (API admission limits) and link
  `docs/OPERATIONS.md` from `docs/ARCHITECTURE_V1.md`'s Observability section.
- `TECHNICAL_DEBT.md`: mark resolved "Correlation IDs are stored but not yet
  propagated to logs", "`job.error` can contain absolute filesystem paths" and
  "Engine subprocess output is decoded with the Windows code page"; record any
  new debt found.
