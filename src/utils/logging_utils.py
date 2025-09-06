import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Set


_DEFAULT_LOGRECORD_KEYS: Set[str] = {
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
}


class JsonFormatter(logging.Formatter):
    def __init__(self, *, default_fields: Dict[str, Any] | None = None, datefmt: str | None = None):
        super().__init__(datefmt=datefmt)
        self.default_fields = default_fields or {}

    def format(self, record: logging.LogRecord) -> str:
        payload = self._record_to_dict(record)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, default=self._stringify)

    def _record_to_dict(self, record: logging.LogRecord) -> Dict[str, Any]:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        data: Dict[str, Any] = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "thread": record.thread,
        }
        data.update(self.default_fields)

        extras: Dict[str, Any] = {}
        for k, v in record.__dict__.items():
            if k not in _DEFAULT_LOGRECORD_KEYS and not k.startswith("_"):
                extras[k] = v
        if extras:
            data["extra"] = extras
        return data

    @staticmethod
    def _stringify(obj: Any) -> str:
        try:
            return str(obj)
        except Exception:
            return "<unserializable>"


