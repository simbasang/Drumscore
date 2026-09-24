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


REPLACEMENT_CHARACTER = chr(0xFFFD)
NON_LATIN_CHARACTER = chr(0x65E5)
UNREPRESENTABLE_MESSAGE = f"bad byte {REPLACEMENT_CHARACTER} and non-latin {NON_LATIN_CHARACTER}"


def configure_and_log(fmt, stream, message):
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging("INFO", fmt, stream=stream)
        logging.getLogger("tests.observability").info(message)
        stream.flush()
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)


def test_json_logging_survives_a_stream_encoding_that_cannot_represent_the_message():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")

    configure_and_log("json", stream, UNREPRESENTABLE_MESSAGE)

    payload = json.loads(raw.getvalue().decode("cp1252").strip())
    assert payload["message"] == UNREPRESENTABLE_MESSAGE


def test_text_logging_survives_a_stream_encoding_that_cannot_represent_the_message():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")

    configure_and_log("text", stream, UNREPRESENTABLE_MESSAGE)

    line = raw.getvalue().decode("cp1252")
    assert "bad byte" in line
    assert REPLACEMENT_CHARACTER.encode("cp1252", errors="backslashreplace").decode("cp1252") in line
    assert NON_LATIN_CHARACTER.encode("cp1252", errors="backslashreplace").decode("cp1252") in line

def test_configure_logging_normalizes_a_lowercase_level():
    stream = io.StringIO()
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging("info", "json", stream=stream)

        assert root.level == logging.INFO
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)


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
