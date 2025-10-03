# pyright: reportMissingImports=false, reportMissingTypeStubs=false, reportMissingModuleSource=false, reportRedeclaration=false
import io
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
import shlex

import pytz
from flask import Blueprint, Response, current_app, jsonify, render_template, request

from utils.http_utils import json_error, json_internal_error
from utils.time_utils import calculate_seconds, get_timezone, now_device_tz

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

# Dev mode in-memory log buffer (circular buffer)
DEV_LOG_BUFFER_SIZE = 1000
_dev_log_buffer: deque = deque(maxlen=DEV_LOG_BUFFER_SIZE)
_dev_log_lock = threading.Lock()


class DevModeLogHandler(logging.Handler):
    """Captures logs in memory for dev mode log viewing."""

    def emit(self, record):
        try:
            msg = self.format(record)
            timestamp = datetime.fromtimestamp(record.created).strftime("%b %d %H:%M:%S")
            log_line = f"{timestamp} [{record.levelname}] {record.name}: {msg}"
            with _dev_log_lock:
                _dev_log_buffer.append((record.created, log_line))
        except Exception:
            self.handleError(record)


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
        # Fallback to timezone-aware UTC for consistency
        since = datetime.now(tz=get_timezone("UTC")) - timedelta(hours=hours)
    lines: list[str] = []
    if not JOURNAL_AVAILABLE:
        # Development mode: return in-memory captured logs
        lines.append("=== Development Mode Logs (In-Memory Buffer) ===")
        lines.append(f"Showing logs from the last {hours} hours (max {DEV_LOG_BUFFER_SIZE} entries)")
        lines.append(f"For complete logs, check your terminal output where Flask is running.")
        lines.append("")

        cutoff_timestamp = since.timestamp()
        with _dev_log_lock:
            for ts, log_line in _dev_log_buffer:
                if ts >= cutoff_timestamp:
                    lines.append(log_line)

        if len(lines) == 4:  # Only headers, no actual logs
            lines.append("(No logs captured in buffer yet)")
        return lines

    # Journal available path
    reader = JournalReader()
    try:
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
            for ts, log_line in _dev_log_buffer:
                if ts >= cutoff_timestamp:
                    dev_lines.append(log_line)

        if len(dev_lines) == 5:  # Only headers
            dev_lines.append("(No logs captured in buffer yet)")
        return dev_lines

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
                ts = datetime.fromtimestamp(ts_usec / 1_000_000)
                formatted_ts = ts.strftime("%b %d %H:%M:%S")
                hostname = data.get("_HOSTNAME", "unknown-host")
                identifier = data.get("SYSLOG_IDENTIFIER") or data.get("_COMM", "?")
                pid = data.get("_PID", "?")
                msg = (data.get("MESSAGE", "") or "").rstrip()
                line = f"{formatted_ts} {hostname} {identifier}[{pid}]: {msg}"
                merged.append((ts.timestamp(), line))
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


# In-memory update state for coordinating UI status and logs
_UPDATE_STATE: dict[str, object] = {
    "running": False,
    "unit": None,
    "started_at": None,  # epoch seconds
}


def _get_install_update_script_path() -> str | None:
    """Return absolute path to update.sh if available on this host.

    Priorities:
    - $PROJECT_DIR/install/update.sh (production install path)
    - repo-relative ../../install/update.sh (developer environment)
    """
    # 1) production install path
    project_dir = os.getenv("PROJECT_DIR")
    if project_dir:
        prod = os.path.join(project_dir, "install", "update.sh")
        if os.path.isfile(prod):
            return prod
    # 2) repo path (this file: src/blueprints/settings.py → repo_root/install/update.sh)
    here = os.path.dirname(os.path.abspath(__file__))
    repo_install = os.path.abspath(os.path.join(here, "..", "..", "install", "update.sh"))
    if os.path.isfile(repo_install):
        return repo_install
    return None


def _systemd_available() -> bool:
    try:
        return shutil.which("systemd-run") is not None
    except Exception:
        return False


def _set_update_state(running: bool, unit: str | None):
    _UPDATE_STATE["running"] = bool(running)
    _UPDATE_STATE["unit"] = unit
    _UPDATE_STATE["started_at"] = float(time.time()) if running else None


def _start_update_via_systemd(unit_name: str, script_path: str) -> None:
    # Run update script in a transient systemd unit so its logs are visible in journal
    cmd = [
        "systemd-run",
        "--collect",
        f"--unit={unit_name}",
        "--property=StandardOutput=journal",
        "--property=StandardError=journal",
        "/bin/bash",
        "-lc",
        shlex.quote(script_path),
    ]
    subprocess.Popen(cmd)  # nosec: commands are fixed, script path quoted


def _start_update_fallback_thread(script_path: str | None) -> None:
    # Development/macOS path: run a simulated update and pipe output into our logger
    # to make it visible in inkypi.service logs and the UI viewer.
    def _runner():
        try:
            logger.info("web_update: starting")
            if script_path and os.path.isfile(script_path) and os.access(script_path, os.X_OK):
                # Do not run the real script unless explicitly enabled
                allow_real = os.getenv("INKYPI_ALLOW_REAL_UPDATE", "0").strip() in ("1", "true", "yes")
                if allow_real:
                    proc = subprocess.Popen(
                        ["/bin/bash", "-lc", shlex.quote(script_path)],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        universal_newlines=True,
                    )
                    for line in proc.stdout or []:
                        logger.info("update | %s", line.rstrip())
                    proc.wait()
                    rc = proc.returncode if proc.returncode is not None else 0
                    if rc == 0:
                        logger.info("web_update: completed successfully")
                    else:
                        logger.error("web_update: failed with return code %s", rc)
                else:
                    # Simulated update to avoid privileged operations in development and tests
                    for msg in [
                        "Simulated update starting...",
                        "Checking connectivity...",
                        "Fetching latest dependencies...",
                        "Updating application files...",
                        "Restarting service...",
                        "Update completed.",
                    ]:
                        logger.info("update | %s", msg)
                        time.sleep(0.5)
            else:
                for i in range(6):
                    logger.info("update | step %d/6", i + 1)
                    time.sleep(0.5)
                logger.info("update | done (simulated)")
        except Exception:
            logger.exception("web_update: exception while running update")
        finally:
            _set_update_state(False, None)

    t = threading.Thread(target=_runner, name="update-fallback", daemon=True)
    t.start()


@settings_bp.route("/settings/update", methods=["POST"])  # start update
def start_update():
    """Trigger InkyPi update via systemd-run when available, with dev fallback.

    Returns JSON immediately; progress is visible in the Logs panel via /api/logs.
    """
    try:
        if _UPDATE_STATE.get("running"):
            return jsonify({
                "success": False,
                "error": "Update already in progress.",
                "running": True,
                "unit": _UPDATE_STATE.get("unit"),
            }), 409

        script_path = _get_install_update_script_path()
        unit = f"inkypi-update-{int(time.time())}"

        if _systemd_available():
            _set_update_state(True, f"{unit}.service")
            try:
                _start_update_via_systemd(unit, script_path or "/usr/local/inkypi/install/update.sh")
            except Exception:
                # If systemd-run fails unexpectedly, fall back to thread runner
                logger.exception("systemd-run failed; falling back to thread runner")
                _start_update_fallback_thread(script_path)
        else:
            _set_update_state(True, None)
            _start_update_fallback_thread(script_path)

        return jsonify({
            "success": True,
            "running": True,
            "unit": _UPDATE_STATE.get("unit"),
            "message": "Update started. Watch the Logs panel for progress.",
        })
    except Exception as e:
        logger.exception("/settings/update error")
        return json_internal_error("start update", details={"error": str(e)})


@settings_bp.route("/settings/update_status")
def update_status():
    try:
        running = bool(_UPDATE_STATE.get("running"))
        unit = _UPDATE_STATE.get("unit")
        started_at = _UPDATE_STATE.get("started_at")
        return jsonify({
            "running": running,
            "unit": unit,
            "started_at": started_at,
        })
    except Exception as e:
        return json_internal_error("update status", details={"error": str(e)})


@settings_bp.route("/settings")
def settings_page():
    device_config = current_app.config["DEVICE_CONFIG"]
    timezones = sorted(pytz.all_timezones_set)
    return render_template(
        "settings.html", device_settings=device_config.get_config(), timezones=timezones
    )


@settings_bp.route("/settings/backup")
def backup_restore_page():
    device_config = current_app.config["DEVICE_CONFIG"]
    # For now, reuse the main settings page and anchor to a section; separate template can be added later
    return render_template(
        "settings.html",
        device_settings=device_config.get_config(),
        timezones=sorted(pytz.all_timezones_set),
    )


@settings_bp.route("/settings/export", methods=["GET"])
def export_settings():
    try:
        include_keys = request.args.get("include_keys", "1").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        device_config = current_app.config["DEVICE_CONFIG"]

        # Build export object with config plus env keys when requested
        data = {
            "config": device_config.get_config(),
        }
        if include_keys:
            # Include known API keys and possibly other keys
            keys = {}
            for k in (
                "OPEN_AI_SECRET",
                "OPEN_WEATHER_MAP_SECRET",
                "NASA_SECRET",
                "UNSPLASH_ACCESS_KEY",
            ):
                try:
                    v = device_config.load_env_key(k)
                except Exception:
                    v = None
                if v:
                    keys[k] = v
            data["env_keys"] = keys

        # JSON response for now; a file download route can be added if needed
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.exception("Error exporting settings")
        return json_internal_error(
            "export settings",
            details={"hint": "Check config readability.", "error": str(e)},
        )


@settings_bp.route("/settings/import", methods=["POST"])
def import_settings():
    try:
        device_config = current_app.config["DEVICE_CONFIG"]
        # Accept JSON body or form upload with a JSON file
        payload = None
        if request.is_json:
            payload = request.get_json(silent=True)
        if payload is None:
            file = request.files.get("file")
            if file:
                import json as _json

                payload = _json.loads(file.stream.read().decode("utf-8"))
        if not payload or not isinstance(payload, dict):
            return json_error("Invalid import payload", status=400)

        cfg = payload.get("config")
        if isinstance(cfg, dict):
            # Merge config and write
            device_config.update_config(cfg)

        env_keys = payload.get("env_keys") or {}
        if isinstance(env_keys, dict):
            for k, v in env_keys.items():
                if v is None:
                    continue
                try:
                    device_config.set_env_key(k, str(v))
                except Exception:
                    logger.exception("Failed setting env key during import: %s", k)

        return jsonify({"success": True, "message": "Import completed"})
    except Exception as e:
        logger.exception("Error importing settings")
        return json_internal_error(
            "import settings",
            details={
                "hint": "Verify JSON structure and file permissions.",
                "error": str(e),
            },
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
        return json_internal_error(
            "saving API keys",
            details={
                "hint": "Ensure .env is writable and values are valid; check disk space/permissions.",
            },
        )


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
        return json_internal_error(
            "deleting API key",
            details={"hint": "Verify .env file permissions and key exists."},
        )


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
        # Optional: device geolocation from browser
        try:
            lat_raw = form_data.get("deviceLat")
            lon_raw = form_data.get("deviceLon")
            if (
                lat_raw is not None
                and lon_raw is not None
                and lat_raw != ""
                and lon_raw != ""
            ):
                lat = float(lat_raw)
                lon = float(lon_raw)
                # Basic sanity range check
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    settings["device_location"] = {"lat": lat, "lon": lon}
        except Exception:
            # Ignore invalid inputs; keep existing config
            pass
        device_config.update_config(settings)

        if plugin_cycle_interval_seconds != previous_interval_seconds:
            # wake the background thread up to signal interval config change
            refresh_task = current_app.config["REFRESH_TASK"]
            refresh_task.signal_config_change()
    except RuntimeError as e:
        return json_error(str(e), status=500)
    except Exception:
        logger.exception("Error saving device settings")
        return json_internal_error(
            "saving device settings",
            details={"hint": "Check numeric values and config file permissions."},
        )
    return jsonify({"success": True, "message": "Saved settings."})


@settings_bp.route("/settings/client_log", methods=["POST"])
def client_log():
    """Accept lightweight client logs and emit them to server logs.

    Intended for front-end flows (e.g., browser geolocation) where we need
    visibility in terminal logs without failing the UX if logging fails.
    """
    try:
        data = request.get_json(silent=True) or {}
        level = str(data.get("level") or "info").lower()
        message = str(data.get("message") or "")
        extra = data.get("extra")
        # Render extra as compact string to avoid noisy logs
        try:
            import json as _json

            extra_str = (
                _json.dumps(extra, separators=(",", ":")) if extra is not None else "{}"
            )
        except Exception:
            extra_str = str(extra)

        line = f"client_log | level={level} msg={message} extra={extra_str}"
        if level == "debug":
            logger.debug(line)
        elif level in ("warn", "warning"):
            logger.warning(line)
        elif level in ("err", "error"):
            logger.error(line)
        else:
            logger.info(line)
        return jsonify({"success": True})
    except Exception:
        logger.exception("/settings/client_log failure")
        return json_internal_error(
            "client_log", details={"hint": "Check payload shape."}
        )


@settings_bp.route("/shutdown", methods=["POST"])
def shutdown():
    """Reboot or shut down the device.

    Consider adding authentication or CSRF protection if publicly exposed.
    """
    data = request.get_json() or {}
    try:
        if data.get("reboot"):
            logger.info("Reboot requested")
            subprocess.run(["sudo", "reboot"], check=True)
        else:
            logger.info("Shutdown requested")
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        return jsonify({"success": True})
    except subprocess.CalledProcessError as e:
        logger.exception("Failed to execute shutdown command")
        return json_internal_error(
            "shutdown", details={"error": str(e)}
        )


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

        # Read raw lines for the main service; include update unit if running
        units = ["inkypi.service"]
        update_unit = _UPDATE_STATE.get("unit")
        if isinstance(update_unit, str) and update_unit:
            units.append(update_unit)
        if len(units) == 1:
            lines = _read_log_lines(hours)
        else:
            lines = _read_units_log_lines(hours, units)

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
                    "units": units,
                },
            }
        )
    except Exception as e:
        logger.exception("/api/logs error")
        return json_error(str(e), status=500)
