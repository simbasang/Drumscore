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
        return redact(json.dumps(payload, default=str, ensure_ascii=True))


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
    target = stream or sys.stdout
    if hasattr(target, "reconfigure"):
        # The default stdout encoding (e.g. cp1252 when stdout is redirected
        # on Windows) can't represent every character a log message may
        # contain (engine stderr decoded with errors="replace" produces
        # U+FFFD, for example). Without this, logging's own StreamHandler
        # raises UnicodeEncodeError on write, prints "--- Logging error ---"
        # to stderr, and silently drops the record.
        target.reconfigure(errors="backslashreplace")
    handler = logging.StreamHandler(target)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.drumscore = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
