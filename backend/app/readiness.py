"""Readiness checks: can this process do its job right now?

`/api/health` only says the API process is up (liveness). Readiness also
checks what the process depends on: the database (reachable and migrated to
head) and the artifact storage (writable) for the API, plus the audio/ML
engines for a worker. `python -m app.readiness worker` is the worker
container's healthcheck; docs/DEPLOYMENT.md describes both."""

import argparse
import json
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.config import Settings, get_settings
from app.drumscript_transcriber import runner_python
from app.observability.redaction import default_error_roots, sanitize_error_message
from app.persistence.migrations import migration_config

_CONNECT_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _failure(name: str, error: Exception, storage_root: Path | None = None) -> CheckResult:
    roots = default_error_roots(storage_root) if storage_root is not None else ()
    return CheckResult(name, False, sanitize_error_message(f"{type(error).__name__}: {error}", roots))


def check_database(database_url: str) -> CheckResult:
    # A healthcheck must answer promptly even when the database host is
    # unreachable, instead of waiting for the OS TCP timeout.
    engine = create_engine(database_url, connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current = MigrationContext.configure(connection).get_current_revision()
    except Exception as error:  # noqa: BLE001 - any failure means "not ready"
        return _failure("database", error)
    finally:
        engine.dispose()

    head = ScriptDirectory.from_config(migration_config(database_url)).get_current_head()
    if current != head:
        return CheckResult("database", False, f"migrations not at head (current {current}, head {head})")
    return CheckResult("database", True, "reachable, migrations at head")


def check_storage(root: Path) -> CheckResult:
    if not root.is_dir():
        return CheckResult("storage", False, "storage root is not an existing directory")
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix=".ready-"):
            pass
    except OSError as error:
        return _failure("storage", error, root)
    return CheckResult("storage", True, "writable")


def check_engines(runner: Path) -> CheckResult:
    missing = []
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg not on PATH")
    if not runner.exists():
        missing.append("DrumScript runner environment missing")
    if missing:
        return CheckResult("engines", False, "; ".join(missing))
    return CheckResult("engines", True, "ffmpeg and DrumScript runner present")


def api_checks(settings: Settings) -> list[CheckResult]:
    return [check_database(settings.database_url.get_secret_value()), check_storage(settings.storage_root)]


def worker_checks(settings: Settings) -> list[CheckResult]:
    return [*api_checks(settings), check_engines(runner_python())]


def report(results: Sequence[CheckResult]) -> dict[str, object]:
    ready = all(result.ok for result in results)
    return {"status": "ready" if ready else "not_ready", "checks": [asdict(result) for result in results]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.readiness")
    parser.add_argument("role", choices=["api", "worker"])
    role = parser.parse_args(argv).role

    checks = worker_checks if role == "worker" else api_checks
    body = report(checks(get_settings()))
    print(json.dumps(body))
    return 0 if body["status"] == "ready" else 1


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
