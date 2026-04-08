"""Tests for JsonFormatter in utils.logging_utils (JTN-337)."""

import json
import logging
import sys

from utils.logging_utils import JsonFormatter


def _make_record(
    name="test.logger",
    level=logging.INFO,
    msg="Hello %s",
    args=("world",),
    lineno=42,
    exc_info=None,
):
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=lineno,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )


# ---------------------------------------------------------------------------
# Basic fields
# ---------------------------------------------------------------------------


def test_basic_fields_present():
    record = _make_record()
    data = json.loads(JsonFormatter().format(record))
    for key in ("ts", "level", "logger", "msg", "module", "func", "line", "pid"):
        assert key in data, f"Expected key '{key}' missing from output"


def test_basic_field_values():
    record = _make_record(
        name="myapp.module",
        level=logging.DEBUG,
        msg="checking fields",
        args=(),
        lineno=99,
    )
    data = json.loads(JsonFormatter().format(record))
    assert data["level"] == "DEBUG"
    assert data["logger"] == "myapp.module"
    assert data["msg"] == "checking fields"
    assert data["line"] == 99


def test_msg_arg_interpolation():
    record = _make_record(msg="Hello %s", args=("world",))
    data = json.loads(JsonFormatter().format(record))
    assert data["msg"] == "Hello world"


def test_ts_is_iso8601_utc():
    record = _make_record()
    data = json.loads(JsonFormatter().format(record))
    ts = data["ts"]
    assert "T" in ts
    assert ts.endswith("+00:00") or ts.endswith("Z"), f"Expected UTC ts, got: {ts}"


def test_pid_is_integer():
    record = _make_record()
    data = json.loads(JsonFormatter().format(record))
    assert isinstance(data["pid"], int)


# ---------------------------------------------------------------------------
# Exception records
# ---------------------------------------------------------------------------


def test_exception_fields_present():
    try:
        raise ValueError("boom")
    except ValueError:
        exc = sys.exc_info()

    record = _make_record(level=logging.ERROR, msg="error", args=(), exc_info=exc)
    data = json.loads(JsonFormatter().format(record))
    assert data["exc_type"] == "ValueError"
    assert data["exc_message"] == "boom"
    assert "ValueError" in data["exc_traceback"]


def test_exception_no_exc_type_key_when_no_exception():
    record = _make_record()
    data = json.loads(JsonFormatter().format(record))
    assert "exc_type" not in data
    assert "exc_message" not in data
    assert "exc_traceback" not in data


# ---------------------------------------------------------------------------
# Extra fields
# ---------------------------------------------------------------------------


def test_extras_passed_through():
    record = _make_record()
    record.request_id = "abc123"
    record.user_id = 42
    data = json.loads(JsonFormatter().format(record))
    assert data["extra"]["request_id"] == "abc123"
    assert data["extra"]["user_id"] == 42


def test_no_extra_key_when_no_extras():
    record = _make_record()
    data = json.loads(JsonFormatter().format(record))
    assert "extra" not in data


# ---------------------------------------------------------------------------
# Non-serialisable extras must not crash
# ---------------------------------------------------------------------------


def test_non_serialisable_extra_does_not_crash():
    class Unserializable:
        def __repr__(self):
            return "<Unserializable>"

    record = _make_record()
    record.bad_field = Unserializable()
    out = JsonFormatter().format(record)
    data = json.loads(out)
    assert "bad_field" in data["extra"]


# ---------------------------------------------------------------------------
# default_fields
# ---------------------------------------------------------------------------


def test_default_fields_merged():
    formatter = JsonFormatter(default_fields={"app": "inkypi", "env": "test"})
    record = _make_record()
    data = json.loads(formatter.format(record))
    assert data["app"] == "inkypi"
    assert data["env"] == "test"


# ---------------------------------------------------------------------------
# Env-var detection: monkeypatch INKYPI_LOG_FORMAT=json
# ---------------------------------------------------------------------------


def test_setup_logging_uses_json_formatter_when_env_set(monkeypatch, tmp_path):
    """setup_logging() must attach JsonFormatter to root when env var is json."""
    monkeypatch.setenv("INKYPI_LOG_FORMAT", "json")

    # Remove all existing root handlers to get a clean slate
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    root.handlers = []

    try:
        from app_setup.logging_setup import setup_logging

        setup_logging()

        root_handlers = logging.getLogger().handlers
        assert len(root_handlers) >= 1, "Expected at least one handler on root logger"
        formatter = root_handlers[0].formatter
        assert isinstance(
            formatter, JsonFormatter
        ), f"Expected JsonFormatter, got {type(formatter)}"
    finally:
        # Restore root logger state
        root.handlers = original_handlers
        root.level = original_level
