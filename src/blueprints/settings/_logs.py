"""Log viewing and download route handlers."""

import io
import re
from collections.abc import Mapping
from typing import Any

from flask import Response, current_app, jsonify, request

from blueprints.settings import logger, settings_bp
from services import logs, updates
from utils.http_utils import json_error
from utils.rate_limit import SlidingWindowLimiter
from utils.time_utils import now_device_tz

# Guardrails and limits for logs APIs
MAX_LOG_HOURS = 24
MIN_LOG_HOURS = 1
MAX_LOG_LINES = 2000
MIN_LOG_LINES = 50
MAX_RESPONSE_BYTES = 512 * 1024

# Simple in-process rate limiter (per remote addr)
_logs_limiter = SlidingWindowLimiter(120, 60)


def _rate_limit_ok(remote_addr: str | None) -> bool:
    """Thin wrapper kept for test compatibility (monkeypatching)."""
    key = remote_addr or "unknown"
    allowed, _ = _logs_limiter.check(key)
    return bool(allowed)


def _clamp_int(value: str | None, default: int, min_value: int, max_value: int) -> int:
    try:
        if value is None:
            return default
        parsed = int(value)
        return max(min_value, min(parsed, max_value))
    except Exception:
        return default


@settings_bp.route("/download-logs", methods=["GET"])
def download_logs() -> Response:
    try:
        # Guardrail hours clamp
        hours = _clamp_int(request.args.get("hours"), 2, MIN_LOG_HOURS, MAX_LOG_HOURS)
        lines = logs._read_log_lines(hours)
        buffer = io.StringIO("\n".join(lines))
        buffer.seek(0)
        # Add date and time to the filename
        now_str = now_device_tz(current_app.config["DEVICE_CONFIG"]).strftime(
            "%Y%m%d-%H%M%S"
        )
        filename = f"inkypi_{now_str}.log"
        return Response(
            buffer.read(),
            mimetype="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except Exception:
        logger.exception("Error reading logs")
        return Response("Error reading logs", status=500, mimetype="text/plain")


def _parse_log_params(
    args: Mapping[str, str | None],
) -> tuple[int, int, str, bool, str, int, int]:
    """Parse the log query parameters.

    Takes a Mapping rather than a dict so `request.args` — a werkzeug
    MultiDict, which is a Mapping but not a dict — can be passed directly
    instead of being copied at each call site.
    """
    raw_hours = args.get("hours")
    raw_limit = args.get("limit")
    raw_contains_full = args.get("contains") or ""

    try:
        pre_hours = int(raw_hours) if raw_hours is not None else 2
    except Exception:
        pre_hours = 2
    try:
        pre_limit = int(raw_limit) if raw_limit is not None else 500
    except Exception:
        pre_limit = 500

    hours = _clamp_int(raw_hours, 2, MIN_LOG_HOURS, MAX_LOG_HOURS)
    limit = _clamp_int(raw_limit, 500, MIN_LOG_LINES, MAX_LOG_LINES)

    contains = raw_contains_full.strip()
    contains_trimmed = False
    if len(contains) > 200:
        contains = contains[:200]
        contains_trimmed = True

    level = (args.get("level") or "all").lower()

    return hours, limit, contains, contains_trimmed, level, pre_hours, pre_limit


def _filter_log_lines(lines: list[str], contains: str, level: str) -> list[str]:
    if contains:
        lc = contains.lower()
        lines = [ln for ln in lines if lc in ln.lower()]

    if level == "errors":
        err_re = re.compile(r"\b(ERROR|CRITICAL|Exception|Traceback)\b", re.IGNORECASE)
        lines = [ln for ln in lines if err_re.search(ln)]
    elif level in ("warn", "warnings", "warn_errors"):
        err_re = re.compile(r"\b(ERROR|CRITICAL|Exception|Traceback)\b", re.IGNORECASE)
        warn_re = re.compile(r"\bWARNING\b", re.IGNORECASE)
        lines = [ln for ln in lines if err_re.search(ln) or warn_re.search(ln)]

    return lines


@settings_bp.route("/api/logs", methods=["GET"])
def api_logs() -> Response | tuple[Any, int]:
    """JSON logs API with server-side filter, level selection and limits."""
    try:
        if not _rate_limit_ok(request.remote_addr):
            return json_error("Too many requests", status=429)

        hours, limit, contains, contains_trimmed, level, pre_hours, pre_limit = (
            _parse_log_params(request.args)
        )

        # Read raw lines for the main service; include update unit if running
        units = ["inkypi.service"]
        update_unit = updates._UPDATE_STATE.get("unit")
        if isinstance(update_unit, str) and update_unit:
            units.append(update_unit)
        if len(units) == 1:
            lines = logs._read_log_lines(hours)
        else:
            lines = logs._read_units_log_lines(hours, units)

        lines = _filter_log_lines(lines, contains, level)

        truncated = (pre_hours != hours) or (pre_limit != limit) or contains_trimmed
        if len(lines) > limit:
            truncated = True
            lines = lines[-limit:]

        # Response size guardrail
        joined = "\n".join(lines)
        while (
            len(joined.encode("utf-8", errors="ignore")) > MAX_RESPONSE_BYTES
            and len(lines) > 100
        ):
            truncated = True
            lines = lines[len(lines) // 4 :]
            joined = "\n".join(lines)

        return jsonify(
            {
                "lines": lines,
                "count": len(lines),
                "truncated": truncated,
                "meta": {
                    "hours": hours,
                    "limit": limit,
                    "level": level,
                    "contains": contains,
                    "units": units,
                },
            }
        )
    except Exception:
        logger.exception("/api/logs error")
        return json_error("An error occurred while reading logs", status=500)
