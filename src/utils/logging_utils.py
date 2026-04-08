"""JSON log formatter for structured logging (JTN-337).

Enabled via INKYPI_LOG_FORMAT=json.  Default behaviour is unchanged
(plain-text via logging.conf).
"""

from __future__ import annotations

import json
import logging
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
