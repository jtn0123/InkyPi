import json
import logging

from utils.logging_utils import JsonFormatter


def test_json_formatter_basic():
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg="Hello %s",
        args=("world",),
        exc_info=None,
    )
    f = JsonFormatter()
    out = f.format(record)
    data = json.loads(out)
    assert data["level"] == "INFO"
    assert data["logger"] == "test.logger"
    assert data["message"] == "Hello world"
    assert data["line"] == 42
    assert "timestamp" in data


def test_json_formatter_includes_extras():
    record = logging.LogRecord(
        name="t", level=logging.WARNING, pathname=__file__, lineno=1, msg="X", args=(), exc_info=None
    )
    record.request_id = "abc123"
    out = JsonFormatter().format(record)
    data = json.loads(out)
    assert data["extra"]["request_id"] == "abc123"


def test_json_format_basic_fields():
    record = logging.LogRecord(
        name="myapp.module",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=99,
        msg="checking fields",
        args=(),
        exc_info=None,
    )
    data = json.loads(JsonFormatter().format(record))
    for key in ("timestamp", "level", "logger", "message", "module", "function", "line"):
        assert key in data, f"Expected key '{key}' missing from output"
    assert data["level"] == "DEBUG"
    assert data["logger"] == "myapp.module"
    assert data["message"] == "checking fields"
    assert data["line"] == 99


def test_json_format_exception_info():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        exc = sys.exc_info()

    record = logging.LogRecord(
        name="t", level=logging.ERROR, pathname=__file__, lineno=1, msg="error", args=(), exc_info=exc
    )
    data = json.loads(JsonFormatter().format(record))
    assert "exc_info" in data
    assert "ValueError" in data["exc_info"]


def test_json_format_extra_fields():
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1, msg="msg", args=(), exc_info=None
    )
    record.trace_id = "xyz-789"
    record.user_id = 42
    data = json.loads(JsonFormatter().format(record))
    assert data["extra"]["trace_id"] == "xyz-789"
    assert data["extra"]["user_id"] == 42


def test_json_format_default_fields():
    formatter = JsonFormatter(default_fields={"app": "inkypi", "env": "test"})
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1, msg="hi", args=(), exc_info=None
    )
    data = json.loads(formatter.format(record))
    assert data["app"] == "inkypi"
    assert data["env"] == "test"


def test_stringify_fallback():
    class Unserializable:
        def __repr__(self):
            return "<Unserializable>"

    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1, msg="msg", args=(), exc_info=None
    )
    record.bad_field = Unserializable()
    # Should not raise; the non-serializable object is coerced via _stringify
    out = JsonFormatter().format(record)
    data = json.loads(out)
    assert "bad_field" in data["extra"]

