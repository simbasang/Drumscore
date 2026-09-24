# V1-033 Observability and Resource/Security Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correlate every job's logs across API and worker, log stage timing/failure as structured events, bound expensive/untrusted work (source size, request size, active jobs, storage) and keep secrets/absolute paths out of logs and API responses.

**Architecture:** A new stdlib-only `app/observability` package holds a ContextVar-based log context (injected into every `LogRecord` by a record factory), JSON/text formatters with password redaction, error-message sanitization and two pure-ASGI middlewares (request ID/access event, request size limit). The runner and worker bind job context and emit `stage_*`/`job_finished` events; the extractor enforces source limits; the API gains admission checks backed by two new `Store` queries.

**Tech Stack:** Python 3.13, FastAPI/Starlette (pure ASGI middleware), pydantic-settings 2.15 (`SecretStr`, `PositiveInt`), SQLAlchemy 2.0, yt-dlp, pytest (+ `caplog`, testcontainers Postgres for `integration`).

**Spec:** `docs/superpowers/specs/2026-09-24-v1-033-observability-limits-design.md`

## Global Constraints

- Issue #84 (V1-033), branch `v1-033_observability-limits`. Scope is exactly the spec; no Prometheus/metrics endpoint, no tracing, no auth, no frontend changes, no new dependencies.
- Backend tests: pytest, flat `backend/tests/test_*.py`; shared fakes/helpers live in `backend/tests/fakes.py` (not duplicated inline). Postgres-backed tests go through the parametrized `store` fixture or carry `@pytest.mark.integration`.
- Test style: Arrange / Act / Assert separated by blank lines, no comments in tests, names `test_<behaviour>`.
- Verification commands (run from `backend/`): `uv run pytest -m "not integration"` (fast), `uv run pytest` (full, needs Docker). Frontend is untouched, but the final task runs `cd frontend && pnpm test && pnpm lint && pnpm exec tsc --noEmit` to prove no regression.
- Defaults (verbatim from spec): `max_source_duration_seconds=900`, `max_download_bytes=200 MiB`, `max_request_bytes=5 MiB`, `max_active_jobs=20`, `storage_max_bytes=100 GiB`, URL `max_length=2048`, `log_format="json"`, `log_level="INFO"`, sanitized error cap 500 chars (first 200 + `…` + last 299), `Retry-After: 60`.
- HTTP codes: 413 body too large, 422 URL too long, 503 + `Retry-After` too many active jobs, 507 storage full.
- Event names (verbatim): `stage_started`, `stage_finished` (`outcome` `ran`|`cached`), `stage_failed`, `job_finished` (`outcome` `completed`|`failed`|`retry_scheduled`|`abandoned`|`lease_lost`), `http_request`, `project_created`, `job_requeued`.
- Context field names (verbatim): `job_id`, `correlation_id`, `project_id`, `worker`, `request_id`.
- Commit after every task with a conventional message ending in:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MPTyGoXm1P9jBGWyFxL4n7
  ```
- Source timestamps and all timing/notation code are untouched.

## Review Focus

1. An `X-Request-ID` carrying a newline, quotes or 500 characters must be replaced by a generated ID, never echoed into headers/logs (Task 9 test `test_unsafe_request_id_is_replaced`).
2. A job whose project was soft-deleted while still queued must not count against `MAX_ACTIVE_JOBS`, or deleting projects could never free queue capacity (Task 8 test `test_count_active_jobs_ignores_terminal_jobs_and_deleted_projects`).
3. Stage-cache reuse makes several `artifacts` rows share one file; storage accounting must count that file once or the storage cap trips early (Task 8 test `test_live_artifact_bytes_counts_each_key_once_and_skips_pruned`).
4. A source whose metadata has no `duration` (some extractors omit it) must still be processable, bounded only by the byte limit (Task 7 test `test_unknown_duration_is_allowed`).
5. An exception raised inside a nested `log_context` must restore the outer context, or one failed job would leak its `job_id` into the next job's logs (Task 2 test `test_log_context_restores_outer_context_after_exception`).

---

## File Structure

| File | Responsibility |
|---|---|
| Create `backend/app/observability/__init__.py` | package marker (empty) |
| Create `backend/app/observability/logging.py` | `log_context`, `current_context`, `log_event`, record factory, `JsonFormatter`, `TextFormatter`, `configure_logging` |
| Create `backend/app/observability/redaction.py` | `redact`, `sanitize_error_message`, `default_error_roots`, `BACKEND_DIR` |
| Create `backend/app/observability/http.py` | `RequestContextMiddleware`, `RequestSizeLimitMiddleware` |
| Modify `backend/app/config.py` | new settings, `SecretStr`, validators |
| Modify `backend/app/main.py` | `configure_logging`, middlewares, secret URL |
| Modify `backend/app/worker/__main__.py` | `configure_logging` |
| Modify `backend/app/worker/factory.py` | `default_engines(settings)`, secret URL |
| Modify `backend/app/worker/worker.py` | job log context, `job_finished`, monotonic, error roots |
| Modify `backend/app/worker/heartbeat.py` | thread inherits log context |
| Modify `backend/app/pipeline/runner.py` | stage events, outcome return, sanitized errors |
| Modify `backend/app/youtube_audio_extractor.py` | source limits |
| Modify `backend/app/demucs_stem_separator.py`, `backend/app/drumscript_transcriber.py` | UTF-8 decoding |
| Modify `backend/app/persistence/store.py`, `memory.py`, `postgres.py` | `count_active_jobs`, `live_artifact_bytes` |
| Modify `backend/app/api/projects.py`, `backend/app/api/schemas.py` | admission, events, URL max length |
| Create `docs/OPERATIONS.md` | env vars, secrets, limits, logs, events |
| Modify `docs/PERSISTENCE.md`, `docs/ARCHITECTURE_V1.md`, `TECHNICAL_DEBT.md`, `backend/.env.example` | docs/debt |
| Tests | `test_config.py`, new `test_observability_logging.py`, new `test_redaction.py`, new `test_http_middleware.py`, `test_runner.py`, `test_worker.py`, `test_heartbeat.py`, `test_youtube_audio_extractor.py`, `test_demucs_stem_separator.py`, `test_drumscript_transcriber.py`, `test_store_contract.py`, `test_projects_api.py`, `test_main.py`, `test_worker_factory.py`, new `test_operations_doc.py`; helpers in `tests/fakes.py` |

---

### Task 1: Settings — new limits, log settings and secret database URL

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py:22`, `backend/app/api/projects.py:50`, `backend/app/worker/factory.py:28`
- Test: `backend/tests/test_config.py`, `backend/tests/test_main.py`

**Interfaces:**
- Produces: `Settings.database_url: SecretStr`; `Settings.log_level: str`; `Settings.log_format: Literal["json", "text"]`; `Settings.max_source_duration_seconds: PositiveInt`; `Settings.max_download_bytes: PositiveInt`; `Settings.max_request_bytes: PositiveInt`; `Settings.max_active_jobs: PositiveInt`; `Settings.storage_max_bytes: PositiveInt`. Every caller of the URL uses `settings.database_url.get_secret_value()`.

- [ ] **Step 1: Write the failing tests** — in `backend/tests/test_config.py` replace `test_settings_have_documented_defaults` and `test_settings_read_environment_variables` and add the new tests:

```python
def test_settings_have_documented_defaults(monkeypatch):
    for name in ("DATABASE_URL", "STORAGE_ROOT", "WORKER_CONCURRENCY", "LEASE_SECONDS", "LOG_FORMAT", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value() == "postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore"
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
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"
    assert settings.max_source_duration_seconds == 900
    assert settings.max_download_bytes == 200 * 1024**2
    assert settings.max_request_bytes == 5 * 1024**2
    assert settings.max_active_jobs == 20
    assert settings.storage_max_bytes == 100 * 1024**3


def test_settings_read_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("WORKER_CONCURRENCY", "4")
    monkeypatch.setenv("LOG_FORMAT", "text")
    monkeypatch.setenv("MAX_ACTIVE_JOBS", "5")

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value() == "postgresql+psycopg://u:p@db:5432/x"
    assert settings.storage_root == tmp_path
    assert settings.worker_concurrency == 4
    assert settings.log_format == "text"
    assert settings.max_active_jobs == 5


def test_database_password_is_hidden_from_repr():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://u:hunter2@db/x")

    text = repr(settings) + str(settings)

    assert "hunter2" not in text


@pytest.mark.parametrize(
    "field",
    ["max_source_duration_seconds", "max_download_bytes", "max_request_bytes", "max_active_jobs", "storage_max_bytes"],
)
def test_limits_must_be_positive(field):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})


def test_unknown_log_format_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_format="xml")


def test_storage_warning_must_not_exceed_the_storage_limit():
    with pytest.raises(ValidationError, match="STORAGE_WARN_BYTES must not exceed STORAGE_MAX_BYTES"):
        Settings(_env_file=None, storage_warn_bytes=11, storage_max_bytes=10)
```

In `backend/tests/test_main.py` the first test keeps asserting `calls == ["postgresql+psycopg://x"]` (it proves `main` unwraps the secret) — no change needed there.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_config.py tests/test_main.py -v`
Expected: FAIL (`AttributeError: 'str' object has no attribute 'get_secret_value'`, missing fields).

- [ ] **Step 3: Implement** — `backend/app/config.py`:

```python
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import PositiveInt, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or
    backend/.env). docs/OPERATIONS.md documents every value and which ones
    are secret; docs/PERSISTENCE.md explains the queue/storage ones."""

    model_config = SettingsConfigDict(env_file=_BACKEND_DIR / ".env", extra="ignore")

    database_url: SecretStr = SecretStr("postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore")
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
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    max_source_duration_seconds: PositiveInt = 900
    max_download_bytes: PositiveInt = 200 * 1024**2
    max_request_bytes: PositiveInt = 5 * 1024**2
    max_active_jobs: PositiveInt = 20
    storage_max_bytes: PositiveInt = 100 * 1024**3

    @field_validator("storage_root")
    @classmethod
    def _resolve_relative_storage_root(cls, value: Path) -> Path:
        # A relative STORAGE_ROOT means the same directory for the API and
        # the workers whatever directory they were started from.
        return value if value.is_absolute() else _BACKEND_DIR / value

    @model_validator(mode="after")
    def _heartbeat_shorter_than_lease(self) -> "Settings":
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError(
                f"HEARTBEAT_SECONDS must be less than LEASE_SECONDS "
                f"(got {self.heartbeat_seconds} >= {self.lease_seconds}); otherwise the lease expires between heartbeats"
            )
        return self

    @model_validator(mode="after")
    def _warning_below_storage_limit(self) -> "Settings":
        if self.storage_warn_bytes > self.storage_max_bytes:
            raise ValueError(
                f"STORAGE_WARN_BYTES must not exceed STORAGE_MAX_BYTES "
                f"(got {self.storage_warn_bytes} > {self.storage_max_bytes})"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Update the three callers:
- `backend/app/main.py`: `upgrade_to_head(settings.database_url.get_secret_value())`
- `backend/app/api/projects.py` `get_store`: `return create_postgres_store(get_settings().database_url.get_secret_value())`
- `backend/app/worker/factory.py` `build_worker`: `store=create_postgres_store(settings.database_url.get_secret_value()),`

Then `grep -rn "database_url" backend/app` must show no other bare use.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_config.py tests/test_main.py tests/test_worker_factory.py -v`
Expected: PASS.

- [ ] **Step 5: Run fast suite and commit**

Run: `uv run pytest -m "not integration"` → all pass.

```bash
git add backend/app/config.py backend/app/main.py backend/app/api/projects.py backend/app/worker/factory.py backend/tests/test_config.py
git commit -m "feat(config): add limit and log settings; keep DATABASE_URL secret"
```

---

### Task 2: Structured logging module with context and redaction

**Files:**
- Create: `backend/app/observability/__init__.py` (empty), `backend/app/observability/logging.py`, `backend/app/observability/redaction.py` (only `redact` in this task)
- Modify: `backend/app/main.py`, `backend/app/worker/__main__.py`
- Modify: `backend/tests/fakes.py` (add `logged_events`)
- Test: `backend/tests/test_observability_logging.py`, `backend/tests/test_redaction.py`

**Interfaces:**
- Consumes: `Settings.log_level`, `Settings.log_format` (Task 1).
- Produces:
  - `app.observability.logging.log_context(**fields: object) -> ContextManager[None]`
  - `app.observability.logging.current_context() -> dict[str, str]`
  - `app.observability.logging.log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: object) -> None` — record has `record.getMessage() == event` and `record.fields == fields`
  - every `LogRecord` has `record.context: dict[str, str]`
  - `JsonFormatter`, `TextFormatter` (`logging.Formatter` subclasses)
  - `configure_logging(level: str = "INFO", fmt: Literal["json", "text"] = "json", stream: TextIO | None = None) -> None`
  - `app.observability.redaction.redact(text: str) -> str`
  - `tests.fakes.logged_events(caplog, event: str) -> list[dict]` — each dict is `{**record.context, **record.fields}`

- [ ] **Step 1: Write failing tests** — `backend/tests/test_redaction.py`:

```python
from app.observability.redaction import redact


def test_redact_hides_the_password_in_a_database_url():
    text = "could not connect to postgresql+psycopg://drumscore:hunter2@db:5432/drumscore"

    result = redact(text)

    assert result == "could not connect to postgresql+psycopg://drumscore:***@db:5432/drumscore"


def test_redact_hides_a_libpq_password_keyword():
    result = redact("host=db user=u password=hunter2 dbname=x")

    assert result == "host=db user=u password=*** dbname=x"


def test_redact_leaves_urls_without_credentials_alone():
    text = "https://youtu.be/dQw4w9WgXcQ and http://localhost:8000/api"

    assert redact(text) == text
```

`backend/tests/test_observability_logging.py`:

```python
import io
import json
import logging
import threading

import pytest

from app.observability.logging import (
    JsonFormatter,
    TextFormatter,
    configure_logging,
    current_context,
    log_context,
    log_event,
)
from tests.fakes import logged_events

logger = logging.getLogger("tests.observability")


def format_one(formatter, emit):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        emit()
    finally:
        logger.removeHandler(handler)
    return stream.getvalue().strip()


def test_log_context_binds_fields_and_restores_on_exit():
    with log_context(job_id="j1"):
        inside = current_context()

    assert inside == {"job_id": "j1"}
    assert current_context() == {}


def test_nested_log_context_merges_and_inner_values_win():
    with log_context(job_id="j1", worker="w"):
        with log_context(job_id="j2", stage="extract"):
            inner = current_context()
        outer = current_context()

    assert inner == {"job_id": "j2", "worker": "w", "stage": "extract"}
    assert outer == {"job_id": "j1", "worker": "w"}


def test_log_context_restores_outer_context_after_exception():
    with log_context(job_id="outer"):
        with pytest.raises(RuntimeError):
            with log_context(job_id="inner"):
                raise RuntimeError("boom")
        after = current_context()

    assert after == {"job_id": "outer"}


def test_every_record_carries_the_bound_context(caplog):
    caplog.set_level(logging.INFO)

    with log_context(job_id="j1", correlation_id="c1"):
        logger.info("hello")

    assert caplog.records[-1].context == {"job_id": "j1", "correlation_id": "c1"}


def test_plain_threads_do_not_inherit_the_context(caplog):
    caplog.set_level(logging.INFO)
    thread = threading.Thread(target=lambda: logger.info("from thread"))

    with log_context(job_id="j1"):
        thread.start()
        thread.join()

    assert caplog.records[-1].context == {}


def test_log_event_records_the_event_name_and_fields(caplog):
    caplog.set_level(logging.INFO)

    with log_context(job_id="j1"):
        log_event(logger, "stage_finished", stage="extract", duration_ms=12)

    assert logged_events(caplog, "stage_finished") == [{"job_id": "j1", "stage": "extract", "duration_ms": 12}]


def test_json_formatter_writes_one_object_with_context_and_fields():
    def emit():
        with log_context(job_id="j1"):
            log_event(logger, "stage_finished", stage="extract", duration_ms=12)

    line = format_one(JsonFormatter(), emit)

    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "tests.observability"
    assert payload["message"] == "stage_finished"
    assert payload["job_id"] == "j1"
    assert payload["stage"] == "extract"
    assert payload["duration_ms"] == 12
    assert payload["ts"].endswith("+00:00")
    assert "\n" not in line


def test_json_formatter_includes_the_traceback_and_redacts_it():
    def emit():
        try:
            raise ConnectionError("postgresql://u:hunter2@db/x refused")
        except ConnectionError:
            logger.exception("db down")

    line = format_one(JsonFormatter(), emit)

    payload = json.loads(line)
    assert "ConnectionError" in payload["exc"]
    assert "hunter2" not in line


def test_json_formatter_stringifies_values_json_cannot_encode():
    line = format_one(JsonFormatter(), lambda: log_event(logger, "odd", value=object))

    assert json.loads(line)["value"] == "<class 'object'>"


def test_text_formatter_appends_context_and_fields_as_key_value_pairs():
    def emit():
        with log_context(job_id="j1"):
            log_event(logger, "stage_finished", stage="extract")

    line = format_one(TextFormatter(), emit)

    assert line.endswith("INFO tests.observability stage_finished job_id=j1 stage=extract")


def test_text_formatter_redacts_passwords():
    line = format_one(TextFormatter(), lambda: logger.info("url postgresql://u:hunter2@db/x"))

    assert "hunter2" not in line
    assert "postgresql://u:***@db/x" in line


def test_configure_logging_installs_one_root_handler_and_routes_uvicorn_logs():
    stream = io.StringIO()
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging("INFO", "json", stream=stream)
        configure_logging("INFO", "json", stream=stream)
        logging.getLogger("uvicorn.error").info("server started")

        ours = [h for h in root.handlers if h not in before]
        assert len(ours) == 1
        assert json.loads(stream.getvalue().strip().splitlines()[-1])["message"] == "server started"
        assert logging.getLogger("uvicorn").propagate is True
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
```

Add to `backend/tests/fakes.py`:

```python
def logged_events(caplog, event: str) -> list[dict]:
    """Structured events (app.observability.logging.log_event) named
    `event`, as {**bound context, **event fields}, in log order."""
    return [
        {**getattr(record, "context", {}), **getattr(record, "fields", {})}
        for record in caplog.records
        if record.getMessage() == event and hasattr(record, "fields")
    ]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_redaction.py tests/test_observability_logging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.observability'`.

- [ ] **Step 3: Implement** — `backend/app/observability/__init__.py`: empty file.

`backend/app/observability/redaction.py`:

```python
"""Keeping secrets and host details out of logs and API responses."""

import re

_URL_PASSWORD = re.compile(r"(?P<prefix>[A-Za-z][A-Za-z0-9+.\-]*://[^:/@\s]*:)[^@\s/]+@")
_KEYWORD_PASSWORD = re.compile(r"(?i)(?P<prefix>\bpassword\s*=\s*)[^\s'\"&;]+")


def redact(text: str) -> str:
    """Replaces the password in `scheme://user:password@host` URLs and in
    libpq-style `password=...` pairs with `***`."""
    text = _URL_PASSWORD.sub(r"\g<prefix>***@", text)
    return _KEYWORD_PASSWORD.sub(r"\g<prefix>***", text)
```

`backend/app/observability/logging.py`:

```python
"""Structured logging. A ContextVar carries per-job / per-request fields
(job_id, correlation_id, request_id, ...) that a LogRecord factory copies
onto every record, so any logger anywhere inherits them. Output is one
JSON object (or one text line) per record on stdout, with passwords
redacted. See docs/OPERATIONS.md for the field and event catalogue."""

import contextvars
import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Literal, TextIO

from app.observability.redaction import redact

_context: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar("drumscore_log_context", default={})

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


@contextmanager
def log_context(**fields: object) -> Iterator[None]:
    """Binds `fields` to every log record created inside the block
    (including in threads started with a copy of this context)."""
    token = _context.set({**_context.get(), **{key: str(value) for key, value in fields.items()}})
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> dict[str, str]:
    return dict(_context.get())


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: object) -> None:
    """Logs a named structured event; `fields` land as top-level JSON keys."""
    logger.log(level, event, extra={"fields": fields})


def _install_record_factory() -> None:
    previous = logging.getLogRecordFactory()
    if getattr(previous, "drumscore_context", False):
        return

    def factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.context = dict(_context.get())
        return record

    factory.drumscore_context = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


_install_record_factory()


def _extras(record: logging.LogRecord) -> dict[str, object]:
    return {**getattr(record, "context", {}), **getattr(record, "fields", {})}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in _extras(record).items():
            payload.setdefault(key, value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, default=str, ensure_ascii=False))


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = _extras(record)
        if extras:
            first, newline, rest = line.partition("\n")
            pairs = " ".join(f"{key}={value}" for key, value in extras.items())
            line = f"{first} {pairs}{newline}{rest}"
        return redact(line)


def configure_logging(level: str = "INFO", fmt: Literal["json", "text"] = "json", stream: TextIO | None = None) -> None:
    """Installs (or replaces) Drumscore's single stdout handler on the root
    logger and routes uvicorn's loggers through it. Safe to call twice."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "drumscore", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.drumscore = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
```

Wire it in:
- `backend/app/main.py`: remove `import logging` and the `logging.basicConfig(...)` block; add
  ```python
  from app.observability.logging import configure_logging

  _settings = get_settings()
  configure_logging(_settings.log_level, _settings.log_format)
  ```
  directly after the imports.
- `backend/app/worker/__main__.py` `run_worker_process`: replace the `logging.basicConfig(...)` line with
  ```python
      settings = get_settings()
      configure_logging(settings.log_level, settings.log_format)
      worker = build_worker(settings)
  ```
  (import `configure_logging` from `app.observability.logging`; drop `import logging`).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_redaction.py tests/test_observability_logging.py tests/test_main.py -v`
Expected: PASS.

- [ ] **Step 5: Fast suite + commit**

Run: `uv run pytest -m "not integration"` → all pass.

```bash
git add backend/app/observability backend/app/main.py backend/app/worker/__main__.py backend/tests/fakes.py backend/tests/test_redaction.py backend/tests/test_observability_logging.py
git commit -m "feat(observability): structured JSON/text logging with bound context and redaction"
```

---

### Task 3: Sanitized job errors

**Files:**
- Modify: `backend/app/observability/redaction.py`
- Modify: `backend/app/pipeline/runner.py` (`JobContext`, `_handle_failure`)
- Modify: `backend/app/worker/worker.py` (pass roots)
- Test: `backend/tests/test_redaction.py`, `backend/tests/test_runner.py`

**Interfaces:**
- Consumes: `redact` (Task 2).
- Produces:
  - `app.observability.redaction.BACKEND_DIR: Path`
  - `default_error_roots(storage_root: Path) -> tuple[tuple[Path, str], ...]` → `((storage_root, "<storage>"), (Path(tempfile.gettempdir()), "<tmp>"), (BACKEND_DIR, "<app>"))`
  - `sanitize_error_message(message: str, roots: Sequence[tuple[Path, str]] = ()) -> str`
  - `JobContext.error_roots: tuple[tuple[Path, str], ...] = ()` (new last field with default)

- [ ] **Step 1: Write failing tests** — append to `backend/tests/test_redaction.py`:

```python
from pathlib import Path

from app.observability.redaction import BACKEND_DIR, default_error_roots, sanitize_error_message


def test_sanitize_replaces_known_roots_longest_first(tmp_path):
    storage = tmp_path / "app" / "data"
    roots = ((storage, "<storage>"), (tmp_path / "app", "<app>"))
    message = f"Demucs failed: cannot open {storage / 'projects' / 'p' / 'source.wav'}"

    result = sanitize_error_message(message, roots)

    assert str(tmp_path) not in result
    assert result.startswith("Demucs failed: cannot open <storage>")
    assert "source.wav" in result


def test_sanitize_matches_roots_written_with_forward_slashes(tmp_path):
    roots = ((tmp_path, "<storage>"),)

    result = sanitize_error_message(f"missing {tmp_path.as_posix()}/x.wav", roots)

    assert result == "missing <storage>/x.wav"


def test_sanitize_replaces_unknown_absolute_paths():
    message = r"No such file: C:\Users\someone\secret.txt and /home/someone/.cache/model.th"

    result = sanitize_error_message(message)

    assert result == "No such file: <path> and <path>"


def test_sanitize_keeps_urls_and_ratios():
    message = "Failed to download https://youtu.be/dQw4w9WgXcQ at 3/4 speed"

    assert sanitize_error_message(message) == message


def test_sanitize_redacts_passwords():
    result = sanitize_error_message("postgresql://u:hunter2@db/x refused")

    assert "hunter2" not in result


def test_sanitize_caps_long_messages_keeping_head_and_tail():
    message = "H" * 300 + "M" * 1000 + "T" * 300

    result = sanitize_error_message(message)

    assert len(result) == 500
    assert result.startswith("H" * 200 + "…")
    assert result.endswith("T" * 299)


def test_default_error_roots_cover_storage_temp_and_backend(tmp_path):
    roots = dict((placeholder, root) for root, placeholder in default_error_roots(tmp_path))

    assert roots["<storage>"] == tmp_path
    assert roots["<app>"] == BACKEND_DIR
    assert roots["<tmp>"].is_dir()
    assert (BACKEND_DIR / "app" / "config.py").is_file()
```

Append to `backend/tests/test_runner.py` (reuse its `new_project`, fixtures; `JobContext` needs `error_roots`, so this test builds its own context):

```python
def test_stored_job_error_is_sanitized_but_the_log_keeps_the_raw_text(store, storage, clock, caplog, tmp_path):
    new_project(store, clock)
    leaked = tmp_path / "secret" / "source.wav"
    engines = make_engines(separator=FakeSeparator(error=StemSeparationError(f"Demucs failed: cannot read {leaked}")))
    job = store.claim_next_job(OWNER, 300, clock())
    ctx = JobContext(
        store=store, storage=storage, engines=engines, owner=OWNER, retry_base_seconds=30, clock=clock,
        error_roots=((tmp_path, "<storage>"),),
    )

    with caplog.at_level(logging.INFO, logger="app.pipeline.runner"):
        process_job(job, ctx)

    stored = store.get_job(job.id).error
    assert stored.startswith("Demucs failed: cannot read <storage>")
    assert stored.endswith("source.wav")
    assert str(tmp_path) not in stored
    assert str(leaked) in caplog.text
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_redaction.py tests/test_runner.py -v`
Expected: FAIL (`ImportError: cannot import name 'sanitize_error_message'`; `JobContext` has no `error_roots`).

- [ ] **Step 3: Implement** — append to `backend/app/observability/redaction.py` (add `import tempfile`, `from collections.abc import Sequence`, `from pathlib import Path` at the top):

```python
BACKEND_DIR = Path(__file__).resolve().parents[2]

_MAX_ERROR_CHARS = 500
_HEAD_CHARS = 200
_WINDOWS_PATH = re.compile(r"(?<!\w)[A-Za-z]:[\\/][^\s'\"<>|*?]*")
_POSIX_PATH = re.compile(r"(?<![\w/:.>~\-])/(?:[^\s'\"/<>]+/)*[^\s'\"/<>]+")


def default_error_roots(storage_root: Path) -> tuple[tuple[Path, str], ...]:
    return ((storage_root, "<storage>"), (Path(tempfile.gettempdir()), "<tmp>"), (BACKEND_DIR, "<app>"))


def sanitize_error_message(message: str, roots: Sequence[tuple[Path, str]] = ()) -> str:
    """Makes an engine/OS error safe to store and return from the API:
    known directories become placeholders, any other absolute path becomes
    `<path>`, passwords are redacted and the text is capped at 500
    characters (head and tail kept, since an engine's stderr ends with the
    actual error)."""
    text = redact(message)
    for root, placeholder in sorted(roots, key=lambda item: len(str(item[0])), reverse=True):
        for spelling in {str(root), root.as_posix()}:
            text = re.sub(re.escape(spelling), placeholder, text, flags=re.IGNORECASE)
    text = _WINDOWS_PATH.sub("<path>", text)
    text = _POSIX_PATH.sub("<path>", text)
    if len(text) > _MAX_ERROR_CHARS:
        tail = _MAX_ERROR_CHARS - _HEAD_CHARS - 1
        text = f"{text[:_HEAD_CHARS]}…{text[-tail:]}"
    return text
```

(The placeholder replaces only the root prefix, so the remainder keeps the OS separator — that is why the runner test asserts prefix/suffix rather than the whole string.)

In `backend/app/pipeline/runner.py`:
- import `from app.observability.redaction import sanitize_error_message`
- add to `JobContext` after `should_stop`: `error_roots: tuple[tuple[Path, str], ...] = ()`
- `_handle_failure`:

```python
def _handle_failure(job: Job, ctx: JobContext, error: Exception) -> None:
    now = ctx.clock()
    if is_permanent(error):
        logger.info("Job %s failed permanently: %s", job.id, error)
        ctx.store.fail_job(job.id, ctx.owner, sanitize_error_message(str(error), ctx.error_roots), now)
        return

    message = sanitize_error_message(f"Unexpected error: {error}", ctx.error_roots)
    logger.exception("Job %s crashed on attempt %d/%d", job.id, job.attempts, job.max_attempts)
    if job.attempts >= job.max_attempts:
        ctx.store.fail_job(job.id, ctx.owner, message, now)
    else:
        delay = backoff_seconds(job.attempts, ctx.retry_base_seconds)
        ctx.store.schedule_retry(job.id, ctx.owner, message, now + timedelta(seconds=delay), now)
```

In `backend/app/worker/worker.py`: import `default_error_roots`; in `__init__` set `self._error_roots = default_error_roots(settings.storage_root)`; pass `error_roots=self._error_roots` when building `JobContext` in `run_once`. Add a worker test to `backend/tests/test_worker.py`:

```python
def test_worker_stores_errors_without_its_storage_root(parts):
    store, storage, clock = parts
    _, job = enqueue(store, clock)
    failing = FakeSeparator(error=StemSeparationError(f"Demucs failed: {storage.root / 'x.wav'}"))
    worker = make_worker(store, storage, clock, make_engines(separator=failing), storage_root=storage.root)

    worker.run_once()

    assert str(storage.root) not in store.get_job(job.id).error
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_redaction.py tests/test_runner.py tests/test_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Fast suite + commit**

```bash
git add backend/app/observability/redaction.py backend/app/pipeline/runner.py backend/app/worker/worker.py backend/tests/test_redaction.py backend/tests/test_runner.py backend/tests/test_worker.py
git commit -m "fix(pipeline): sanitize stored job errors (no absolute paths or passwords)"
```

---

### Task 4: Decode engine subprocess output as UTF-8

**Files:**
- Modify: `backend/app/demucs_stem_separator.py`, `backend/app/drumscript_transcriber.py`
- Test: `backend/tests/test_demucs_stem_separator.py`, `backend/tests/test_drumscript_transcriber.py`

**Interfaces:** none new; both `subprocess.run` calls gain `encoding="utf-8", errors="replace"`.

- [ ] **Step 1: Write failing tests.** In `test_demucs_stem_separator.py` update the `assert_called_once_with(...)` in `test_separate_invokes_demucs_with_two_stems_drums_flag` to include `encoding="utf-8", errors="replace",` after `text=True,`. Make the same change in the DrumScript test that asserts the full `subprocess.run` kwargs (if it asserts only `command`, add `assert mock_run.call_args.kwargs["encoding"] == "utf-8"` and `assert mock_run.call_args.kwargs["errors"] == "replace"` to `test_transcribe_invokes_runner_script_with_audio_and_output_paths`). Add real-subprocess regression tests:

`backend/tests/test_demucs_stem_separator.py`:

```python
_FAILING_ENGINE = "import sys; sys.stderr.buffer.write(b'boom \\x8d\\x81 end'); sys.exit(1)"


def test_failure_message_survives_undecodable_stderr_bytes(tmp_path):
    audio_path = tmp_path / "source.wav"
    audio_path.write_bytes(b"fake audio")
    real_run = subprocess.run

    def run_failing_engine(command, **kwargs):
        return real_run([sys.executable, "-c", _FAILING_ENGINE], **kwargs)

    with patch("app.demucs_stem_separator.subprocess.run", side_effect=run_failing_engine):
        with pytest.raises(StemSeparationError, match="Demucs failed: boom .* end"):
            DemucsStemSeparator().separate(audio_path, tmp_path / "out")
```

`backend/tests/test_drumscript_transcriber.py` (uses the existing `fake_runner_python` fixture):

```python
_FAILING_ENGINE = "import sys; sys.stderr.buffer.write(b'boom \\x8d\\x81 end'); sys.exit(1)"


def test_failure_message_survives_undecodable_stderr_bytes(tmp_path, fake_runner_python):
    audio_path = tmp_path / "drums.wav"
    audio_path.write_bytes(b"fake audio")
    real_run = subprocess.run

    def run_failing_engine(command, **kwargs):
        return real_run([sys.executable, "-c", _FAILING_ENGINE], **kwargs)

    with patch("app.drumscript_transcriber.subprocess.run", side_effect=run_failing_engine):
        with pytest.raises(TranscriptionError, match="Drum transcription failed: boom .* end"):
            DrumScriptTranscriber().transcribe(audio_path)
```

(Add `import subprocess`, `import sys` to the DrumScript test imports if missing.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_demucs_stem_separator.py tests/test_drumscript_transcriber.py -v`
Expected: FAIL — kwargs mismatch; on Windows the regression test fails with `AttributeError: 'NoneType' object has no attribute 'strip'` (cp1252 cannot decode `0x8d`/`0x81`). On a UTF-8 locale the regression test fails because the invalid UTF-8 bytes raise in the reader thread the same way.

- [ ] **Step 3: Implement** — in both files add to the `subprocess.run(...)` call, right after `text=True,`:

```python
                encoding="utf-8",
                errors="replace",
```

- [ ] **Step 4: Run to verify pass** — same command, expected PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/demucs_stem_separator.py backend/app/drumscript_transcriber.py backend/tests/test_demucs_stem_separator.py backend/tests/test_drumscript_transcriber.py
git commit -m "fix(engines): decode engine output as UTF-8 so failures keep their stderr"
```

---

### Task 5: Stage events and job outcome in the runner

**Files:**
- Modify: `backend/app/pipeline/runner.py`
- Modify: `backend/tests/fakes.py` (add `FakeMonotonic`)
- Test: `backend/tests/test_runner.py`

**Interfaces:**
- Consumes: `log_event` (Task 2), `JobContext.error_roots` (Task 3).
- Produces:
  - `JobContext.monotonic: Callable[[], float] = time.monotonic` (new last field)
  - `JobOutcome = Literal["completed", "failed", "retry_scheduled"]` in `app.pipeline.runner`
  - `process_job(job, ctx) -> JobOutcome`
  - events `stage_started {stage}`, `stage_finished {stage, duration_ms:int, outcome}`, `stage_failed {stage, duration_ms:int, error_type:str, permanent:bool}` (level WARNING) from logger `app.pipeline.runner`; stages `extract|separate|transcribe|map_tempo`
  - `tests.fakes.FakeMonotonic` with `__call__() -> float` and `advance(seconds: float)`

- [ ] **Step 1: Write failing tests.** Add to `backend/tests/fakes.py`:

```python
class FakeMonotonic:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
```

In `backend/tests/test_runner.py`: extend `run(...)` with a `monotonic=None` parameter passed as `monotonic=monotonic or FakeMonotonic()` into `JobContext`, and make it return `store.get_job(job.id)` as before but also expose the outcome via a new helper:

```python
def run_with_outcome(store, storage, clock, engines, monotonic=None):
    job = store.claim_next_job(OWNER, 300, clock())
    ctx = JobContext(
        store=store, storage=storage, engines=engines, owner=OWNER, retry_base_seconds=30, clock=clock,
        monotonic=monotonic or FakeMonotonic(),
    )
    return process_job(job, ctx), store.get_job(job.id)
```

Replace `test_stages_that_run_are_logged_and_reused_stages_are_not` with:

```python
def test_each_stage_logs_start_and_finish_with_its_duration(store, storage, clock, caplog):
    monotonic = FakeMonotonic()
    engines = make_engines(separator=FakeSeparator(on_call=lambda: monotonic.advance(2.5)))
    new_project(store, clock)

    with caplog.at_level(logging.INFO, logger="app.pipeline.runner"):
        outcome, _ = run_with_outcome(store, storage, clock, engines, monotonic)

    assert outcome == "completed"
    assert [e["stage"] for e in logged_events(caplog, "stage_started")] == ["extract", "separate", "transcribe", "map_tempo"]
    finished = {e["stage"]: e for e in logged_events(caplog, "stage_finished")}
    assert finished["separate"] == {"stage": "separate", "duration_ms": 2500, "outcome": "ran"}
    assert finished["extract"]["duration_ms"] == 0
    assert set(finished) == {"extract", "separate", "transcribe", "map_tempo"}


def test_reused_stages_log_a_cached_finish_without_a_start(store, storage, clock, caplog):
    engines = make_engines()
    new_project(store, clock)
    run(store, storage, clock, engines)
    new_project(store, clock)

    with caplog.at_level(logging.INFO, logger="app.pipeline.runner"):
        run(store, storage, clock, engines)

    assert [e["stage"] for e in logged_events(caplog, "stage_started")] == ["map_tempo"]
    cached = [e for e in logged_events(caplog, "stage_finished") if e["outcome"] == "cached"]
    assert [e["stage"] for e in cached] == ["separate", "transcribe"]


def test_failing_stage_logs_stage_failed_and_the_job_fails(store, storage, clock, caplog):
    monotonic = FakeMonotonic()
    error = StemSeparationError("Demucs failed: bad input")
    engines = make_engines(separator=FakeSeparator(error=error, on_call=lambda: monotonic.advance(1)))
    new_project(store, clock)

    with caplog.at_level(logging.INFO, logger="app.pipeline.runner"):
        outcome, job = run_with_outcome(store, storage, clock, engines, monotonic)

    assert outcome == "failed"
    assert job.status == JobStatus.FAILED
    assert logged_events(caplog, "stage_failed") == [
        {"stage": "separate", "duration_ms": 1000, "error_type": "StemSeparationError", "permanent": True}
    ]
    assert [e["stage"] for e in logged_events(caplog, "stage_finished")] == ["extract"]


def test_transient_failure_reports_retry_scheduled(store, storage, clock, caplog):
    engines = make_engines(separator=FakeSeparator(error=OSError("disk hiccup")))
    new_project(store, clock)

    with caplog.at_level(logging.INFO, logger="app.pipeline.runner"):
        outcome, job = run_with_outcome(store, storage, clock, engines)

    assert outcome == "retry_scheduled"
    assert logged_events(caplog, "stage_failed")[0]["permanent"] is False


def test_deleted_project_reports_failed(store, storage, clock):
    project, _ = new_project(store, clock)
    store.soft_delete_project(project.id, clock())

    outcome, job = run_with_outcome(store, storage, clock, make_engines())

    assert outcome == "failed"
    assert job.error == "Project was deleted"
```

Import `FakeMonotonic` and `logged_events` from `tests.fakes`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL (`JobContext.__init__() got an unexpected keyword argument 'monotonic'`).

- [ ] **Step 3: Implement** in `backend/app/pipeline/runner.py`:

Imports: add `import time`, `from collections.abc import Callable, Iterator`, `from contextlib import contextmanager`, `from typing import Literal`, `from app.observability.logging import log_event`.

```python
JobOutcome = Literal["completed", "failed", "retry_scheduled"]
```

`JobContext` gets, after `error_roots`: `monotonic: Callable[[], float] = time.monotonic`.

```python
def process_job(job: Job, ctx: JobContext) -> JobOutcome:
    """... (keep existing docstring) ... Returns how the attempt ended;
    abandonment and lease loss are raised instead."""
    project = ctx.store.get_project(job.project_id)
    if project is None or project.deleted_at is not None:
        ctx.store.fail_job(job.id, ctx.owner, "Project was deleted", ctx.clock())
        return "failed"

    try:
        _run_stages(job, project, ctx)
    except (JobAbandoned, LeaseLostError):
        raise
    except Exception as error:  # noqa: BLE001 - every failure must end in fail, retry or abandon
        if ctx.should_stop():
            logger.info("Job %s: stage ended with %r after a stop request; abandoning", job.id, error)
            raise JobAbandoned(job.id) from error
        return _handle_failure(job, ctx, error)
    return "completed"


def _handle_failure(job: Job, ctx: JobContext, error: Exception) -> JobOutcome:
    now = ctx.clock()
    if is_permanent(error):
        logger.info("Job %s failed permanently: %s", job.id, error)
        ctx.store.fail_job(job.id, ctx.owner, sanitize_error_message(str(error), ctx.error_roots), now)
        return "failed"

    message = sanitize_error_message(f"Unexpected error: {error}", ctx.error_roots)
    logger.exception("Job %s crashed on attempt %d/%d", job.id, job.attempts, job.max_attempts)
    if job.attempts >= job.max_attempts:
        ctx.store.fail_job(job.id, ctx.owner, message, now)
        return "failed"
    delay = backoff_seconds(job.attempts, ctx.retry_base_seconds)
    ctx.store.schedule_retry(job.id, ctx.owner, message, now + timedelta(seconds=delay), now)
    return "retry_scheduled"


def _elapsed_ms(started: float, ctx: JobContext) -> int:
    return round((ctx.monotonic() - started) * 1000)


@contextmanager
def _timed_stage(stage: str, ctx: JobContext) -> Iterator[None]:
    started = ctx.monotonic()
    log_event(logger, "stage_started", stage=stage)
    try:
        yield
    except LeaseLostError:
        raise
    except Exception as error:
        log_event(
            logger, "stage_failed", logging.WARNING,
            stage=stage, duration_ms=_elapsed_ms(started, ctx),
            error_type=type(error).__name__, permanent=is_permanent(error),
        )
        raise
    log_event(logger, "stage_finished", stage=stage, duration_ms=_elapsed_ms(started, ctx), outcome="ran")
```

`_obtain` body becomes (drop the two old `logger.info` lines):

```python
    cached = _usable_cache_entry(stage, project, ctx)
    if cached is not None:
        started = ctx.monotonic()
        created = ctx.store.commit_stage(job.id, ctx.owner, done, cached.artifacts, None, ctx.clock())
        log_event(logger, "stage_finished", stage=stage.value, duration_ms=_elapsed_ms(started, ctx), outcome="cached")
        return {artifact.kind: artifact for artifact in created}

    with _timed_stage(stage.value, ctx):
        ctx.store.set_job_status(job.id, ctx.owner, running, ctx.clock())
        with ctx.storage.staging_dir() as staging:
            descriptors = tuple(_store_output(job, kind, path, ctx) for kind, path in produce(staging))
        entry = CacheEntry(source_key=project.source_key, stage=stage, pipeline_version=PIPELINE_VERSION, artifacts=descriptors)
        created = ctx.store.commit_stage(job.id, ctx.owner, done, descriptors, entry, ctx.clock())
    return {artifact.kind: artifact for artifact in created}
```

`_map_tempo_and_complete`: wrap its whole body in `with _timed_stage("map_tempo", ctx):`.

Also update `backend/tests/test_projects_api.py` `Harness.process_next` only if it breaks (its positional `JobContext(...)` call stays valid because new fields have defaults).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_runner.py tests/test_projects_api.py -m "not integration" -v`
Expected: PASS.

- [ ] **Step 5: Fast suite + commit**

```bash
git add backend/app/pipeline/runner.py backend/tests/fakes.py backend/tests/test_runner.py
git commit -m "feat(pipeline): log stage start/finish/failure with durations; return job outcome"
```

---

### Task 6: Worker job context, job_finished event and heartbeat context

**Files:**
- Modify: `backend/app/worker/worker.py`, `backend/app/worker/heartbeat.py`
- Test: `backend/tests/test_worker.py`, `backend/tests/test_heartbeat.py`

**Interfaces:**
- Consumes: `log_context`, `log_event` (Task 2); `process_job -> JobOutcome`, `JobContext.monotonic` (Task 5); `default_error_roots` (Task 3).
- Produces: `Worker(..., monotonic: Callable[[], float] = time.monotonic)`; event `job_finished {outcome, duration_ms:int, attempt:int}` from logger `app.worker.worker`; every record logged while a job runs (runner, worker, heartbeat thread) carries `job_id`, `correlation_id`, `project_id`, `worker`.

- [ ] **Step 1: Write failing tests** — `backend/tests/test_worker.py` (extend `make_worker` with `monotonic=None` → `monotonic=monotonic or FakeMonotonic()`; import `FakeMonotonic`, `logged_events`):

```python
def test_job_logs_carry_job_and_correlation_ids(parts, caplog):
    store, storage, clock = parts
    project, job = enqueue(store, clock)

    with caplog.at_level(logging.INFO):
        make_worker(store, storage, clock).run_once()

    stage_events = logged_events(caplog, "stage_finished")
    assert stage_events
    for event in stage_events:
        assert event["job_id"] == job.id
        assert event["correlation_id"] == job.correlation_id
        assert event["project_id"] == project.id
        assert event["worker"] == "w1"


def test_completed_job_logs_job_finished_with_duration(parts, caplog):
    store, storage, clock = parts
    monotonic = FakeMonotonic()
    _, job = enqueue(store, clock)
    engines = make_engines(separator=FakeSeparator(on_call=lambda: monotonic.advance(3)))

    with caplog.at_level(logging.INFO):
        make_worker(store, storage, clock, engines, monotonic=monotonic).run_once()

    assert logged_events(caplog, "job_finished") == [
        {"job_id": job.id, "correlation_id": job.correlation_id, "project_id": job.project_id,
         "worker": "w1", "outcome": "completed", "duration_ms": 3000, "attempt": 1}
    ]


def test_failed_job_logs_job_finished_failed(parts, caplog):
    store, storage, clock = parts
    enqueue(store, clock)
    engines = make_engines(separator=FakeSeparator(error=StemSeparationError("bad")))

    with caplog.at_level(logging.INFO):
        make_worker(store, storage, clock, engines).run_once()

    assert logged_events(caplog, "job_finished")[0]["outcome"] == "failed"


def test_abandoned_job_logs_job_finished_abandoned(parts, caplog):
    store, storage, clock = parts
    enqueue(store, clock)
    worker = make_worker(store, storage, clock)
    engines = make_engines(extractor=FakeExtractor(on_call=worker.stop))
    worker.engines = engines

    with caplog.at_level(logging.INFO):
        worker.run_once()

    assert logged_events(caplog, "job_finished")[0]["outcome"] == "abandoned"


def test_context_is_cleared_after_the_job(parts, caplog):
    store, storage, clock = parts
    enqueue(store, clock)
    worker = make_worker(store, storage, clock)
    worker.run_once()

    with caplog.at_level(logging.INFO):
        logging.getLogger("tests").info("after")

    assert caplog.records[-1].context == {}
```

Add a `lease_lost` outcome test modelled on the existing `test_lost_lease_is_logged_not_raised` (same arrangement), asserting `logged_events(caplog, "job_finished")[0]["outcome"] == "lease_lost"`.

`backend/tests/test_heartbeat.py`:

```python
import logging

from app.observability.logging import log_context


def test_heartbeat_thread_logs_with_the_callers_context(caplog):
    store, clock = InMemoryStore(), FakeClock()
    job = claimed_job(store, clock)
    clock.advance(301)
    store.claim_next_job("thief", 300, clock())

    with caplog.at_level(logging.WARNING, logger="app.worker.heartbeat"):
        with log_context(job_id=job.id):
            with LeaseHeartbeat(store, job.id, "w", 300, 0.01, clock=clock) as heartbeat:
                wait_for(lambda: heartbeat.lost)

    assert caplog.records[-1].context == {"job_id": job.id}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_worker.py tests/test_heartbeat.py -v`
Expected: FAIL (`Worker.__init__() got an unexpected keyword argument 'monotonic'`; heartbeat record context `{}`).

- [ ] **Step 3: Implement.** `backend/app/worker/heartbeat.py`: add `import contextvars`; in `__init__` replace the thread construction with `self._thread: threading.Thread | None = None`; `__enter__`:

```python
    def __enter__(self) -> "LeaseHeartbeat":
        # Run the thread inside a copy of the caller's context so its log
        # records carry the job's log context (job_id, correlation_id, ...).
        context = contextvars.copy_context()
        self._thread = threading.Thread(
            target=context.run, args=(self._run,), daemon=True, name=f"heartbeat-{self._job_id}"
        )
        self._thread.start()
        return self
```

`__exit__`: `self._stop.set()` then `if self._thread is not None: self._thread.join()`.

`backend/app/worker/worker.py`: add `import time`; imports `from app.observability.logging import log_context, log_event`; constructor param `monotonic: Callable[[], float] = time.monotonic` stored as `self._monotonic`. Replace `run_once`:

```python
    def run_once(self) -> bool:
        job = self.store.claim_next_job(self.owner, self.settings.lease_seconds, self._clock())
        if job is None:
            return False
        with log_context(job_id=job.id, correlation_id=job.correlation_id, project_id=job.project_id, worker=self.owner):
            self._run_claimed(job)
        return True

    def _run_claimed(self, job: Job) -> None:
        started = self._monotonic()
        # attempts only exceeds max_attempts here when the previous attempt
        # died without recording anything (killed process -> lease expiry).
        if job.attempts > job.max_attempts:
            self.store.fail_job(job.id, self.owner, job.error or "Exceeded maximum attempts", self._clock())
            self._log_finished("failed", started, job)
            return

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
                error_roots=self._error_roots,
                monotonic=self._monotonic,
            )
            try:
                outcome: str = process_job(job, context)
            except JobAbandoned:
                if not heartbeat.lost:
                    self.store.release_lease(job.id, self.owner, self._clock())
                logger.info("Worker %s abandoned job %s", self.owner, job.id)
                outcome = "abandoned"
            except LeaseLostError:
                logger.warning("Lost lease on job %s; another worker owns it now", job.id)
                outcome = "lease_lost"
        self._log_finished(outcome, started, job)

    def _log_finished(self, outcome: str, started: float, job: Job) -> None:
        duration_ms = round((self._monotonic() - started) * 1000)
        log_event(logger, "job_finished", outcome=outcome, duration_ms=duration_ms, attempt=job.attempts)
```

Import `Job` from `app.persistence.models`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_worker.py tests/test_heartbeat.py -v`
Expected: PASS.

- [ ] **Step 5: Fast suite + commit**

```bash
git add backend/app/worker/worker.py backend/app/worker/heartbeat.py backend/tests/test_worker.py backend/tests/test_heartbeat.py
git commit -m "feat(worker): bind job correlation context to all job logs; log job_finished"
```

---

### Task 7: Source duration and download size limits

**Files:**
- Modify: `backend/app/youtube_audio_extractor.py`, `backend/app/worker/factory.py`
- Test: `backend/tests/test_youtube_audio_extractor.py`, `backend/tests/test_worker_factory.py`

**Interfaces:**
- Consumes: `Settings.max_source_duration_seconds`, `Settings.max_download_bytes` (Task 1).
- Produces: `YtDlpAudioExtractor(max_duration_seconds: int = 900, max_download_bytes: int = 200 * 1024**2)`; `_build_ydl_options(destination_dir: Path, max_download_bytes: int = 200 * 1024**2) -> dict` (adds `"max_filesize"`); `default_engines(settings: Settings) -> PipelineEngines`.

- [ ] **Step 1: Write failing tests.** In `backend/tests/test_youtube_audio_extractor.py`, change every existing test's mock from `extract_info.return_value = {...}` with `download=True` to the two-phase flow. Replace these tests:

```python
def mock_ydl(mock_ydl_cls, info):
    ydl = mock_ydl_cls.return_value.__enter__.return_value
    ydl.extract_info.return_value = info
    return ydl


def test_build_ydl_options_caps_the_download_size(tmp_path):
    options = _build_ydl_options(tmp_path, max_download_bytes=1234)

    assert options["max_filesize"] == 1234


def test_extract_raises_when_no_output_file_is_produced(tmp_path, source):
    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl(mock_ydl_cls, {"title": "Song", "duration": 200})

        with pytest.raises(AudioExtractionError, match="did not produce an output file .*200 MB limit"):
            YtDlpAudioExtractor().extract(source, tmp_path / "job-1")


def test_extract_reads_metadata_first_then_downloads(tmp_path, source):
    destination_dir = tmp_path / "job-1"
    destination_dir.mkdir()
    (destination_dir / "source.wav").write_bytes(b"fake wav data")
    info = {"title": "Never Gonna Give You Up", "duration": 213}

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        ydl = mock_ydl(mock_ydl_cls, info)

        result = YtDlpAudioExtractor().extract(source, destination_dir)

    assert result.audio_path == destination_dir / "source.wav"
    assert result.title == "Never Gonna Give You Up"
    ydl.extract_info.assert_called_once_with(source.url, download=False)
    ydl.process_ie_result.assert_called_once_with(info, download=True)


def test_extract_fails_when_metadata_is_missing(tmp_path, source):
    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        ydl = mock_ydl(mock_ydl_cls, None)

        with pytest.raises(AudioExtractionError, match="Could not read the source's metadata"):
            YtDlpAudioExtractor().extract(source, tmp_path / "job-1")

    ydl.process_ie_result.assert_not_called()


def test_too_long_source_is_rejected_before_download(tmp_path, source):
    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        ydl = mock_ydl(mock_ydl_cls, {"title": "Mix", "duration": 3725})

        with pytest.raises(AudioExtractionError, match=r"Source is 62:05 long; the limit is 15:00"):
            YtDlpAudioExtractor(max_duration_seconds=900).extract(source, tmp_path / "job-1")

    ydl.process_ie_result.assert_not_called()


def test_source_at_the_duration_limit_is_accepted(tmp_path, source):
    destination_dir = tmp_path / "job-1"
    destination_dir.mkdir()
    (destination_dir / "source.wav").write_bytes(b"x")

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl(mock_ydl_cls, {"title": "Song", "duration": 900})

        result = YtDlpAudioExtractor(max_duration_seconds=900).extract(source, destination_dir)

    assert result.audio_path.exists()


def test_unknown_duration_is_allowed(tmp_path, source):
    destination_dir = tmp_path / "job-1"
    destination_dir.mkdir()
    (destination_dir / "source.wav").write_bytes(b"x")

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        ydl = mock_ydl(mock_ydl_cls, {"title": "Song"})

        YtDlpAudioExtractor().extract(source, destination_dir)

    ydl.process_ie_result.assert_called_once()


@pytest.mark.parametrize("info", [{"is_live": True}, {"live_status": "is_live"}, {"live_status": "is_upcoming"}])
def test_live_streams_are_rejected(tmp_path, source, info):
    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl(mock_ydl_cls, {"title": "Live", **info})

        with pytest.raises(AudioExtractionError, match="Live streams are not supported"):
            YtDlpAudioExtractor().extract(source, tmp_path / "job-1")


@pytest.mark.parametrize("size_key", ["filesize", "filesize_approx"])
def test_too_large_source_is_rejected_before_download(tmp_path, source, size_key):
    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        ydl = mock_ydl(mock_ydl_cls, {"title": "Big", "duration": 100, size_key: 300 * 1024**2})

        with pytest.raises(AudioExtractionError, match="Source audio is 300 MB; the limit is 200 MB"):
            YtDlpAudioExtractor().extract(source, tmp_path / "job-1")

    ydl.process_ie_result.assert_not_called()


def test_extract_wraps_download_errors(tmp_path, source):
    import yt_dlp

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.return_value.extract_info.side_effect = (
            yt_dlp.utils.DownloadError("video unavailable")
        )

        with pytest.raises(AudioExtractionError, match="video unavailable"):
            YtDlpAudioExtractor().extract(source, tmp_path / "job-1")
```

Remove the old `test_extract_returns_output_path_and_video_title` and `test_extract_returns_no_title_when_metadata_is_missing` (superseded above). Keep `test_build_ydl_options_targets_wav_output_in_destination_dir` and `test_build_ydl_options_sets_a_socket_timeout`.

`backend/tests/test_worker_factory.py`:

```python
def test_default_engines_use_production_adapters_with_configured_limits():
    settings = Settings(_env_file=None, max_source_duration_seconds=60, max_download_bytes=1000)

    engines = default_engines(settings)

    assert isinstance(engines.extractor, YtDlpAudioExtractor)
    assert engines.extractor.max_duration_seconds == 60
    assert engines.extractor.max_download_bytes == 1000
    assert isinstance(engines.separator, DemucsStemSeparator)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_youtube_audio_extractor.py tests/test_worker_factory.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement** — `backend/app/youtube_audio_extractor.py`:

```python
from pathlib import Path

import yt_dlp

from app.audio_extraction import AudioExtractionError, ExtractedAudio
from app.media_source import ParsedSource

_TARGET_SAMPLE_RATE = "44100"
_TARGET_CHANNELS = "2"
_SOCKET_TIMEOUT_SECONDS = 30
_DEFAULT_MAX_DURATION_SECONDS = 900
_DEFAULT_MAX_DOWNLOAD_BYTES = 200 * 1024**2
_LIVE_STATUSES = {"is_live", "is_upcoming"}


def _build_ydl_options(destination_dir: Path, max_download_bytes: int = _DEFAULT_MAX_DOWNLOAD_BYTES) -> dict:
    return {
        "format": "bestaudio/best",
        "outtmpl": str(destination_dir / "source.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "wav"},
        ],
        "postprocessor_args": {
            "extractaudio": ["-ar", _TARGET_SAMPLE_RATE, "-ac", _TARGET_CHANNELS],
        },
        "quiet": True,
        "noplaylist": True,
        "noprogress": True,
        "socket_timeout": _SOCKET_TIMEOUT_SECONDS,
        # Backstop for sources whose metadata has no size: yt-dlp skips
        # (does not raise on) a download that grows past this.
        "max_filesize": max_download_bytes,
    }


def _minutes(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _megabytes(size: float) -> str:
    return f"{size / 1024**2:.0f}"


class YtDlpAudioExtractor:
    """Reads the source's metadata first and refuses live streams, sources
    longer than `max_duration_seconds` and audio larger than
    `max_download_bytes` before downloading anything."""

    def __init__(
        self,
        max_duration_seconds: int = _DEFAULT_MAX_DURATION_SECONDS,
        max_download_bytes: int = _DEFAULT_MAX_DOWNLOAD_BYTES,
    ) -> None:
        self.max_duration_seconds = max_duration_seconds
        self.max_download_bytes = max_download_bytes

    def extract(self, source: ParsedSource, destination_dir: Path) -> ExtractedAudio:
        destination_dir.mkdir(parents=True, exist_ok=True)
        options = _build_ydl_options(destination_dir, self.max_download_bytes)

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(source.url, download=False)
                if not isinstance(info, dict):
                    raise AudioExtractionError("Could not read the source's metadata")
                self._check_limits(info)
                ydl.process_ie_result(info, download=True)
        except yt_dlp.utils.DownloadError as error:
            raise AudioExtractionError(f"Failed to download audio: {error}") from error

        output_path = destination_dir / "source.wav"
        if not output_path.exists():
            raise AudioExtractionError(
                "Audio extraction did not produce an output file "
                f"(the download may exceed the {_megabytes(self.max_download_bytes)} MB limit)"
            )

        return ExtractedAudio(audio_path=output_path, title=info.get("title"))

    def _check_limits(self, info: dict) -> None:
        if info.get("is_live") or info.get("live_status") in _LIVE_STATUSES:
            raise AudioExtractionError("Live streams are not supported")
        duration = info.get("duration")
        if isinstance(duration, int | float) and duration > self.max_duration_seconds:
            raise AudioExtractionError(
                f"Source is {_minutes(duration)} long; the limit is {_minutes(self.max_duration_seconds)}"
            )
        size = info.get("filesize") or info.get("filesize_approx")
        if isinstance(size, int | float) and size > self.max_download_bytes:
            raise AudioExtractionError(
                f"Source audio is {_megabytes(size)} MB; the limit is {_megabytes(self.max_download_bytes)} MB"
            )
```

`backend/app/worker/factory.py`:

```python
def default_engines(settings: Settings) -> PipelineEngines:
    return PipelineEngines(
        source_validator=YouTubeSourceValidator(),
        extractor=YtDlpAudioExtractor(
            max_duration_seconds=settings.max_source_duration_seconds,
            max_download_bytes=settings.max_download_bytes,
        ),
        separator=DemucsStemSeparator(),
        transcriber=DrumScriptTranscriber(),
        tempo_estimator=LibrosaTempoEstimator(),
        beat_detector=LibrosaBeatDetector(),
    )
```

and `engines=default_engines(settings),` in `build_worker`. `grep -rn "default_engines(" backend` must show no other caller without settings.

- [ ] **Step 4: Run to verify pass** — same command, expected PASS.

- [ ] **Step 5: Fast suite + commit**

```bash
git add backend/app/youtube_audio_extractor.py backend/app/worker/factory.py backend/tests/test_youtube_audio_extractor.py backend/tests/test_worker_factory.py
git commit -m "feat(extraction): reject live, too-long and too-large sources before download"
```

---

### Task 8: Store queries for admission control

**Files:**
- Modify: `backend/app/persistence/store.py`, `backend/app/persistence/memory.py`, `backend/app/persistence/postgres.py`
- Test: `backend/tests/test_store_contract.py`

**Interfaces:**
- Produces: `Store.count_active_jobs() -> int` (status not `completed`/`failed`, project not soft-deleted); `Store.live_artifact_bytes() -> int` (sum of `size_bytes` over distinct `storage_key` of rows with `pruned_at IS NULL`).

- [ ] **Step 1: Write failing tests** — append to `backend/tests/test_store_contract.py` (uses its `create`, `run_stage`, `descriptor`, `complete`, `OWNER`, `NOW`):

```python
def test_count_active_jobs_ignores_terminal_jobs_and_deleted_projects(store):
    _, done = create(store, key="youtube:done", now=NOW)
    complete(store, done.id)
    create(store, key="youtube:failed", now=NOW + timedelta(seconds=1))
    failing = store.claim_next_job(OWNER, LEASE, NOW + timedelta(seconds=1))
    store.fail_job(failing.id, OWNER, "boom", NOW + timedelta(seconds=1))
    create(store, key="youtube:running", now=NOW + timedelta(seconds=2))
    store.claim_next_job(OWNER, LEASE, NOW + timedelta(seconds=2))
    create(store, key="youtube:queued", now=NOW + timedelta(seconds=3))
    deleted, _ = create(store, key="youtube:deleted", now=NOW + timedelta(seconds=4))
    store.soft_delete_project(deleted.id, NOW + timedelta(seconds=4))

    count = store.count_active_jobs()

    assert count == 2


def test_count_active_jobs_is_zero_for_an_empty_store(store):
    assert store.count_active_jobs() == 0


def test_live_artifact_bytes_counts_each_key_once_and_skips_pruned(store):
    _, first = create(store, key="youtube:a")
    run_stage(store, first.id, [descriptor(ArtifactKind.DRUMS_STEM, "shared/drums.wav"), descriptor(ArtifactKind.SOURCE_AUDIO, "a/source.wav")])
    _, second = create(store, key="youtube:b")
    run_stage(store, second.id, [descriptor(ArtifactKind.DRUMS_STEM, "shared/drums.wav"), descriptor(ArtifactKind.SOURCE_AUDIO, "b/source.wav")])
    store.mark_storage_keys_pruned({"b/source.wav"}, NOW)

    total = store.live_artifact_bytes()

    assert total == 8


def test_live_artifact_bytes_is_zero_for_an_empty_store(store):
    assert store.live_artifact_bytes() == 0
```

(Each job is created after the previous one reached its state, so every `claim_next_job` has exactly one eligible job; the two active ones are `running` and `queued`.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_store_contract.py -k "active_jobs or live_artifact" -v` (runs memory; postgres too when Docker is up)
Expected: FAIL (`AttributeError: 'InMemoryStore' object has no attribute 'count_active_jobs'`).

- [ ] **Step 3: Implement.** `backend/app/persistence/store.py`, new section before `# --- lifecycle`:

```python
    # --- admission ----------------------------------------------------------
    def count_active_jobs(self) -> int: ...

    def live_artifact_bytes(self) -> int: ...
```

`backend/app/persistence/memory.py`:

```python
    def count_active_jobs(self):
        with self._lock:
            return sum(
                1
                for job in self._jobs.values()
                if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED)
                and self._projects[job.project_id].deleted_at is None
            )

    def live_artifact_bytes(self):
        with self._lock:
            sizes = {a.storage_key: a.size_bytes for a in self._artifacts.values() if a.pruned_at is None}
            return sum(sizes.values())
```

`backend/app/persistence/postgres.py` (module-level SQL next to the other `_..._SQL` constants, methods next to `disposable_storage_keys`):

```python
_LIVE_BYTES_SQL = text(
    """
    SELECT COALESCE(SUM(size_bytes), 0) FROM (
        SELECT DISTINCT ON (storage_key) size_bytes
        FROM artifacts
        WHERE pruned_at IS NULL
        ORDER BY storage_key
    ) AS live
    """
)

    def count_active_jobs(self):
        query = (
            select(func.count())
            .select_from(t.jobs.join(t.projects, t.jobs.c.project_id == t.projects.c.id))
            .where(
                t.jobs.c.status.not_in([JobStatus.COMPLETED.value, JobStatus.FAILED.value]),
                t.projects.c.deleted_at.is_(None),
            )
        )
        with self.engine.connect() as c:
            return c.execute(query).scalar_one()

    def live_artifact_bytes(self):
        with self.engine.connect() as c:
            return int(c.execute(_LIVE_BYTES_SQL).scalar_one())
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_store_contract.py -v` (Docker running → both implementations)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/persistence/store.py backend/app/persistence/memory.py backend/app/persistence/postgres.py backend/tests/test_store_contract.py
git commit -m "feat(persistence): count active jobs and live artifact bytes for admission"
```

---

### Task 9: HTTP middlewares — request ID/access event and body size limit

**Files:**
- Create: `backend/app/observability/http.py`
- Modify: `backend/app/main.py`, `backend/app/api/schemas.py` (URL max length)
- Test: `backend/tests/test_http_middleware.py`, `backend/tests/test_projects_api.py`

**Interfaces:**
- Consumes: `log_context`, `log_event` (Task 2); `Settings.max_request_bytes` (Task 1).
- Produces: `RequestContextMiddleware(app, monotonic: Callable[[], float] = time.monotonic)`; `RequestSizeLimitMiddleware(app, max_bytes: int)`; response header `X-Request-ID`; event `http_request {method, path, status:int, duration_ms:int}` from logger `app.observability.http`; `CreateProjectRequest.url` max 2048 chars.

- [ ] **Step 1: Write failing tests** — `backend/tests/test_http_middleware.py`:

```python
import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import main
from app.observability.http import RequestContextMiddleware, RequestSizeLimitMiddleware
from app.observability.logging import current_context
from tests.fakes import FakeMonotonic, logged_events


def context_app(monotonic=None):
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"context": current_context()}

    app.add_middleware(RequestContextMiddleware, monotonic=monotonic or FakeMonotonic())
    return app


def test_request_id_is_generated_bound_and_returned():
    client = TestClient(context_app())

    response = client.get("/ping")

    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32
    assert response.json()["context"] == {"request_id": request_id}


def test_safe_incoming_request_id_is_reused():
    client = TestClient(context_app())

    response = client.get("/ping", headers={"X-Request-ID": "abc-123.DEF_4"})

    assert response.headers["x-request-id"] == "abc-123.DEF_4"


def test_unsafe_request_id_is_replaced():
    client = TestClient(context_app())

    for unsafe in ("a b", 'quote"d', "x" * 65, ""):
        response = client.get("/ping", headers={"X-Request-ID": unsafe})

        assert response.headers["x-request-id"] != unsafe
        assert len(response.headers["x-request-id"]) == 32


def test_every_request_logs_an_http_request_event(caplog):
    monotonic = FakeMonotonic()
    app = context_app(monotonic)

    @app.get("/slow")
    def slow():
        monotonic.advance(0.25)
        return {}

    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app.observability.http"):
        response = client.get("/slow")

    event = logged_events(caplog, "http_request")[0]
    assert event == {
        "request_id": response.headers["x-request-id"],
        "method": "GET",
        "path": "/slow",
        "status": 200,
        "duration_ms": 250,
    }


def size_limited_app(max_bytes):
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request):
        return {"size": len(await request.body())}

    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_bytes)
    return app


def test_body_within_the_limit_passes():
    client = TestClient(size_limited_app(10))

    response = client.post("/echo", content=b"x" * 10)

    assert response.json() == {"size": 10}


def test_declared_oversized_body_is_rejected_with_413():
    client = TestClient(size_limited_app(10))

    response = client.post("/echo", content=b"x" * 11)

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is larger than the 10-byte limit"}


def test_streamed_body_without_content_length_is_cut_off_at_the_limit():
    received = []

    async def downstream(scope, receive, send):
        while True:
            message = await receive()
            received.append(message)
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    chunks = [
        {"type": "http.request", "body": b"x" * 6, "more_body": True},
        {"type": "http.request", "body": b"x" * 6, "more_body": False},
    ]
    sent = []

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/echo", "headers": []}

    asyncio.run(RequestSizeLimitMiddleware(downstream, max_bytes=10)(scope, receive, send))

    assert sent[0]["status"] == 413
    assert len(received) == 1


def test_main_app_installs_both_middlewares():
    classes = [m.cls for m in main.app.user_middleware]

    assert RequestContextMiddleware in classes
    assert RequestSizeLimitMiddleware in classes
    assert classes.index(RequestContextMiddleware) < classes.index(RequestSizeLimitMiddleware)
```

(`app.user_middleware` lists the outermost middleware first.)

In `backend/tests/test_projects_api.py`:

```python
def test_create_rejects_urls_longer_than_2048_characters(harness):
    response = harness.create("https://youtu.be/dQw4w9WgXcQ?x=" + "a" * 2048)

    assert response.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_http_middleware.py tests/test_projects_api.py -k "not postgres" -v`
Expected: FAIL (`ModuleNotFoundError: app.observability.http`; long URL returns 201).

- [ ] **Step 3: Implement** — `backend/app/observability/http.py`:

```python
"""Pure-ASGI middlewares for the API: a per-request log context with an
X-Request-ID and one `http_request` event per request, and a request body
size limit that also covers bodies streamed without Content-Length."""

import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from app.observability.logging import log_context, log_event

logger = logging.getLogger(__name__)

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

Scope = dict[str, Any]
Receive = Callable[[], Any]
Send = Callable[[dict[str, Any]], Any]


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


class RequestContextMiddleware:
    def __init__(self, app: Any, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.app = app
        self._monotonic = monotonic

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope, b"x-request-id")
        request_id = incoming if incoming and _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        status = 500
        started = self._monotonic()

        async def send_with_request_id(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [*message.get("headers", []), (b"x-request-id", request_id.encode("latin-1"))]
                message = {**message, "headers": headers}
            await send(message)

        with log_context(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_request_id)
            finally:
                log_event(
                    logger, "http_request",
                    method=scope["method"], path=scope["path"], status=status,
                    duration_ms=round((self._monotonic() - started) * 1000),
                )


class _BodyTooLarge(Exception):
    pass


class RequestSizeLimitMiddleware:
    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _header(scope, b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        response_started = False

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if response_started:
                raise
            await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps({"detail": f"Request body is larger than the {self.max_bytes}-byte limit"}).encode()
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
```

`backend/app/main.py` — middleware order (Starlette: last added is outermost; wanted outer→inner: RequestContext, CORS, RequestSizeLimit):

```python
app = FastAPI(title="Drumscore API", lifespan=lifespan)
app.include_router(projects_router)

app.add_middleware(RequestSizeLimitMiddleware, max_bytes=_settings.max_request_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestContextMiddleware)
```

`backend/app/api/schemas.py` — `CreateProjectRequest`:

```python
class CreateProjectRequest(BaseModel):
    url: str = Field(max_length=2048)
```

(import `Field` from pydantic; keep any other existing fields of the class unchanged.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_http_middleware.py tests/test_projects_api.py tests/test_main.py -m "not integration" -v`
Expected: PASS.

- [ ] **Step 5: Fast suite + commit**

```bash
git add backend/app/observability/http.py backend/app/main.py backend/app/api/schemas.py backend/tests/test_http_middleware.py backend/tests/test_projects_api.py
git commit -m "feat(api): request IDs, http_request events and request size limit"
```

---

### Task 10: API admission limits and correlated project events

**Files:**
- Modify: `backend/app/api/projects.py`
- Test: `backend/tests/test_projects_api.py`

**Interfaces:**
- Consumes: `Store.count_active_jobs`, `Store.live_artifact_bytes` (Task 8); `Settings.max_active_jobs`, `Settings.storage_max_bytes` (Task 1); `log_context`, `log_event` (Task 2).
- Produces: `POST /api/projects` and `POST /api/projects/{id}/retry` return 507 (storage) or 503 + `Retry-After: 60` (active jobs) before writing; events `project_created` / `job_requeued` carrying `project_id`, `job_id`, `correlation_id`.

- [ ] **Step 1: Write failing tests** — in `backend/tests/test_projects_api.py`, let `override`/`make_harness` accept settings overrides: change `override(store, storage, clock)` to `override(store, storage, clock, settings=None)` using `get_app_settings: lambda: settings or Settings(_env_file=None)`, and `make_harness(store, tmp_path, **setting_overrides)` passing `Settings(_env_file=None, **setting_overrides) if setting_overrides else None`. Add:

```python
@pytest.fixture
def limited_harness(store, tmp_path):
    def build(**overrides):
        return make_harness(store, tmp_path, **overrides)

    yield build
    app.dependency_overrides.clear()


def test_create_is_refused_with_503_when_too_many_jobs_are_active(limited_harness):
    harness = limited_harness(max_active_jobs=1)
    harness.create()

    response = harness.create(OTHER_URL)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"
    assert "Too many jobs" in response.json()["detail"]
    assert len(harness.store.list_live_projects()) == 1


def test_create_is_accepted_again_once_a_job_finishes(limited_harness):
    harness = limited_harness(max_active_jobs=1)
    harness.create()
    harness.process_next()

    response = harness.create(OTHER_URL)

    assert response.status_code == 201


def test_create_is_refused_with_507_when_storage_is_full(limited_harness):
    harness = limited_harness(storage_max_bytes=1, storage_warn_bytes=1)
    harness.completed_project()

    response = harness.create(OTHER_URL)

    assert response.status_code == 507
    assert "Storage is full" in response.json()["detail"]


def test_duplicate_check_runs_before_admission(limited_harness):
    harness = limited_harness(max_active_jobs=1)
    harness.create()

    response = harness.create()

    assert response.status_code == 409


def test_retry_is_refused_with_503_when_too_many_jobs_are_active(limited_harness):
    harness = limited_harness(max_active_jobs=1)
    failed_id = harness.create().json()["project"]["id"]
    harness.process_next(make_engines(extractor=FakeExtractor(error=AudioExtractionError("gone"))))
    harness.create(OTHER_URL)

    response = harness.client.post(f"/api/projects/{failed_id}/retry")

    assert response.status_code == 503


def test_create_logs_project_created_with_correlation_ids(harness, caplog):
    with caplog.at_level(logging.INFO, logger="app.api.projects"):
        body = harness.create().json()

    event = logged_events(caplog, "project_created")[0]
    job = harness.store.get_job(body["job"]["id"])
    assert event["project_id"] == body["project"]["id"]
    assert event["job_id"] == job.id
    assert event["correlation_id"] == job.correlation_id
    assert event["request_id"]


def test_retry_logs_job_requeued_with_correlation_ids(harness, caplog):
    project_id = harness.create().json()["project"]["id"]
    job = harness.process_next(make_engines(extractor=FakeExtractor(error=AudioExtractionError("gone"))))

    with caplog.at_level(logging.INFO, logger="app.api.projects"):
        harness.client.post(f"/api/projects/{project_id}/retry")

    event = logged_events(caplog, "job_requeued")[0]
    assert event["job_id"] == job.id
    assert event["correlation_id"] == job.correlation_id
```

Imports: `import logging`, `from tests.fakes import logged_events` (alongside the existing fakes import).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_projects_api.py -m "not integration" -v`
Expected: FAIL (201 instead of 503/507; no `project_created` event).

- [ ] **Step 3: Implement** in `backend/app/api/projects.py`: import `from app.observability.logging import log_context, log_event`; add

```python
def _admit_new_job(store: Store, settings: Settings) -> None:
    """Refuses new work while storage or the job queue is at its limit.
    Advisory under concurrency: two requests at the limit can both pass,
    so the queue can overshoot by the number of simultaneous requests."""
    if store.live_artifact_bytes() >= settings.storage_max_bytes:
        raise HTTPException(
            status_code=507, detail="Storage is full; delete projects or raise STORAGE_MAX_BYTES"
        )
    if store.count_active_jobs() >= settings.max_active_jobs:
        raise HTTPException(
            status_code=503,
            detail="Too many jobs are queued or running; try again later",
            headers={"Retry-After": "60"},
        )
```

In `create_project`, call `_admit_new_job(store, settings)` after the duplicate check and before `store.create_project_with_job(...)`; replace the old `logger.info("Created project ...")` with

```python
    with log_context(project_id=project.id, job_id=job.id, correlation_id=job.correlation_id):
        log_event(logger, "project_created", source_key=source_key)
```

In `retry_project`, add `settings: Settings = Depends(get_app_settings)` to the signature, call `_admit_new_job(store, settings)` after the failed-status check and before `requeue_failed_job`, and after a successful requeue:

```python
    with log_context(project_id=project.id, job_id=requeued.id, correlation_id=requeued.correlation_id):
        log_event(logger, "job_requeued")
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_projects_api.py -v` (Docker up → memory and postgres)
Expected: PASS.

- [ ] **Step 5: Fast suite + commit**

```bash
git add backend/app/api/projects.py backend/tests/test_projects_api.py
git commit -m "feat(api): refuse new jobs when storage or the queue is full; log correlated project events"
```

---

### Task 11: Operations doc, env/secret checks and debt updates

**Files:**
- Create: `docs/OPERATIONS.md`, `backend/tests/test_operations_doc.py`
- Modify: `backend/.env.example`, `docs/PERSISTENCE.md`, `docs/ARCHITECTURE_V1.md`, `TECHNICAL_DEBT.md`

**Interfaces:** Consumes `Settings.model_fields` (Task 1). Produces documentation only.

- [ ] **Step 1: Write failing tests** — `backend/tests/test_operations_doc.py`:

```python
from pathlib import Path

from app.config import Settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
OPERATIONS = BACKEND_DIR.parent / "docs" / "OPERATIONS.md"


def env_example_keys():
    lines = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    return {line.split("=", 1)[0].strip() for line in lines if line.strip() and not line.startswith("#")}


def test_every_setting_is_documented_in_operations_md():
    text = OPERATIONS.read_text(encoding="utf-8")

    missing = [name.upper() for name in Settings.model_fields if f"`{name.upper()}`" not in text]

    assert missing == []


def test_env_file_is_git_ignored():
    patterns = (BACKEND_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in [pattern.strip() for pattern in patterns]


def test_env_example_only_uses_known_settings():
    known = {name.upper() for name in Settings.model_fields}

    assert env_example_keys() <= known


def test_env_example_database_url_is_the_development_placeholder():
    lines = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    url = next(line.split("=", 1)[1] for line in lines if line.startswith("DATABASE_URL="))

    assert url == "postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_operations_doc.py -v`
Expected: FAIL (`FileNotFoundError` for `docs/OPERATIONS.md`).

- [ ] **Step 3: Write the docs.**

`backend/.env.example` — add `LOG_FORMAT=text` (readable local logs) below the existing three lines.

`docs/OPERATIONS.md` must contain, in this order:
1. **Processes** — API (`uv run uvicorn app.main:app --no-access-log`; why `--no-access-log`: `http_request` replaces uvicorn's access log, whose logger is otherwise routed into the same JSON stream and would duplicate lines) and workers (`uv run python -m app.worker`).
2. **Configuration** — one table row per setting with columns *Variable* (backticked upper-case name, e.g. `` `DATABASE_URL` ``), *Default*, *Secret* (yes only for `DATABASE_URL`), *Meaning*. All fields: `DATABASE_URL`, `STORAGE_ROOT`, `WORKER_CONCURRENCY`, `LEASE_SECONDS`, `HEARTBEAT_SECONDS`, `POLL_INTERVAL_SECONDS`, `MAX_ATTEMPTS`, `RETRY_BASE_SECONDS`, `FAILED_JOB_RETENTION_DAYS`, `PRUNE_INTERVAL_SECONDS`, `STORAGE_WARN_BYTES`, `RUN_MIGRATIONS_ON_STARTUP`, `LOG_LEVEL`, `LOG_FORMAT`, `MAX_SOURCE_DURATION_SECONDS`, `MAX_DOWNLOAD_BYTES`, `MAX_REQUEST_BYTES`, `MAX_ACTIVE_JOBS`, `STORAGE_MAX_BYTES`.
3. **Secrets** — `DATABASE_URL` is the only secret; it is a `SecretStr` (never in `repr`); every log line passes through redaction (URL passwords and `password=` pairs become `***`); `backend/.env` is git-ignored and never committed; `backend/.env.example` holds only development placeholders; production supplies secrets through the environment (containerization, #85, decides the mechanism). `job.error` is sanitized before storage (placeholders `<storage>`, `<tmp>`, `<app>`, `<path>`, 500-char cap, head 200 + `…` + tail 299); the unsanitized text stays in the worker log.
4. **Limits** — table: the five new limits (value, where enforced, response/error text), the URL 2048-char limit, and the existing ones: `WORKER_CONCURRENCY`, Demucs 600 s and DrumScript 600 s timeouts (hard-coded in `demucs_stem_separator.py`/`drumscript_transcriber.py`), yt-dlp 30 s socket timeout, `LEASE_SECONDS`, `MAX_ATTEMPTS`, `STORAGE_WARN_BYTES` (warning only). State that admission checks are advisory under concurrency and that `STORAGE_MAX_BYTES` counts live artifact files (distinct keys, not temp/staging files).
5. **Logs** — format (`LOG_FORMAT=json|text`), JSON keys (`ts`, `level`, `logger`, `message`, context fields, event fields, `exc`), context fields (`request_id` in the API; `job_id`, `correlation_id`, `project_id`, `worker` in workers), how to follow one job: filter on `job_id` (API `project_created`/`job_requeued` carry it too).
6. **Event catalogue** — table of `http_request`, `project_created`, `job_requeued`, `stage_started`, `stage_finished`, `stage_failed`, `job_finished` with their fields and allowed `outcome` values exactly as in the Global Constraints.

`docs/PERSISTENCE.md` — add a short "API admission limits" subsection (after the claim/lease section) pointing to `docs/OPERATIONS.md#limits`: create/retry refuse with 507/503 based on `live_artifact_bytes()` / `count_active_jobs()`.

`docs/ARCHITECTURE_V1.md` — at the end of the `## Observability` paragraph add: "Implemented in V1-033; see docs/OPERATIONS.md for the log format, event catalogue, limits and secret handling."

`TECHNICAL_DEBT.md` — append a **Resolved (V1-033):** note to:
- "Correlation IDs are stored but not yet propagated to logs" — worker binds `job_id`/`correlation_id`/`project_id`/`worker` for the whole job (incl. heartbeat thread); API events carry them.
- "`job.error` can contain absolute filesystem paths" — `sanitize_error_message` in `app/observability/redaction.py`.
- "Engine subprocess output is decoded with the Windows code page" — both engine calls decode UTF-8 with `errors="replace"`; regression tests feed undecodable bytes.
Add new **Deferred** entries for anything found during implementation (at minimum: "Admission limits are advisory under concurrent requests" — found in V1-033, fix would be a serializable/locked admission check, deferred because overshoot is bounded by concurrent requests in a single-user deployment).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_operations_doc.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/OPERATIONS.md docs/PERSISTENCE.md docs/ARCHITECTURE_V1.md TECHNICAL_DEBT.md backend/.env.example backend/tests/test_operations_doc.py
git commit -m "docs: add operations guide (env, secrets, limits, log events); resolve V1-033 debt"
```

---

### Task 12: Full verification and manual log-trail check

**Files:** none (verification only; fix-ups go in their own commits).

- [ ] **Step 1: Full backend suite** — `cd backend && uv run pytest` (Docker running). Expected: all pass (previous baseline 374 + new tests), no warnings about unclosed handlers.
- [ ] **Step 2: Frontend regression** — `cd frontend && pnpm test && pnpm lint && pnpm exec tsc --noEmit`. Expected: all pass, unchanged count (299).
- [ ] **Step 3: Grep checks** — `grep -rn "basicConfig" backend/app` → no matches; `grep -rn "database_url" backend/app | grep -v get_secret_value | grep -v "config.py"` → no matches.
- [ ] **Step 4: Manual check (needs the user's local Postgres on :5433 and services, like Slice A)** — start the API (`uv run uvicorn app.main:app --no-access-log`) and one worker with `LOG_FORMAT=json`, submit a real song from the UI, then filter both processes' output on that job's `job_id`: expect `project_created` (API, with `request_id`), `stage_started`/`stage_finished` for `extract`, `separate`, `transcribe`, `map_tempo` with plausible `duration_ms`, and `job_finished outcome=completed` (worker). Submit a > 15-minute video: expect the job to fail with "Source is … long; the limit is 15:00" and `stage_failed stage=extract permanent=true`. Confirm no line contains the database password.
- [ ] **Step 5: Push and open the PR** closing #84 (body: summary per acceptance criterion, event catalogue pointer, test plan with the manual check result, scope-outs: metrics endpoint, auth, configurable engine timeouts, advisory admission).
