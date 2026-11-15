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
* Tracebacks, credential query parameters and Client-ID headers
* setup_logging() masks records from child loggers on every handler
"""

from __future__ import annotations

import io
import json
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

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
    def test_api_key_equals(self) -> None:
        result = _redact("api_key=abc123def456")  # gitleaks:allow
        assert "abc123def456" not in result
        assert "***REDACTED***" in result
        assert "api_key" in result

    def test_token_colon(self) -> None:
        result = _redact('token: "mysecrettoken"')
        assert "mysecrettoken" not in result
        assert "***REDACTED***" in result

    def test_password_equals(self) -> None:
        result = _redact("password=hunter2")
        assert "hunter2" not in result
        assert "***REDACTED***" in result

    def test_pin_equals(self) -> None:
        result = _redact("pin=1234")
        assert "1234" not in result
        assert "***REDACTED***" in result

    def test_bearer_token(self) -> None:
        result = _redact("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.sig")
        assert "eyJhbGciOiJSUzI1NiJ9" not in result
        assert "***REDACTED***" in result
        # The word "Bearer" itself (or "Bearer ***REDACTED***") should remain
        assert "Bearer" in result

    def test_hex_32_chars_redacted(self) -> None:
        hex_key = "a" * 32
        result = _redact(f"here is a key: {hex_key}")
        assert hex_key not in result
        assert "***REDACTED***" in result

    def test_hex_31_chars_not_redacted(self) -> None:
        short_hex = "a" * 31
        result = _redact(f"value: {short_hex}")
        # 31-char hex should NOT be treated as a secret
        assert short_hex in result

    def test_normal_text_unchanged(self) -> None:
        clean = "Starting server on port 8080"
        assert _redact(clean) == clean

    @pytest.mark.parametrize(
        "template",
        [
            "refresh_info: {{'plugin_id': 'clock', 'image_hash': '{h}'}}",
            'refresh_info: {{"image_hash": "{h}"}}',
            "display skipped, image_hash={h}",
        ],
    )
    def test_labelled_image_hash_is_kept(self, template: str) -> None:
        """The frame's SHA-256 is what tells two refreshes apart in the log."""
        sha256 = "3f" * 32
        text = template.format(h=sha256)
        assert _redact(text) == text

    @pytest.mark.parametrize(
        "text",
        [
            # A key with an image_hash label but a key's length.
            "image_hash=" + "ab" * 16,
            # A SHA-256-length value under any other label.
            "content_hash=" + "3f" * 32,
            "secret_image_hash=" + "3f" * 32,
            # An unlabelled one.
            "frame " + "3f" * 32,
        ],
    )
    def test_other_long_hex_is_still_masked(self, text: str) -> None:
        assert "***REDACTED***" in _redact(text)

    def test_mixed_sentence_only_secret_redacted(self) -> None:
        text = "User logged in successfully; api_key=TOPSECRETKEY123 from 192.168.1.1"  # gitleaks:allow
        result = _redact(text)
        assert "User logged in successfully" in result
        assert "192.168.1.1" in result
        assert "TOPSECRETKEY123" not in result

    @pytest.mark.parametrize(
        ("text", "secret", "kept"),
        [
            (
                "GET /planetary/apod?api_key=NASAKEY1234567890XYZ&date=2026-04-24",  # gitleaks:allow
                "NASAKEY1234567890XYZ",
                "date=2026-04-24",
            ),
            (
                "onecall?lat=1&lon=2&appid=OWMAPPID12345&units=metric",  # gitleaks:allow
                "OWMAPPID12345",
                "units=metric",
            ),
            (
                "photos/random?client_id=UNSPLASHKEY987&per_page=100",  # gitleaks:allow
                "UNSPLASHKEY987",
                "per_page=100",
            ),
            (
                "maps/api?key=GOOGLEKEY555&zoom=3",  # gitleaks:allow
                "GOOGLEKEY555",
                "zoom=3",
            ),
            (
                "{'Authorization': 'Client-ID UNSPLASHKEY987'}",  # gitleaks:allow
                "UNSPLASHKEY987",
                "Authorization",
            ),
        ],
        ids=["api_key", "appid", "client_id", "key-param", "client-id-header"],
    )
    def test_keys_in_urls_and_headers(self, text: str, secret: str, kept: str) -> None:
        result = _redact(text)
        assert secret not in result
        assert kept in result
        assert "***REDACTED***" in result

    def test_ordinary_words_named_key_are_kept(self) -> None:
        text = "Missing key 'urls' in the response; press any key"
        assert _redact(text) == text


# ---------------------------------------------------------------------------
# Filter applied to LogRecord
# ---------------------------------------------------------------------------


class TestSecretRedactionFilter:
    def test_msg_redacted(self) -> None:
        record = _apply(_make_record("api_key=abc123def456"))  # gitleaks:allow
        assert "abc123def456" not in record.msg
        assert "***REDACTED***" in record.msg

    def test_clean_msg_unchanged(self) -> None:
        record = _apply(_make_record("No secrets here, just info"))
        assert record.msg == "No secrets here, just info"

    def test_args_tuple_redacted(self) -> None:
        # The arg itself contains a key=value pattern that should be redacted.
        record = _apply(_make_record("config: %s", args=("password=hunter2",)))
        assert all("hunter2" not in str(a) for a in record.args)

    def test_args_tuple_non_string_untouched(self) -> None:
        record = _apply(_make_record("count=%d", args=(42,)))
        assert record.args == (42,)

    def test_args_tuple_bearer_redacted(self) -> None:
        record = _apply(
            _make_record("header: %s", args=("Bearer eyJhbGciOiJSUzI1NiJ9.abc.def",))
        )
        assert all("eyJhbGciOiJSUzI1NiJ9" not in str(a) for a in record.args)

    def test_extra_string_attribute_with_secret_redacted(self) -> None:
        # Extra attribute contains a key=value pair — the value is redacted.
        auth = "api_key=SECRETKEYVALUE"  # gitleaks:allow
        record = _apply(_make_record("check extras", auth_info=auth))
        assert record.auth_info == "api_key=***REDACTED***"  # type: ignore[attr-defined]

    def test_extra_non_string_attribute_untouched(self) -> None:
        record = _apply(_make_record("check extras", request_id=999))
        assert record.request_id == 999  # type: ignore[attr-defined]

    def test_filter_always_returns_true(self) -> None:
        """Filter must never drop records."""
        msg = "api_key=xyz"  # gitleaks:allow
        result = SecretRedactionFilter().filter(_make_record(msg))
        assert result is True

    def test_authorization_header_redacted(self) -> None:
        record = _apply(
            _make_record("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.sig")
        )
        assert "eyJhbGciOiJSUzI1NiJ9" not in record.msg

    def test_password_in_record_redacted(self) -> None:
        record = _apply(_make_record("Password: hunter2"))
        assert "hunter2" not in record.msg
        assert "***REDACTED***" in record.msg

    def test_secret_inside_a_non_string_arg_redacted(self) -> None:
        # requests puts the full URL in the exception, which is logged via %s.
        url = "https://x.test/?api_key=FROMEXC123"  # gitleaks:allow
        exc = RuntimeError(f"401 for url: {url}")
        record = _apply(_make_record("Request failed: %s", args=(exc,)))
        assert "FROMEXC123" not in record.getMessage()
        assert record.getMessage().startswith("Request failed: 401 for url:")

    def test_secret_split_across_template_and_arg_redacted(self) -> None:
        record = _apply(_make_record("url=/apod?api_key=%s", args=("SPLITKEY77",)))
        assert "SPLITKEY77" not in record.getMessage()

    def test_traceback_redacted(self) -> None:
        try:
            raise ValueError("https://x.test/?appid=TRACEKEY42")  # gitleaks:allow
        except ValueError:
            record = _make_record("boom")
            record.exc_info = sys.exc_info()
        _apply(record)
        formatted = logging.Formatter().format(record)
        assert "TRACEKEY42" not in formatted
        assert "ValueError" in formatted

    def test_preformatted_traceback_redacted(self) -> None:
        record = _make_record("boom")
        record.exc_text = "Traceback...\nValueError: token=PREFORMATTED9"
        _apply(record)
        assert "PREFORMATTED9" not in record.exc_text

    def test_stack_info_redacted(self) -> None:
        record = _make_record("boom")
        record.stack_info = "Stack (most recent call last):\n  password=STACKPW"
        _apply(record)
        assert "STACKPW" not in record.stack_info

    def test_bad_format_args_are_left_for_the_handler(self) -> None:
        record = _make_record("count=%d", args=("not a number",))
        assert SecretRedactionFilter().filter(record) is True
        assert record.args == ("not a number",)


# ---------------------------------------------------------------------------
# Plain-text (str) formatter output
# ---------------------------------------------------------------------------


class TestPlainTextOutput:
    def test_formatted_message_redacted_via_msg(self) -> None:
        # Secret is in the msg template itself (already fully interpolated) -> None -> None.
        record = _make_record("api_key=MYSECRETAPIKEY123")  # gitleaks:allow
        SecretRedactionFilter().filter(record)
        formatted = record.getMessage()
        assert "MYSECRETAPIKEY123" not in formatted
        assert "***REDACTED***" in formatted

    def test_formatted_message_redacted_via_args(self) -> None:
        # Secret is in a %s arg that itself contains a key=value pattern.
        record = _make_record("config dump: %s", args=("password=hunter2",))
        SecretRedactionFilter().filter(record)
        formatted = record.getMessage()
        assert "hunter2" not in formatted
        assert "***REDACTED***" in formatted

    def test_clean_formatted_message_unchanged(self) -> None:
        record = _make_record("Server started on %s", args=("localhost:8080",))
        SecretRedactionFilter().filter(record)
        assert record.getMessage() == "Server started on localhost:8080"


# ---------------------------------------------------------------------------
# JSON formatter output
# ---------------------------------------------------------------------------


class TestJsonFormatterOutput:
    def test_secret_in_msg_redacted_in_json(self) -> None:
        record = _make_record("api_key=SUPERSECRET")  # gitleaks:allow
        SecretRedactionFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
        assert "SUPERSECRET" not in data["msg"]
        assert "***REDACTED***" in data["msg"]

    def test_clean_msg_in_json_unchanged(self) -> None:
        record = _make_record("All systems nominal")
        SecretRedactionFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
        assert data["msg"] == "All systems nominal"

    def test_secret_extra_redacted_in_json(self) -> None:
        # Extra attribute contains a key=value string — value gets redacted.
        record = _make_record("request", auth_header="token=BEARER_TOKEN_VALUE_HERE")
        SecretRedactionFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
        assert "BEARER_TOKEN_VALUE_HERE" not in json.dumps(data)

    def test_bearer_in_json_redacted(self) -> None:
        record = _make_record("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.abc.def")
        SecretRedactionFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
        assert "eyJhbGciOiJSUzI1NiJ9" not in data["msg"]
        assert "***REDACTED***" in data["msg"]

    def test_exception_message_redacted_in_json_without_filter(self) -> None:
        try:
            raise RuntimeError("401 https://x.test/?api_key=JSONEXC1")  # gitleaks:allow
        except RuntimeError:
            record = _make_record("boom")
            record.exc_info = sys.exc_info()
        line = JsonFormatter().format(record)
        assert "JSONEXC1" not in line
        assert json.loads(line)["exc_type"] == "RuntimeError"

    def test_hex_key_in_json_redacted(self) -> None:
        hex_key = "deadbeef" * 4  # 32 chars
        record = _make_record(f"loaded config key={hex_key}")
        SecretRedactionFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
        assert hex_key not in data["msg"]


# ---------------------------------------------------------------------------
# setup_logging() wires the filter
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_root_logger(monkeypatch: pytest.MonkeyPatch) -> Iterator[logging.Logger]:
    """Give setup_logging() an empty root logger and restore it afterwards."""
    monkeypatch.delenv("INKYPI_LOG_FILE", raising=False)
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_filters = root.filters[:]
    saved_level = root.level
    root.handlers = []
    root.filters = []
    try:
        yield root
    finally:
        for handler in root.handlers:
            if handler not in saved_handlers:
                handler.close()
        root.handlers = saved_handlers
        root.filters = saved_filters
        root.level = saved_level


def _capture_console(root: logging.Logger) -> io.StringIO:
    stream = io.StringIO()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(stream)
    return stream


def _has_redaction(handler: logging.Handler) -> bool:
    return any(isinstance(f, SecretRedactionFilter) for f in handler.filters)


class TestSetupLoggingWiresFilter:
    @pytest.mark.parametrize("log_format", ["json", "plain"])
    def test_every_handler_has_the_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_root_logger: logging.Logger,
        log_format: str,
    ) -> None:
        monkeypatch.setenv("INKYPI_LOG_FORMAT", log_format)
        from app_setup.logging_setup import setup_logging

        setup_logging()
        setup_logging()  # a second call must not stack filters

        assert clean_root_logger.handlers
        for handler in clean_root_logger.handlers:
            redaction = [
                f for f in handler.filters if isinstance(f, SecretRedactionFilter)
            ]
            assert len(redaction) == 1

    @pytest.mark.parametrize("log_format", ["json", "plain"])
    def test_child_logger_secrets_never_reach_the_console(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_root_logger: logging.Logger,
        log_format: str,
    ) -> None:
        """Records from named loggers skip root-logger filters; the handler
        filter must still mask them (the NASA key leaked this way)."""
        monkeypatch.setenv("INKYPI_LOG_FORMAT", log_format)
        from app_setup.logging_setup import setup_logging

        setup_logging()
        stream = _capture_console(clean_root_logger)

        logging.getLogger("urllib3.connectionpool").warning(
            "Retrying after connection broken by '%s': %s",
            "ReadTimeoutError",
            "/planetary/apod?api_key=CHILDKEY123456&date=2026-04-24",  # gitleaks:allow
        )
        try:
            raise RuntimeError(
                "401 Client Error for url: https://api.test/onecall?appid=EXCKEY98765"  # gitleaks:allow
            )
        except RuntimeError:
            logging.getLogger("plugins.weather").exception("Weather refresh failed")

        output = stream.getvalue()
        assert "Retrying after connection broken" in output
        assert "Weather refresh failed" in output
        assert "CHILDKEY123456" not in output
        assert "EXCKEY98765" not in output
        assert "date=2026-04-24" in output

    def test_rotating_file_handler_has_the_filter(
        self, clean_root_logger: logging.Logger, tmp_path: Path
    ) -> None:
        from app_setup.logging_setup import attach_rotating_file_handler

        handler = attach_rotating_file_handler(str(tmp_path / "inkypi.log"))
        assert _has_redaction(handler)

        logging.getLogger("plugins.unsplash").warning(
            "GET /photos/random?client_id=FILEKEY4242"  # gitleaks:allow
        )
        handler.flush()
        written = (tmp_path / "inkypi.log").read_text()
        assert "GET /photos/random" in written
        assert "FILEKEY4242" not in written

    def test_dev_mode_handler_has_the_filter(
        self, clean_root_logger: logging.Logger
    ) -> None:
        from app_setup.logging_setup import install_dev_log_handler
        from services.logs import DevModeLogHandler

        install_dev_log_handler()

        dev_handlers = [
            h for h in clean_root_logger.handlers if isinstance(h, DevModeLogHandler)
        ]
        assert len(dev_handlers) == 1
        assert _has_redaction(dev_handlers[0])

    def test_expected_sse_disconnect_filter_drops_waitress_noise(self) -> None:
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
