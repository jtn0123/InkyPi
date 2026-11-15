# pyright: reportMissingImports=false, reportMissingTypeStubs=false, reportMissingModuleSource=false, reportRedeclaration=false
"""Service log reads: the systemd journal on the Pi, an in-memory buffer in dev.

The logs routes (``blueprints/settings/_logs.py``) and the diagnostics page
read lines through ``_read_log_lines`` / ``_read_units_log_lines``. Off-device
there is no journal, so ``DevModeLogHandler`` keeps recent records in memory
for the same views.
"""

import logging
import threading
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import current_app

from utils.logging_utils import log_datetime_from_timestamp, redact_secrets
from utils.time_utils import get_timezone, now_device_tz

# Try to import cysystemd for journal reading (Linux only)
try:
    from cysystemd.reader import (
        JournalOpenMode,
        JournalReader,
        Rule,
    )

    JOURNAL_AVAILABLE = True
except ImportError:
    JOURNAL_AVAILABLE = False
    # Define dummy classes for when cysystemd is not available
    JournalReader = None
    JournalOpenMode = None
    Rule = None


LOG_TIMESTAMP_FORMAT = "%b %d %H:%M:%S"
_PRIORITY_TO_LEVEL = {
    "0": "CRITICAL",
    "1": "CRITICAL",
    "2": "CRITICAL",
    "3": "ERROR",
    "4": "WARNING",
    "5": "INFO",
    "6": "INFO",
    "7": "DEBUG",
}

# Dev mode in-memory log buffer (circular buffer)
DEV_LOG_BUFFER_SIZE = 1000
_dev_log_buffer: deque[tuple[float, str]] = deque(maxlen=DEV_LOG_BUFFER_SIZE)
_dev_log_lock = threading.Lock()


class DevModeLogHandler(logging.Handler):
    """Captures logs in memory for dev mode log viewing."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            timestamp = log_datetime_from_timestamp(record.created).strftime(
                LOG_TIMESTAMP_FORMAT
            )
            log_line = f"{timestamp} [{record.levelname}] {record.name}: {msg}"
            with _dev_log_lock:
                _dev_log_buffer.append((record.created, log_line))
        except Exception:
            self.handleError(record)


def _format_journal_line(formatted_ts: str, data: dict[str, Any]) -> str:
    priority = str(data.get("PRIORITY", "6"))
    level = _PRIORITY_TO_LEVEL.get(priority, "INFO")
    # Journal entries written before redaction reached every logger, or by
    # other processes in the unit, can still hold keys.
    msg = redact_secrets((data.get("MESSAGE", "") or "").rstrip())
    return f"{formatted_ts} [{level}] {msg}"


def _device_log_timezone() -> Any:
    try:
        device_config = current_app.config["DEVICE_CONFIG"]
        return get_timezone(device_config.get_config("timezone", default="UTC"))
    except Exception:
        return get_timezone("UTC")


def _read_log_lines(hours: int) -> list[str]:
    """Read service logs for the last N hours and return as list of formatted lines."""
    # Use device timezone for consistency in all time computations
    try:
        from flask import current_app

        device_config = current_app.config["DEVICE_CONFIG"]
        since = now_device_tz(device_config) - timedelta(hours=hours)
    except Exception:
        # Fallback to timezone-aware UTC for consistency
        since = datetime.now(tz=get_timezone("UTC")) - timedelta(hours=hours)
    lines: list[str] = []
    if not JOURNAL_AVAILABLE:
        # Development mode: return in-memory captured logs
        lines.append("=== Development Mode Logs (In-Memory Buffer) ===")
        lines.append(
            f"Showing logs from the last {hours} hours (max {DEV_LOG_BUFFER_SIZE} entries)"
        )
        lines.append(
            "For complete logs, check your terminal output where Flask is running."
        )
        lines.append("")

        cutoff_timestamp = since.timestamp()
        with _dev_log_lock:
            for entry_ts, log_line in _dev_log_buffer:
                if entry_ts >= cutoff_timestamp:
                    lines.append(log_line)

        if len(lines) == 4:  # Only headers, no actual logs
            lines.append("(No logs captured in buffer yet)")
        return lines

    log_tz = _device_log_timezone()

    # Journal available path
    reader = JournalReader()
    try:
        reader.open(JournalOpenMode.SYSTEM)
        reader.add_filter(Rule("_SYSTEMD_UNIT", "inkypi.service"))
        reader.seek_realtime_usec(int(since.timestamp() * 1_000_000))

        for record in reader:
            try:
                timestamp = datetime.fromtimestamp(
                    record.get_realtime_usec() / 1_000_000, tz=UTC
                )
                formatted_ts = timestamp.astimezone(log_tz).strftime(
                    LOG_TIMESTAMP_FORMAT
                )
            except Exception:
                formatted_ts = "??? ?? ??:??:??"

            data = record.data
            lines.append(_format_journal_line(formatted_ts, data))
    finally:
        try:
            reader.close()
        except Exception:
            pass
    return lines


def _read_units_log_lines(hours: int, units: list[str]) -> list[str]:
    """Read service logs for the last N hours for one or more units and merge chronologically.

    Falls back to the development message when journal is not available.
    """
    try:
        from flask import current_app

        device_config = current_app.config["DEVICE_CONFIG"]
        since = now_device_tz(device_config) - timedelta(hours=hours)
    except Exception:
        since = datetime.now(tz=get_timezone("UTC")) - timedelta(hours=hours)

    if not JOURNAL_AVAILABLE:
        dev_lines = [
            "=== Development Mode Logs (In-Memory Buffer) ===",
            f"Showing logs from the last {hours} hours (max {DEV_LOG_BUFFER_SIZE} entries)",
            f"Units requested: {', '.join(units)}",
            "For complete logs, check your terminal output where Flask is running.",
            "",
        ]
        cutoff_timestamp = since.timestamp()
        with _dev_log_lock:
            for entry_ts, log_line in _dev_log_buffer:
                if entry_ts >= cutoff_timestamp:
                    dev_lines.append(log_line)

        if len(dev_lines) == 5:  # Only headers
            dev_lines.append("(No logs captured in buffer yet)")
        return dev_lines

    log_tz = _device_log_timezone()
    merged: list[tuple[float, str]] = []
    reader = JournalReader()
    try:
        reader.open(JournalOpenMode.SYSTEM)
        reader.seek_realtime_usec(int(since.timestamp() * 1_000_000))
        for record in reader:
            try:
                data = record.data
                unit_name = data.get("_SYSTEMD_UNIT", "")
                if unit_name not in units:
                    continue
                ts_usec = record.get_realtime_usec()
                log_ts = datetime.fromtimestamp(ts_usec / 1_000_000, tz=UTC)
                formatted_ts = log_ts.astimezone(log_tz).strftime(LOG_TIMESTAMP_FORMAT)
                line = _format_journal_line(formatted_ts, data)
                merged.append((log_ts.timestamp(), line))
            except Exception:
                # Skip malformed records
                continue
    finally:
        try:
            reader.close()
        except Exception:
            pass
    # Sort by timestamp and return only the text
    merged.sort(key=lambda t: t[0])
    return [text for _, text in merged]
