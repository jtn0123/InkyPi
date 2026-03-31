"""Log viewing and download route handlers."""

import io
import re

from flask import Response, current_app, jsonify, request

import blueprints.settings as _mod
from utils.http_utils import json_error
from utils.time_utils import now_device_tz


@_mod.settings_bp.route("/download-logs")
def download_logs():
    try:
        # Guardrail hours clamp
        hours = _mod._clamp_int(
            request.args.get("hours"), 2, _mod.MIN_LOG_HOURS, _mod.MAX_LOG_HOURS
        )
        lines = _mod._read_log_lines(hours)
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
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        _mod.logger.exception("Error reading logs")
        return Response(f"Error reading logs: {e}", status=500, mimetype="text/plain")


@_mod.settings_bp.route("/api/logs")
def api_logs():
    """JSON logs API with server-side filter, level selection and limits."""
    try:
        if not _mod._rate_limit_ok(request.remote_addr):
            return json_error("Too many requests", status=429)

        # Capture raw inputs and determine if clamped/trimmed
        raw_hours = request.args.get("hours")
        raw_limit = request.args.get("limit")
        raw_contains_full = request.args.get("contains") or ""

        try:
            pre_hours = int(raw_hours) if raw_hours is not None else 2
        except Exception:
            pre_hours = 2
        try:
            pre_limit = int(raw_limit) if raw_limit is not None else 500
        except Exception:
            pre_limit = 500

        hours = _mod._clamp_int(raw_hours, 2, _mod.MIN_LOG_HOURS, _mod.MAX_LOG_HOURS)
        limit = _mod._clamp_int(raw_limit, 500, _mod.MIN_LOG_LINES, _mod.MAX_LOG_LINES)

        contains = raw_contains_full.strip()
        contains_trimmed = False
        if len(contains) > 200:
            contains = contains[:200]
            contains_trimmed = True

        level = (request.args.get("level") or "all").lower()

        # Read raw lines for the main service; include update unit if running
        units = ["inkypi.service"]
        update_unit = _mod._UPDATE_STATE.get("unit")
        if isinstance(update_unit, str) and update_unit:
            units.append(update_unit)
        if len(units) == 1:
            lines = _mod._read_log_lines(hours)
        else:
            lines = _mod._read_units_log_lines(hours, units)

        if contains:
            lc = contains.lower()
            lines = [ln for ln in lines if lc in ln.lower()]

        if level == "errors":
            err_re = re.compile(
                r"\b(ERROR|CRITICAL|Exception|Traceback)\b", re.IGNORECASE
            )
            lines = [ln for ln in lines if err_re.search(ln)]
        elif level in ("warn", "warnings", "warn_errors"):
            err_re = re.compile(
                r"\b(ERROR|CRITICAL|Exception|Traceback)\b", re.IGNORECASE
            )
            warn_re = re.compile(r"\bWARNING\b", re.IGNORECASE)
            lines = [ln for ln in lines if err_re.search(ln) or warn_re.search(ln)]

        truncated = (pre_hours != hours) or (pre_limit != limit) or contains_trimmed
        if len(lines) > limit:
            truncated = True
            lines = lines[-limit:]

        # Response size guardrail
        joined = "\n".join(lines)
        while (
            len(joined.encode("utf-8", errors="ignore")) > _mod.MAX_RESPONSE_BYTES
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
    except Exception as e:
        _mod.logger.exception("/api/logs error")
        return json_error(str(e), status=500)
