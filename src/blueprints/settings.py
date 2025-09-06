# pyright: reportMissingImports=false, reportMissingTypeStubs=false, reportMissingModuleSource=false, reportRedeclaration=false
import io
import logging
import os
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta
import time

import pytz
from flask import Blueprint, Response, current_app, jsonify, render_template, request

from utils.http_utils import json_error
from utils.time_utils import calculate_seconds, now_device_tz

# Try to import cysystemd for journal reading (Linux only)
try:
    from cysystemd.reader import (  # type: ignore[import-not-found]
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


logger = logging.getLogger(__name__)
settings_bp = Blueprint("settings", __name__)

# Guardrails and limits for logs APIs
MAX_LOG_HOURS = 24
MIN_LOG_HOURS = 1
MAX_LOG_LINES = 2000
MIN_LOG_LINES = 50
MAX_RESPONSE_BYTES = 512 * 1024  # 512 KB safety cap

# Simple in-process rate limiter (per remote addr)
_REQUESTS: dict[str, deque] = defaultdict(deque)
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 120


def _rate_limit_ok(remote_addr: str | None) -> bool:
    try:
        key = remote_addr or "unknown"
        q = _REQUESTS[key]
        now = time.time()
        # drop old timestamps
        cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= _RATE_LIMIT_MAX_REQUESTS:
            return False
        q.append(now)
        return True
    except Exception:
        # On any failure, allow rather than block
        return True


def _clamp_int(value: str | None, default: int, min_value: int, max_value: int) -> int:
    try:
        if value is None:
            return default
        parsed = int(value)
        return max(min_value, min(parsed, max_value))
    except Exception:
        return default


def _read_log_lines(hours: int) -> list[str]:
    """Read service logs for the last N hours and return as list of formatted lines."""
    # Use device timezone for consistency in all time computations
    try:
        from flask import current_app

        device_config = current_app.config["DEVICE_CONFIG"]
        since = now_device_tz(device_config) - timedelta(hours=hours)
    except Exception:
        since = datetime.now() - timedelta(hours=hours)
    lines: list[str] = []
    if not JOURNAL_AVAILABLE:
        # Development mode message when systemd journal is not accessible
        lines.append(
            "Log download not available in development mode (cysystemd not installed)."
        )
        lines.append(
            f"Logs would normally show InkyPi service logs from the last {hours} hours."
        )
        lines.append("")
        lines.append("To see Flask development logs, check your terminal output.")
        return lines

    # Journal available path
    reader = JournalReader()
    reader.open(JournalOpenMode.SYSTEM)
    reader.add_filter(Rule("_SYSTEMD_UNIT", "inkypi.service"))
    reader.seek_realtime_usec(int(since.timestamp() * 1_000_000))

    for record in reader:
        try:
            ts = datetime.fromtimestamp(record.get_realtime_usec() / 1_000_000)
            formatted_ts = ts.strftime("%b %d %H:%M:%S")
        except Exception:
            formatted_ts = "??? ?? ??:??:??"

        data = record.data
        hostname = data.get("_HOSTNAME", "unknown-host")
        identifier = data.get("SYSLOG_IDENTIFIER") or data.get("_COMM", "?")
        pid = data.get("_PID", "?")
        msg = data.get("MESSAGE", "").rstrip()
        lines.append(f"{formatted_ts} {hostname} {identifier}[{pid}]: {msg}")
    return lines


@settings_bp.route("/settings")
def settings_page():
    device_config = current_app.config["DEVICE_CONFIG"]
    timezones = sorted(pytz.all_timezones_set)
    return render_template(
        "settings.html", device_settings=device_config.get_config(), timezones=timezones
    )


@settings_bp.route("/settings/api-keys")
def api_keys_page():
    device_config = current_app.config["DEVICE_CONFIG"]

    def mask(value):
        if not value:
            return None
        try:
            return f"...{value[-4:]}" if len(value) >= 4 else "set"
        except Exception:
            return "set"

    keys = {
        "OPEN_AI_SECRET": device_config.load_env_key("OPEN_AI_SECRET"),
        "OPEN_WEATHER_MAP_SECRET": device_config.load_env_key(
            "OPEN_WEATHER_MAP_SECRET"
        ),
        "NASA_SECRET": device_config.load_env_key("NASA_SECRET"),
        "UNSPLASH_ACCESS_KEY": device_config.load_env_key("UNSPLASH_ACCESS_KEY"),
    }
    masked = {k: mask(v) for k, v in keys.items()}
    return render_template("api_keys.html", masked=masked)


@settings_bp.route("/settings/save_api_keys", methods=["POST"])
def save_api_keys():
    device_config = current_app.config["DEVICE_CONFIG"]
    try:
        form_data = request.form.to_dict()
        updated = []
        for key in (
            "OPEN_AI_SECRET",
            "OPEN_WEATHER_MAP_SECRET",
            "NASA_SECRET",
            "UNSPLASH_ACCESS_KEY",
        ):
            value = form_data.get(key)
            if value:
                device_config.set_env_key(key, value)
                updated.append(key)
        return jsonify(
            {"success": True, "message": "API keys saved.", "updated": updated}
        )
    except Exception:
        logger.exception("Error saving API keys")
        return json_error("An internal error occurred", status=500)


@settings_bp.route("/settings/delete_api_key", methods=["POST"])
def delete_api_key():
    device_config = current_app.config["DEVICE_CONFIG"]
    key = request.form.get("key")
    valid_keys = {
        "OPEN_AI_SECRET",
        "OPEN_WEATHER_MAP_SECRET",
        "NASA_SECRET",
        "UNSPLASH_ACCESS_KEY",
    }
    if key not in valid_keys:
        return json_error("Invalid key name", status=400)
    try:
        device_config.unset_env_key(key)
        return jsonify({"success": True, "message": f"Deleted {key}."})
    except Exception:
        logger.exception("Error deleting API key")
        return json_error("An internal error occurred", status=500)


@settings_bp.route("/save_settings", methods=["POST"])
def save_settings():
    device_config = current_app.config["DEVICE_CONFIG"]

    try:
        form_data = request.form.to_dict()

        unit, interval, time_format = (
            form_data.get("unit"),
            form_data.get("interval"),
            form_data.get("timeFormat"),
        )
        if not unit or unit not in ["minute", "hour"]:
            return json_error("Plugin cycle interval unit is required", status=400)
        if not interval or not interval.isnumeric():
            return json_error("Refresh interval is required", status=400)
        if not form_data.get("timezoneName"):
            return json_error("Time Zone is required", status=400)
        if not time_format or time_format not in ["12h", "24h"]:
            return json_error("Time format is required", status=400)
        previous_interval_seconds = device_config.get_config(
            "plugin_cycle_interval_seconds"
        )
        plugin_cycle_interval_seconds = calculate_seconds(int(interval), unit)
        if plugin_cycle_interval_seconds > 86400 or plugin_cycle_interval_seconds <= 0:
            return json_error(
                "Plugin cycle interval must be less than 24 hours", status=400
            )

        settings = {
            "name": form_data.get("deviceName"),
            "orientation": form_data.get("orientation"),
            "inverted_image": form_data.get("invertImage"),
            "log_system_stats": form_data.get("logSystemStats"),
            "timezone": form_data.get("timezoneName"),
            "time_format": form_data.get("timeFormat"),
            "plugin_cycle_interval_seconds": plugin_cycle_interval_seconds,
            "image_settings": {
                "saturation": float(form_data.get("saturation", "1.0")),
                "brightness": float(form_data.get("brightness", "1.0")),
                "sharpness": float(form_data.get("sharpness", "1.0")),
                "contrast": float(form_data.get("contrast", "1.0")),
            },
            "preview_size_mode": form_data.get("previewSizeMode", "native"),
        }
        device_config.update_config(settings)

        if plugin_cycle_interval_seconds != previous_interval_seconds:
            # wake the background thread up to signal interval config change
            refresh_task = current_app.config["REFRESH_TASK"]
            refresh_task.signal_config_change()
    except RuntimeError as e:
        return json_error(str(e), status=500)
    except Exception:
        logger.exception("Error saving device settings")
        return json_error("An internal error occurred", status=500)
    return jsonify({"success": True, "message": "Saved settings."})


@settings_bp.route("/shutdown", methods=["POST"])
def shutdown():
    data = request.get_json() or {}
    if data.get("reboot"):
        logger.info("Reboot requested")
        os.system("sudo reboot")
    else:
        logger.info("Shutdown requested")
        os.system("sudo shutdown -h now")
    return jsonify({"success": True})


@settings_bp.route("/download-logs")
def download_logs():
    try:
        # Guardrail hours clamp
        hours = _clamp_int(request.args.get("hours"), 2, MIN_LOG_HOURS, MAX_LOG_HOURS)
        lines = _read_log_lines(hours)
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
        logger.exception("Error reading logs")
        return Response(f"Error reading logs: {e}", status=500, mimetype="text/plain")


@settings_bp.route("/api/logs")
def api_logs():
    """JSON logs API with server-side filter, level selection and limits."""
    try:
        if not _rate_limit_ok(request.remote_addr):
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

        hours = _clamp_int(raw_hours, 2, MIN_LOG_HOURS, MAX_LOG_HOURS)
        limit = _clamp_int(raw_limit, 500, MIN_LOG_LINES, MAX_LOG_LINES)

        contains = raw_contains_full.strip()
        contains_trimmed = False
        if len(contains) > 200:
            contains = contains[:200]
            contains_trimmed = True

        level = (request.args.get("level") or "all").lower()

        # Read raw lines then apply filtering server-side
        lines = _read_log_lines(hours)

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
                },
            }
        )
    except Exception as e:
        logger.exception("/api/logs error")
        return json_error(str(e), status=500)
