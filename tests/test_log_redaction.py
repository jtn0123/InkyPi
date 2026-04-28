"""Tests for SecretRedactionFilter (JTN-364).

Covers:
* api_key=value style secrets
* Bearer token redaction
* 32+ hex-string redaction
* Mixed sentences — only the secret portion is redacted
* Records WITHOUT secrets pass through unchanged
* Both plain-text (str) and JSON formatter output
* record.args (positional tuple and keyword dict)
* Extra attributes attached by callers
"""

from __future__ import annotations

import json
import logging

from utils.logging_utils import JsonFormatter, SecretRedactionFilter, _redact

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_record(
    msg: str,
    args: tuple | None = None,
    **extras: object,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args or (),
        exc_info=None,
    )
    for k, v in extras.items():
        setattr(record, k, v)
    return record


def _apply(record: logging.LogRecord) -> logging.LogRecord:
    """Run the filter on *record* and return it."""
    SecretRedactionFilter().filter(record)
    return record


# ---------------------------------------------------------------------------
# Unit tests for the _redact() helper
# ---------------------------------------------------------------------------


class TestRedactHelper:
    def test_api_key_equals(self):
        result = _redact("api_key=abc123def456")  # gitleaks:allow
        assert "abc123def456" not in result
        assert "***REDACTED***" in result
        assert "api_key" in result

    def test_token_colon(self):
        result = _redact('token: "mysecrettoken"')
        assert "mysecrettoken" not in result
        assert "***REDACTED***" in result

    def test_password_equals(self):
        result = _redact("password=hunter2")
        assert "hunter2" not in result
        assert "***REDACTED***" in result

    def test_pin_equals(self):
        result = _redact("pin=1234")
        assert "1234" not in result
        assert "***REDACTED***" in result

    def test_bearer_token(self):
        result = _redact("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.sig")
        assert "eyJhbGciOiJSUzI1NiJ9" not in result
        assert "***REDACTED***" in result
        # The word "Bearer" itself (or "Bearer ***REDACTED***") should remain
        assert "Bearer" in result

    def test_hex_32_chars_redacted(self):
        hex_key = "a" * 32
        result = _redact(f"here is a key: {hex_key}")
        assert hex_key not in result
        assert "***REDACTED***" in result

    def test_hex_31_chars_not_redacted(self):
        short_hex = "a" * 31
        result = _redact(f"value: {short_hex}")
        # 31-char hex should NOT be treated as a secret
        assert short_hex in result

    def test_normal_text_unchanged(self):
        clean = "Starting server on port 8080"
        assert _redact(clean) == clean

    def test_mixed_sentence_only_secret_redacted(self):
        text = "User logged in successfully; api_key=TOPSECRETKEY123 from 192.168.1.1"  # gitleaks:allow
        result = _redact(text)
        assert "User logged in successfully" in result
        assert "192.168.1.1" in result
        assert "TOPSECRETKEY123" not in result


# ---------------------------------------------------------------------------
# Filter applied to LogRecord
# ---------------------------------------------------------------------------


class TestSecretRedactionFilter:
    def test_msg_redacted(self):
        record = _apply(_make_record("api_key=abc123def456"))  # gitleaks:allow
        assert "abc123def456" not in record.msg
        assert "***REDACTED***" in record.msg

    def test_clean_msg_unchanged(self):
        record = _apply(_make_record("No secrets here, just info"))
        assert record.msg == "No secrets here, just info"

    def test_args_tuple_redacted(self):
        # The arg itself contains a key=value pattern that should be redacted.
        record = _apply(_make_record("config: %s", args=("password=hunter2",)))
        assert all("hunter2" not in str(a) for a in record.args)

    def test_args_tuple_non_string_untouched(self):
        record = _apply(_make_record("count=%d", args=(42,)))
        assert record.args == (42,)

    def test_args_tuple_bearer_redacted(self):
        record = _apply(
            _make_record("header: %s", args=("Bearer eyJhbGciOiJSUzI1NiJ9.abc.def",))
        )
        assert all("eyJhbGciOiJSUzI1NiJ9" not in str(a) for a in record.args)

    def test_extra_string_attribute_with_secret_redacted(self):
        # Extra attribute contains a key=value pair — the value is redacted.
        auth = "api_key=SECRETKEYVALUE"  # gitleaks:allow
        record = _apply(_make_record("check extras", auth_info=auth))
        assert record.auth_info == "api_key=***REDACTED***"  # type: ignore[attr-defined]

    def test_extra_non_string_attribute_untouched(self):
        record = _apply(_make_record("check extras", request_id=999))
        assert record.request_id == 999  # type: ignore[attr-defined]

    def test_filter_always_returns_true(self):
        """Filter must never drop records."""
        msg = "api_key=xyz"  # gitleaks:allow
        result = SecretRedactionFilter().filter(_make_record(msg))
        assert result is True

    def test_authorization_header_redacted(self):
        record = _apply(
            _make_record("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.sig")
        )
        assert "eyJhbGciOiJSUzI1NiJ9" not in record.msg

    def test_password_in_record_redacted(self):
        record = _apply(_make_record("Password: hunter2"))
        assert "hunter2" not in record.msg
        assert "***REDACTED***" in record.msg


# ---------------------------------------------------------------------------
# Plain-text (str) formatter output
# ---------------------------------------------------------------------------


class TestPlainTextOutput:
    def test_formatted_message_redacted_via_msg(self):
        # Secret is in the msg template itself (already fully interpolated).
        record = _make_record("api_key=MYSECRETAPIKEY123")  # gitleaks:allow
        SecretRedactionFilter().filter(record)
        formatted = record.getMessage()
        assert "MYSECRETAPIKEY123" not in formatted
        assert "***REDACTED***" in formatted

    def test_formatted_message_redacted_via_args(self):
        # Secret is in a %s arg that itself contains a key=value pattern.
        record = _make_record("config dump: %s", args=("password=hunter2",))
        SecretRedactionFilter().filter(record)
        formatted = record.getMessage()
        assert "hunter2" not in formatted
        assert "***REDACTED***" in formatted

    def test_clean_formatted_message_unchanged(self):
        record = _make_record("Server started on %s", args=("localhost:8080",))
        SecretRedactionFilter().filter(record)
        assert record.getMessage() == "Server started on localhost:8080"


# ---------------------------------------------------------------------------
# JSON formatter output
# ---------------------------------------------------------------------------


class TestJsonFormatterOutput:
    def test_secret_in_msg_redacted_in_json(self):
        record = _make_record("api_key=SUPERSECRET")  # gitleaks:allow
        SecretRedactionFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
        assert "SUPERSECRET" not in data["msg"]
        assert "***REDACTED***" in data["msg"]

    def test_clean_msg_in_json_unchanged(self):
        record = _make_record("All systems nominal")
        SecretRedactionFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
        assert data["msg"] == "All systems nominal"

    def test_secret_extra_redacted_in_json(self):
        # Extra attribute contains a key=value string — value gets redacted.
        record = _make_record("request", auth_header="token=BEARER_TOKEN_VALUE_HERE")
        SecretRedactionFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
        assert "BEARER_TOKEN_VALUE_HERE" not in json.dumps(data)

    def test_bearer_in_json_redacted(self):
        record = _make_record("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.abc.def")
        SecretRedactionFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
        assert "eyJhbGciOiJSUzI1NiJ9" not in data["msg"]
        assert "***REDACTED***" in data["msg"]

    def test_hex_key_in_json_redacted(self):
        hex_key = "deadbeef" * 4  # 32 chars
        record = _make_record(f"loaded config key={hex_key}")
        SecretRedactionFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
        assert hex_key not in data["msg"]


# ---------------------------------------------------------------------------
# setup_logging() wires the filter
# ---------------------------------------------------------------------------


class TestSetupLoggingWiresFilter:
    def test_root_logger_has_redaction_filter_after_setup(self, monkeypatch):
        monkeypatch.setenv("INKYPI_LOG_FORMAT", "json")
        root = logging.getLogger()
        saved_handlers = root.handlers[:]
        saved_filters = root.filters[:]
        saved_level = root.level
        root.handlers = []
        root.filters = []
        try:
            from app_setup.logging_setup import setup_logging

            setup_logging()
            filter_types = [type(f) for f in logging.getLogger().filters]
            assert SecretRedactionFilter in filter_types
        finally:
            root.handlers = saved_handlers
            root.filters = saved_filters
            root.level = saved_level

    def test_expected_sse_disconnect_filter_drops_waitress_noise(self):
        from app_setup.logging_setup import ExpectedSSEDisconnectFilter

        flt = ExpectedSSEDisconnectFilter()

        progress = _make_record(
            "Client disconnected while serving /api/progress/stream"
        )
        events = _make_record("Client disconnected while serving /api/events")
        other = _make_record("Client disconnected while serving /settings")

        assert flt.filter(progress) is False
        assert flt.filter(events) is False
        assert flt.filter(other) is True

    def test_root_logger_has_redaction_filter_plain_text(self, monkeypatch, tmp_path):
        """Filter is wired for plain-text mode too."""
        monkeypatch.delenv("INKYPI_LOG_FORMAT", raising=False)
        root = logging.getLogger()
        saved_handlers = root.handlers[:]
        saved_filters = root.filters[:]
        saved_level = root.level
        root.handlers = []
        root.filters = []
        try:
            from app_setup.logging_setup import setup_logging

            setup_logging()
            filter_types = [type(f) for f in logging.getLogger().filters]
            assert SecretRedactionFilter in filter_types
        finally:
            root.handlers = saved_handlers
            root.filters = saved_filters
            root.level = saved_level
