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


