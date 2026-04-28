"""Top-level test module for JSON structured logging (JTN-337).

The detailed formatter unit tests live in tests/unit/test_json_formatter.py.
This module re-runs the key acceptance scenarios at the integration level so
they are discoverable by a plain ``pytest tests/`` invocation.
"""

import json
import logging
import sys

from utils.logging_utils import JsonFormatter, set_log_timezone


def _record(msg="hello", level=logging.INFO, name="root", exc_info=None, **extras):
    r = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    for k, v in extras.items():
        setattr(r, k, v)
    return r


def test_format_logrecord_all_spec_fields():
    data = json.loads(JsonFormatter().format(_record()))
    for field in ("ts", "level", "logger", "msg", "module", "func", "line", "pid"):
        assert field in data, f"Missing spec field: {field}"


def test_exception_record_has_exc_fields():
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        exc = sys.exc_info()

    data = json.loads(
        JsonFormatter().format(_record(level=logging.ERROR, exc_info=exc))
    )
    assert data["exc_type"] == "RuntimeError"
    assert data["exc_message"] == "kaboom"
    assert "RuntimeError" in data["exc_traceback"]


def test_extras_present_in_output():
    data = json.loads(JsonFormatter().format(_record(trace_id="t-1", user="alice")))
    assert data["extra"]["trace_id"] == "t-1"
    assert data["extra"]["user"] == "alice"


def test_non_serialisable_extra_does_not_crash():
    class _Blob:
        pass

    data = json.loads(JsonFormatter().format(_record(blob=_Blob())))
    assert "blob" in data["extra"]


def test_json_formatter_uses_configured_log_timezone():
    try:
        set_log_timezone("America/Los_Angeles")
        record = _record()
        record.created = 1735693200.0  # 2025-01-01T01:00:00Z

        data = json.loads(JsonFormatter().format(record))

        assert data["ts"].endswith("-08:00")
        assert data["ts"].startswith("2024-12-31T17:00:00")
    finally:
        set_log_timezone("UTC")


def test_env_var_detection(monkeypatch):
    """Root logger must use JsonFormatter when INKYPI_LOG_FORMAT=json."""
    monkeypatch.setenv("INKYPI_LOG_FORMAT", "json")

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers = []

    try:
        from app_setup.logging_setup import setup_logging

        setup_logging()
        handlers = logging.getLogger().handlers
        assert handlers, "No handlers attached to root logger"
        assert isinstance(handlers[0].formatter, JsonFormatter)
    finally:
        root.handlers = saved_handlers
        root.level = saved_level
