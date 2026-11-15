"""JSON log formatter and secret-redaction filter for structured logging.

JSON formatter enabled via INKYPI_LOG_FORMAT=json.  Default behaviour is
unchanged (plain-text via logging.conf).

SecretRedactionFilter (JTN-364) is attached to every handler in
app_setup.logging_setup. A filter on the root *logger* would only see records
logged on the root logger itself; Python skips logger filters for records that
propagate up from child loggers (``plugins.*``, ``urllib3.connectionpool``...),
so the filter must sit on the handlers to see everything.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# All keys that exist on a bare LogRecord.  Extras are anything in
# record.__dict__ that is NOT in this set and does NOT start with "_".
_LOGRECORD_BUILTIN_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",  # Python 3.12+
        "message",  # set by Formatter.format() before our call; exclude it
    }
)


_REDACTED = "***REDACTED***"
_LOG_TIMEZONE: tzinfo = UTC

# Sensitive key names used in the key/value pattern.
_SECRET_KEY_NAMES = (
    r"api[_-]?key|access[_-]?key|client[_-]?id|app[_-]?id|token|password|secret|pin"
)

# Query parameters that carry credentials under a generic name. Only matched
# right after ``?`` or ``&`` so ordinary words like "key" are left alone.
_SECRET_QUERY_PARAMS = r"key|sig|signature|auth|code"

# Compiled once at import time for efficiency.
#
# Pattern ordering matters:
#   1. Bearer / Client-ID tokens before the key/value pattern consumes
#      "authorization".
#   2. Query parameters, so a key in a URL is masked up to the next ``&``
#      and the rest of the URL stays readable.
#   3. Key/value pairs: api_key=..., token: "...", password=..., etc. Values
#      already masked by step 2 are skipped.
#   4. Raw 32+ hex strings (likely API keys / hashes).
_TOKEN_PATTERN = re.compile(r"(?i)((?:bearer|client-id)\s+)([A-Za-z0-9._+/=-]+)")
_QUERY_PATTERN = re.compile(
    r"(?i)([?&](?:[\w.-]*?(?:"
    + _SECRET_KEY_NAMES
    + r")|"
    + _SECRET_QUERY_PARAMS
    + r")=)[^&\s\"'#]+"
)
# "authorization" is deliberately not a key name here; its value is caught by
# the token pattern above.
_KEY_VALUE_PATTERN = re.compile(
    r"(?i)(" + _SECRET_KEY_NAMES + r")"
    r'(["\']?\s*[:=]\s*["\']?)'
    r"(?!" + re.escape(_REDACTED) + r")"
    r'([^\s"\'`,}]+)',
)
_HEX_PATTERN = re.compile(r"(?i)\b([a-f0-9]{32,})\b")


def _redact(text: str) -> str:
    """Apply all secret patterns to *text* and return the sanitised string."""
    text = _TOKEN_PATTERN.sub(r"\1" + _REDACTED, text)
    text = _QUERY_PATTERN.sub(r"\1" + _REDACTED, text)
    text = _KEY_VALUE_PATTERN.sub(r"\1\2" + _REDACTED, text)
    return _HEX_PATTERN.sub(_REDACTED, text)


def redact_secrets(value: object) -> str:
    """Return a string form of *value* with known secret patterns masked.

    Public sanitizer for call sites that need to log values potentially
    derived from user-supplied settings (e.g. ``template_params`` dicts that
    CodeQL flags as sensitive sources). Non-string inputs are coerced with
    ``str()`` before redaction.
    """
    return _redact(value if isinstance(value, str) else str(value))


def set_log_timezone(tz_name: str | None) -> tzinfo:
    """Set the timezone used by structured log timestamps.

    Plain-text logging uses the process ``TZ`` setting configured in
    ``app_setup.logging_setup``. JSON logs do their own timestamp formatting,
    so they keep a small module-level timezone instead.
    """
    global _LOG_TIMEZONE
    try:
        _LOG_TIMEZONE = ZoneInfo(str(tz_name)) if tz_name else UTC
    except (ZoneInfoNotFoundError, ValueError):
        _LOG_TIMEZONE = UTC
    return _LOG_TIMEZONE


def log_datetime_from_timestamp(created: float) -> datetime:
    """Return a log timestamp in the configured device timezone."""
    return datetime.fromtimestamp(created, tz=_LOG_TIMEZONE)


class SecretRedactionFilter(logging.Filter):
    """logging.Filter that masks secrets in every log record.

    Attach it to *handlers* (see ``app_setup.logging_setup``): handler filters
    run for every record the handler emits, including those propagated from
    child loggers, while a filter on the root logger only sees records logged
    on the root logger itself.

    Covers:
    * the rendered message (``msg % args``), so secrets inside exception
      objects or other non-string arguments are caught as well as strings;
    * the exception traceback text and ``stack_info``;
    * string-valued extras attached by callers.

    A record is only rewritten when redaction changes something; then its
    message is stored pre-rendered (``args`` emptied) so the masked text is
    what every handler formats.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            # Bad format arguments: leave the record for the handler to
            # report rather than hiding the logging error.
            message = None
        if message is not None:
            redacted = _redact(message)
            if redacted != message:
                record.msg = redacted
                record.args = ()

        if record.exc_info and not record.exc_text:
            exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = _redact(exc_text)
        elif record.exc_text:
            record.exc_text = _redact(record.exc_text)
        if record.stack_info:
            record.stack_info = _redact(record.stack_info)

        # Redact any string-valued extras attached by callers.
        builtin_plus = _LOGRECORD_BUILTIN_KEYS | {"message"}
        for key, val in record.__dict__.items():
            if (
                key not in builtin_plus
                and not key.startswith("_")
                and isinstance(val, str)
            ):
                setattr(record, key, _redact(val))

        return True  # always pass the record through


def _redact_tree(value: Any) -> Any:
    """Return a JSON-ready copy of *value* with every string masked.

    Values JSON can't encode are stringified first, as ``default=str`` would.
    """
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, dict):
        return {key: _redact_tree(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_tree(item) for item in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return _redact(str(value))


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    Field names follow the spec (JTN-337):
      ts, level, logger, msg, module, func, line, pid

    Exception records gain: exc_type, exc_message, exc_traceback.
    Caller-supplied extras appear under the top-level "extra" key.
    Non-serialisable values are stringified, and every string is masked
    for secrets.
    """

    def __init__(
        self,
        *,
        default_fields: dict[str, Any] | None = None,
        datefmt: str | None = None,
    ) -> None:
        super().__init__(datefmt=datefmt)
        self.default_fields: dict[str, Any] = default_fields or {}

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def format(self, record: logging.LogRecord) -> str:
        # Exception messages and tracebacks are rebuilt from exc_info here,
        # so mask every field again, before encoding (masking the encoded
        # line could cut through a JSON escape).
        payload = _redact_tree(self._build_payload(record))
        return json.dumps(payload, ensure_ascii=False)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _build_payload(self, record: logging.LogRecord) -> dict[str, Any]:
        ts = log_datetime_from_timestamp(record.created).isoformat()

        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "pid": record.process,
        }

        # Stable, user-supplied defaults (e.g. {"host": "pi-zero"})
        payload.update(self.default_fields)

        # Exception info
        if record.exc_info:
            exc_type, exc_value, tb = record.exc_info
            payload["exc_type"] = exc_type.__name__ if exc_type is not None else None
            payload["exc_message"] = str(exc_value) if exc_value is not None else None
            payload["exc_traceback"] = self.formatException(record.exc_info)

        # Stack info (rare, but respect it)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        # Caller-supplied extras
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _LOGRECORD_BUILTIN_KEYS and not k.startswith("_")
        }
        if extras:
            payload["extra"] = extras

        return payload
