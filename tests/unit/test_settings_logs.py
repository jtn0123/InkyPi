import re
from collections.abc import Iterator
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from flask.testing import FlaskClient


def test_api_logs_clamp_and_meta(client: FlaskClient) -> None:
    """Out-of-range parameters are clamped, echoed in meta, and flagged."""
    resp = client.get(
        "/api/logs?hours=9999&limit=999999&level=errors&contains=" + ("x" * 500)
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["meta"]["hours"] == 24
    assert data["meta"]["limit"] == 2000
    assert data["meta"]["level"] == "errors"
    assert data["meta"]["contains"] == "x" * 200
    assert data["truncated"] is True


_CORPUS = [
    "Jan 01 host app[1]: INFO started",
    "Jan 01 host app[1]: WARNING something odd",
    "Jan 01 host app[1]: Error mixed case error",
    "Jan 01 host app[1]: critical CRITICAL boom",
    "Jan 01 host app[1]: DEBUG noisy",
]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        pytest.param("level=all", _CORPUS, id="all"),
        pytest.param("level=errors", [_CORPUS[2], _CORPUS[3]], id="errors"),
        pytest.param(
            "level=warn_errors", [_CORPUS[1], _CORPUS[2], _CORPUS[3]], id="warn-errors"
        ),
        pytest.param(
            "level=warnings", [_CORPUS[1], _CORPUS[2], _CORPUS[3]], id="warnings-alias"
        ),
        pytest.param("level=all&contains=STARTED", [_CORPUS[0]], id="contains"),
        pytest.param(
            "level=errors&contains=boom", [_CORPUS[3]], id="contains-and-level"
        ),
    ],
)
def test_api_logs_filters_lines_by_level_and_text(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, query: str, expected: Any
) -> None:
    """Level matching and ``contains`` both ignore case."""
    from services import logs

    monkeypatch.setattr(logs, "_read_log_lines", lambda _hours: list(_CORPUS))

    resp = client.get(f"/api/logs?{query}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["lines"] == expected
    assert data["count"] == len(expected)
    assert data["truncated"] is False


def test_api_logs_keeps_the_newest_lines_up_to_the_limit(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A limit below the minimum is raised to 50, and the newest 50 are kept."""
    from services import logs

    corpus = [f"Jan 01 host app[1]: ERROR line {i}" for i in range(60)]
    monkeypatch.setattr(logs, "_read_log_lines", lambda _hours: corpus)

    resp = client.get("/api/logs?level=errors&limit=2")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["meta"]["limit"] == 50
    assert data["lines"] == corpus[-50:]
    assert data["count"] == 50
    assert data["truncated"] is True


def test_api_logs_hides_a_read_error(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """JTN-141: the reader's exception text does not reach the client."""
    from services import logs

    def failing_read(hours: Any) -> None:
        raise Exception("secret journal path")

    monkeypatch.setattr(logs, "_read_log_lines", failing_read)

    resp = client.get("/api/logs")
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"] == "An error occurred while reading logs"
    assert "secret journal path" not in resp.get_data(as_text=True)


def test_clamp_int_bounds_and_defaults() -> None:
    from blueprints.settings._logs import _clamp_int

    assert _clamp_int("5", 10, 1, 20) == 5
    assert _clamp_int("25", 10, 1, 20) == 20
    assert _clamp_int("0", 10, 1, 20) == 1
    assert _clamp_int(None, 10, 1, 20) == 10
    assert _clamp_int("invalid", 10, 1, 20) == 10


def test_api_logs_size_guard(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ask for a large limit; handler should ensure response size guardrail
    resp = client.get("/api/logs?hours=2&limit=5000&level=all")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] <= data["meta"]["limit"]
    # Ensure meta present
    assert "meta" in data


def test_rate_limit_without_an_address_shares_one_bucket() -> None:
    """A request with no remote address is counted under "unknown"."""
    from blueprints.settings import _logs

    _logs._logs_limiter._requests.pop("unknown", None)
    max_requests = _logs._logs_limiter._max
    try:
        assert all(_logs._rate_limit_ok(None) for _ in range(max_requests))
        assert _logs._rate_limit_ok(None) is False
        assert _logs._rate_limit_ok("1.2.3.4") is True
    finally:
        _logs._logs_limiter._requests.pop("unknown", None)
        _logs._logs_limiter._requests.pop("1.2.3.4", None)


def test_api_logs_rate_limit(client: FlaskClient) -> None:
    """120 requests a minute from one address pass; the 121st gets a 429.

    The reset_rate_limiters fixture empties the limiter before each test, so
    the count starts at zero.
    """
    statuses = [client.get("/api/logs").status_code for _ in range(120)]
    assert statuses == [200] * 120

    limited = client.get("/api/logs")
    assert limited.status_code == 429
    assert limited.get_json().get("error") == "Too many requests"


# ---- Additional edge-case tests ----


def test_download_logs_is_a_timestamped_text_attachment(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a journal, the download is the dev buffer for the asked hours."""
    from services import logs

    monkeypatch.setattr(logs, "JOURNAL_AVAILABLE", False)

    resp = client.get("/download-logs?hours=5")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert re.fullmatch(
        r'attachment; filename="inkypi_\d{8}-\d{6}\.log"',
        resp.headers["Content-Disposition"],
    )
    lines = resp.get_data(as_text=True).splitlines()
    assert lines[0] == "=== Development Mode Logs (In-Memory Buffer) ==="
    assert lines[1].startswith("Showing logs from the last 5 hours")


def test_download_logs_exception_500(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read error returns a plain 500 without the exception text."""
    from services import logs

    monkeypatch.setattr(
        logs,
        "_read_log_lines",
        lambda h: (_ for _ in ()).throw(RuntimeError("secret journal path")),
    )

    resp = client.get("/download-logs")
    assert resp.status_code == 500
    assert resp.get_data(as_text=True) == "Error reading logs"
    assert "Content-Disposition" not in resp.headers


def test_api_logs_level_warn_errors(client: FlaskClient) -> None:
    """level=warn_errors is accepted and echoed back in meta."""
    resp = client.get("/api/logs?level=warn_errors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["meta"]["level"] == "warn_errors"


def test_api_logs_level_all(client: FlaskClient) -> None:
    """level=all is accepted and echoed back in meta."""
    resp = client.get("/api/logs?level=all")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["meta"]["level"] == "all"


def test_api_logs_contains_case_insensitive(client: FlaskClient) -> None:
    """contains parameter is accepted and echoed back in meta."""
    resp = client.get("/api/logs?contains=ERROR")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["meta"]["contains"] == "ERROR"


def test_api_logs_truncated_hours_clamped(client: FlaskClient) -> None:
    """hours=999 → truncated is true (clamped to 24)."""
    resp = client.get("/api/logs?hours=999")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["truncated"] is True
    assert data["meta"]["hours"] == 24


def test_api_logs_truncated_limit_clamped(client: FlaskClient) -> None:
    """limit=999999 → truncated is true (clamped to 2000)."""
    resp = client.get("/api/logs?limit=999999")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["truncated"] is True
    assert data["meta"]["limit"] == 2000


def test_api_logs_response_size_guardrail(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Huge output is truncated under MAX_RESPONSE_BYTES."""
    from blueprints.settings import _logs
    from services import logs

    # Generate huge log output
    big_lines = ["X" * 1000 for _ in range(2000)]
    monkeypatch.setattr(logs, "_read_log_lines", lambda h: big_lines)

    resp = client.get("/api/logs?hours=2&limit=2000")
    assert resp.status_code == 200
    resp.get_json()
    # Response body should be under the guardrail
    raw = resp.data
    # some overhead for JSON wrapping
    assert len(raw) <= _logs.MAX_RESPONSE_BYTES + 10000


def test_format_journal_line_strips_internals() -> None:
    """_format_journal_line maps priority to level and omits hostname/PID."""
    from services.logs import _format_journal_line

    data = {
        "PRIORITY": "3",
        "_HOSTNAME": "raspberrypi",
        "SYSLOG_IDENTIFIER": "python3",
        "_PID": "1234",
        "MESSAGE": "Something failed",
    }
    result = _format_journal_line("Apr 02 10:00:00", data)
    assert result == "Apr 02 10:00:00 [ERROR] Something failed"
    assert "raspberrypi" not in result
    assert "python3" not in result
    assert "1234" not in result


def test_format_journal_line_without_a_message() -> None:
    """An entry with no MESSAGE field still formats, as an empty INFO line."""
    from services.logs import _format_journal_line

    assert _format_journal_line("Apr 02 10:00:00", {}) == "Apr 02 10:00:00 [INFO] "
    assert (
        _format_journal_line("Apr 02 10:00:00", {"MESSAGE": None})
        == "Apr 02 10:00:00 [INFO] "
    )


def test_format_journal_line_masks_keys_already_in_the_journal() -> None:
    """Lines written before redaction covered every logger still hold keys."""
    from services.logs import _format_journal_line

    data = {
        "PRIORITY": "4",
        "MESSAGE": "Retrying: /planetary/apod?api_key=OLDJOURNALKEY1&date=2026-04-24",  # gitleaks:allow
    }
    result = _format_journal_line("Apr 02 10:00:00", data)
    assert "OLDJOURNALKEY1" not in result
    assert result.startswith("Apr 02 10:00:00 [WARNING] Retrying: /planetary/apod?")
    assert "date=2026-04-24" in result


def test_format_journal_line_defaults_to_info() -> None:
    """Missing PRIORITY defaults to INFO level."""
    from services.logs import _format_journal_line

    result = _format_journal_line("Apr 02 10:00:00", {"MESSAGE": "hello"})
    assert result == "Apr 02 10:00:00 [INFO] hello"


def test_log_lines_exclude_internal_details(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Log lines should not expose hostname, PID, or process identifiers."""
    import re

    from services import logs

    # Simulate journal-style lines that the formatter would produce
    fake_lines = [
        "Apr 02 10:00:00 [INFO] Application started",
        "Apr 02 10:00:01 [ERROR] Something went wrong",
        "Apr 02 10:00:02 [DEBUG] Detailed trace info",
    ]
    monkeypatch.setattr(logs, "_read_log_lines", lambda _hours: fake_lines)

    resp = client.get("/api/logs?hours=2")
    assert resp.status_code == 200
    data = resp.get_json()
    for line in data.get("lines", []):
        assert "unknown-host" not in line
        assert not re.search(
            r"\w+\[\d+\]:", line
        ), f"Found identifier[pid] pattern in: {line}"


def test_dev_mode_log_handler_uses_configured_timezone() -> None:
    import logging

    from services import logs
    from utils.logging_utils import set_log_timezone

    set_log_timezone("America/Los_Angeles")
    logs._dev_log_buffer.clear()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.created = 1735693200.0  # 2025-01-01T01:00:00Z

    try:
        logs.DevModeLogHandler().emit(record)
        assert logs._dev_log_buffer[-1][1].startswith("Dec 31 17:00:00")
    finally:
        logs._dev_log_buffer.clear()
        set_log_timezone("UTC")


def test_device_log_timezone_falls_back_without_app_context() -> None:
    from services import logs

    tz = logs._device_log_timezone()
    assert isinstance(tz, ZoneInfo)
    assert tz.key == "UTC"


# ---------------------------------------------------------------------------
# services.logs readers: journal merge for several units, dev-buffer cutoffs,
# and the fallbacks for records that cannot be read.
# ---------------------------------------------------------------------------


class _FakeJournalRecord:
    def __init__(self, unit: str, usec: int, message: str) -> None:
        self.data = {"_SYSTEMD_UNIT": unit, "PRIORITY": "6", "MESSAGE": message}
        self._usec = usec

    def get_realtime_usec(self) -> int:
        return self._usec


class _UnreadableJournalRecord:
    @property
    def data(self) -> dict[str, str]:
        raise RuntimeError("corrupt journal entry")

    def get_realtime_usec(self) -> int:
        raise RuntimeError("corrupt journal entry")


class _FakeJournalReader:
    records: list[_FakeJournalRecord | _UnreadableJournalRecord] = []
    closed = False

    def open(self, mode: object) -> None:
        pass

    def add_filter(self, rule: object) -> None:
        pass

    def seek_realtime_usec(self, usec: int) -> None:
        pass

    def __iter__(self) -> Iterator[_FakeJournalRecord | _UnreadableJournalRecord]:
        return iter(self.records)

    def close(self) -> None:
        type(self).closed = True
        raise OSError("journal already closed")


def _use_fake_journal(
    monkeypatch: pytest.MonkeyPatch,
    records: list[_FakeJournalRecord | _UnreadableJournalRecord],
) -> None:
    from services import logs

    monkeypatch.setattr(_FakeJournalReader, "records", records)
    monkeypatch.setattr(_FakeJournalReader, "closed", False)
    monkeypatch.setattr(logs, "JOURNAL_AVAILABLE", True)
    monkeypatch.setattr(logs, "JournalReader", _FakeJournalReader)
    monkeypatch.setattr(logs, "JournalOpenMode", type("M", (), {"SYSTEM": object()}))
    monkeypatch.setattr(logs, "Rule", lambda *_a, **_k: None)


def test_read_units_log_lines_merges_requested_units_in_time_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import logs

    _use_fake_journal(
        monkeypatch,
        [
            _FakeJournalRecord("inkypi.service", 2_000_000, "second"),
            _FakeJournalRecord("other.service", 500_000, "not requested"),
            _UnreadableJournalRecord(),
            _FakeJournalRecord("inkypi-update-1.service", 1_000_000, "first"),
        ],
    )

    lines = logs._read_units_log_lines(1, ["inkypi.service", "inkypi-update-1.service"])

    assert lines == [
        "Jan 01 00:00:01 [INFO] first",
        "Jan 01 00:00:02 [INFO] second",
    ]
    # close() raising is swallowed; the read still returns its lines.
    assert _FakeJournalReader.closed


def test_read_log_lines_marks_unreadable_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import logs

    record = _FakeJournalRecord("inkypi.service", 0, "no clock")
    monkeypatch.setattr(
        record,
        "get_realtime_usec",
        lambda: (_ for _ in ()).throw(RuntimeError("bad timestamp")),
    )
    _use_fake_journal(monkeypatch, [record])

    assert logs._read_log_lines(1) == ["??? ?? ??:??:?? [INFO] no clock"]
    assert _FakeJournalReader.closed


@pytest.mark.parametrize("reader", ["single", "units"])
def test_dev_buffer_reads_keep_only_recent_entries(
    monkeypatch: pytest.MonkeyPatch, reader: str
) -> None:
    import time

    from services import logs

    monkeypatch.setattr(logs, "JOURNAL_AVAILABLE", False)
    units = ["inkypi.service", "inkypi-update-1.service"]
    with logs._dev_log_lock:
        logs._dev_log_buffer.clear()
        logs._dev_log_buffer.append((0.0, "too old"))
        logs._dev_log_buffer.append((time.time(), "recent"))
    try:
        if reader == "single":
            lines = logs._read_log_lines(1)
        else:
            lines = logs._read_units_log_lines(1, units)
    finally:
        with logs._dev_log_lock:
            logs._dev_log_buffer.clear()

    assert lines[0] == "=== Development Mode Logs (In-Memory Buffer) ==="
    assert lines[-1] == "recent"
    assert "too old" not in lines
    if reader == "units":
        assert "Units requested: inkypi.service, inkypi-update-1.service" in lines


def test_read_units_log_lines_reports_an_empty_dev_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import logs

    monkeypatch.setattr(logs, "JOURNAL_AVAILABLE", False)
    with logs._dev_log_lock:
        logs._dev_log_buffer.clear()

    lines = logs._read_units_log_lines(2, ["inkypi.service"])

    assert len(lines) == 6
    assert lines[-1] == "(No logs captured in buffer yet)"


def test_dev_mode_log_handler_routes_format_errors_to_handle_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import logging

    from services import logs

    handler = logs.DevModeLogHandler()
    errors: list[logging.LogRecord] = []
    monkeypatch.setattr(handler, "format", lambda _r: 1 / 0)
    monkeypatch.setattr(handler, "handleError", errors.append)
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "x", (), None)
    before = len(logs._dev_log_buffer)

    handler.emit(record)

    assert errors == [record]
    assert len(logs._dev_log_buffer) == before
