"""JSON log formatter and secret-redaction filter for structured logging.

JSON formatter enabled via INKYPI_LOG_FORMAT=json.  Default behaviour is
unchanged (plain-text via logging.conf).

SecretRedactionFilter (JTN-364) is wired to the root logger in
app_setup.logging_setup so it applies to all handlers and both log formats.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

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

# Sensitive key names used in pattern 0.
_SECRET_KEY_NAMES = r"api[_-]?key|token|password|secret|pin"

# Compiled once at import time for efficiency.
#
# Pattern ordering matters:
#   0. Bearer tokens FIRST — before the key/value pattern consumes "authorization".
#   1. Key/value pairs: api_key=..., token: "...", password=..., etc.
#   2. Raw 32+ hex strings (likely API keys / hashes).
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # Bearer tokens (full value up to whitespace or end-of-string).
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._+/=-]+)"),
    # Key/value pairs — secret keyword followed by separator and value.
    # "authorization" deliberately excluded here; its value is caught by the
    # Bearer pattern above.
    re.compile(
        r"(?i)(" + _SECRET_KEY_NAMES + r")" r'(["\']?\s*[:=]\s*["\']?)([^\s"\'`,}]+)',
    ),
    # Raw 32+ hex strings (likely API keys / hashes).
    re.compile(r"(?i)\b([a-f0-9]{32,})\b"),
]


def _redact(text: str) -> str:
    """Apply all secret patterns to *text* and return the sanitised string."""
    # Pattern 0: Bearer <token> — keep "Bearer ", replace token.
    text = _SECRET_PATTERNS[0].sub(r"\1" + _REDACTED, text)
    # Pattern 1: key=value — keep key + separator, replace only the value.
    text = _SECRET_PATTERNS[1].sub(r"\1\2" + _REDACTED, text)
    # Pattern 2: bare 32+ hex strings.
    return _SECRET_PATTERNS[2].sub(_REDACTED, text)


def redact_secrets(value: object) -> str:
    """Return a string form of *value* with known secret patterns masked.

    Public sanitizer for call sites that need to log values potentially
    derived from user-supplied settings (e.g. ``template_params`` dicts that
    CodeQL flags as sensitive sources). Non-string inputs are coerced with
    ``str()`` before redaction.
    """
    return _redact(value if isinstance(value, str) else str(value))


def _redact_value(value: object) -> object:
    """Redact *value* if it is a string; leave all other types untouched."""
    if isinstance(value, str):
        return _redact(value)
    return value


class SecretRedactionFilter(logging.Filter):
    """logging.Filter that masks secrets in every log record.

    Applies to:
    * record.msg  (the raw format string)
    * record.args (positional / keyword args interpolated into msg)

    The filter is attached to the root logger in setup_logging() so it runs
    before any handler formats the record, covering both plain-text and JSON
    output.

    .. note::
        The filter operates on a *shallow copy* of record.args so the
        original caller's objects are never mutated.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the message template.
        if isinstance(record.msg, str):
            record.msg = _redact(record.msg)

        # Redact args (used for %-style interpolation).
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_value(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _redact_value(v) for k, v in record.args.items()}

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


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    Field names follow the spec (JTN-337):
      ts, level, logger, msg, module, func, line, pid

    Exception records gain: exc_type, exc_message, exc_traceback.
    Caller-supplied extras appear under the top-level "extra" key.
    Non-serialisable values are stringified via *default=str*.
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
        payload = self._build_payload(record)
        return json.dumps(payload, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _build_payload(self, record: logging.LogRecord) -> dict[str, Any]:
        ts = datetime.fromtimestamp(record.created, tz=UTC).isoformat()

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
