# pyright: reportMissingImports=false, reportMissingTypeStubs=false, reportMissingModuleSource=false, reportRedeclaration=false
import io
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any

import pytz
import requests as _requests
from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from utils.http_utils import json_error, json_internal_error
from utils.progress_events import get_progress_bus, to_sse
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


def _benchmarks_enabled() -> bool:
    return os.getenv("INKYPI_BENCHMARK_API_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _get_bench_db_path() -> str:
    from benchmarks.benchmark_storage import _get_db_path

    return _get_db_path(current_app.config["DEVICE_CONFIG"])


def _ensure_bench_schema(conn: sqlite3.Connection) -> None:
    from benchmarks.benchmark_storage import _ensure_schema

    _ensure_schema(conn)


def _window_since_seconds(window: str | None) -> float:
    now = time.time()
    if not window:
        return now - 24 * 3600
    val = (window or "").strip().lower()
    if val.endswith("h"):
        return now - (int(val[:-1]) * 3600)
    if val.endswith("m"):
        return now - (int(val[:-1]) * 60)
    if val.endswith("d"):
        return now - (int(val[:-1]) * 86400)
    return now - 24 * 3600


def _pct(values: list[int], p: float) -> int | None:
    if not values:
        return None
    values = sorted(values)
    idx = max(0, min(len(values) - 1, int(round((len(values) - 1) * p))))
    return int(values[idx])


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
    finally:
        # Prune empty deques to prevent unbounded memory growth from unique IPs
        try:
            _prune_empty_rate_limit_keys()
        except Exception:
            pass


def _prune_empty_rate_limit_keys():
    """Remove IP keys with empty deques from the rate limiter."""
    empty_keys = [k for k, v in _REQUESTS.items() if not v]
    for k in empty_keys:
        del _REQUESTS[k]


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
        lines.append("For complete logs, check your terminal output where Flask is running.")
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
    "last_unit": None,  # preserved after update completes for log retrieval
}

_UPDATE_TIMEOUT_SECONDS = 1800  # 30 minutes


def _get_update_script_path() -> str | None:
    """Return absolute path to the best update script available on this host.

    Looks for ``do_update.sh`` first (git pull + deps), then ``update.sh`` (deps only).

    Priorities:
    1. Follow the ``$PROJECT_DIR/src`` symlink back to the repo for ``install/do_update.sh``
    2. ``$PROJECT_DIR/install/do_update.sh``
    3. Repo-relative ``../../install/do_update.sh`` (developer environment)
    4. Same cascade for ``update.sh`` as fallback
    """
    candidates: list[str] = []
    project_dir = os.getenv("PROJECT_DIR")

    # Resolve the real repo root by following the src symlink (production layout)
    if project_dir:
        src_link = os.path.join(project_dir, "src")
        if os.path.islink(src_link):
            repo_root = os.path.dirname(os.path.realpath(src_link))
            candidates.append(os.path.join(repo_root, "install", "do_update.sh"))
            candidates.append(os.path.join(repo_root, "install", "update.sh"))
        # Direct PROJECT_DIR/install paths
        candidates.append(os.path.join(project_dir, "install", "do_update.sh"))
        candidates.append(os.path.join(project_dir, "install", "update.sh"))

    # Repo-relative path (this file: src/blueprints/settings.py → repo_root/install/)
    here = os.path.dirname(os.path.abspath(__file__))
    repo_install = os.path.abspath(os.path.join(here, "..", "..", "install"))
    candidates.append(os.path.join(repo_install, "do_update.sh"))
    candidates.append(os.path.join(repo_install, "update.sh"))

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


# Keep legacy alias
_get_install_update_script_path = _get_update_script_path


def _systemd_available() -> bool:
    try:
        return shutil.which("systemd-run") is not None
    except Exception:
        return False


def _set_update_state(running: bool, unit: str | None):
    if not running and _UPDATE_STATE.get("unit"):
        _UPDATE_STATE["last_unit"] = _UPDATE_STATE["unit"]
    _UPDATE_STATE["running"] = bool(running)
    _UPDATE_STATE["unit"] = unit
    _UPDATE_STATE["started_at"] = float(time.time()) if running else None


def _start_update_via_systemd(unit_name: str, script_path: str, target_tag: str | None = None) -> None:
    # Run update script in a transient systemd unit so its logs are visible in journal
    project_dir = os.getenv("PROJECT_DIR", "/usr/local/inkypi")
    cmd = [
        "systemd-run",
        "--collect",
        f"--unit={unit_name}",
        "--property=StandardOutput=journal",
        "--property=StandardError=journal",
        f"--setenv=PROJECT_DIR={project_dir}",
        "/bin/bash",
        script_path,
    ]
    if target_tag:
        cmd.append(target_tag)
    subprocess.Popen(cmd)  # nosec: commands are fixed, script path validated


def _start_update_fallback_thread(script_path: str | None) -> None:
    # Development/macOS path: run a simulated update and pipe output into our logger
    # to make it visible in inkypi.service logs and the UI viewer.
    def _log_and_publish(msg: str, level: str = "info"):
        """Log and publish update progress to the SSE bus."""
        getattr(logger, level)("update | %s", msg)
        try:
            bus = get_progress_bus()
            bus.publish({"type": "update_log", "line": msg})
        except Exception:
            pass

    def _runner():
        try:
            _log_and_publish("web_update: starting")
            if script_path and os.path.isfile(script_path) and os.access(script_path, os.X_OK):
                # Do not run the real script unless explicitly enabled
                allow_real = os.getenv("INKYPI_ALLOW_REAL_UPDATE", "0").strip() in ("1", "true", "yes")
                if allow_real:
                    proc = subprocess.Popen(
                        ["/bin/bash", script_path],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        universal_newlines=True,
                    )
                    for line in proc.stdout or []:
                        _log_and_publish(line.rstrip())
                    proc.wait()
                    rc = proc.returncode if proc.returncode is not None else 0
                    if rc == 0:
                        _log_and_publish("web_update: completed successfully")
                    else:
                        _log_and_publish(f"web_update: failed with return code {rc}", "error")
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
                        _log_and_publish(msg)
                        time.sleep(0.5)
            else:
                for i in range(6):
                    _log_and_publish(f"step {i + 1}/6")
                    time.sleep(0.5)
                _log_and_publish("done (simulated)")
        except Exception:
            logger.exception("web_update: exception while running update")
        finally:
            _set_update_state(False, None)

    t = threading.Thread(target=_runner, name="update-fallback", daemon=True)
    t.start()


@settings_bp.route("/settings/update", methods=["POST"])  # start update
def start_update():
    """Trigger InkyPi update via systemd-run when available, with dev fallback.

    Accepts optional JSON body ``{"target_version": "v1.2.0"}`` to update to a
    specific tag.  Returns JSON immediately; progress is visible in the Logs
    panel via /api/logs.
    """
    try:
        if _UPDATE_STATE.get("running"):
            return jsonify({
                "success": False,
                "error": "Update already in progress.",
                "running": True,
                "unit": _UPDATE_STATE.get("unit"),
            }), 409

        # Accept optional target tag from JSON body
        target_tag: str | None = None
        try:
            body = request.get_json(silent=True) or {}
            raw = body.get("target_version")
            if raw and isinstance(raw, str):
                target_tag = raw.strip()
        except Exception:
            pass

        script_path = _get_update_script_path()
        unit = f"inkypi-update-{int(time.time())}"

        if _systemd_available():
            _set_update_state(True, f"{unit}.service")
            try:
                _start_update_via_systemd(
                    unit,
                    script_path or "/usr/local/inkypi/install/do_update.sh",
                    target_tag=target_tag,
                )
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

        # Auto-clear stale update state
        if running:
            cleared = False
            # Check if the systemd transient unit has finished
            if unit and _systemd_available():
                try:
                    result = subprocess.run(
                        ["systemctl", "is-active", unit],
                        capture_output=True, text=True, timeout=5,
                    )
                    status = result.stdout.strip()
                    if status not in ("active", "activating"):
                        _UPDATE_STATE["last_unit"] = unit
                        _set_update_state(False, None)
                        cleared = True
                except Exception:
                    pass
            # Timeout fallback: force-clear if started >30 min ago
            if not cleared and started_at and (time.time() - float(started_at)) > _UPDATE_TIMEOUT_SECONDS:
                _UPDATE_STATE["last_unit"] = unit
                _set_update_state(False, None)

            # Re-read after potential clear
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


# --- Version check via GitHub Releases API ---
_GITHUB_REPO = os.getenv("INKYPI_GITHUB_REPO", "jtn0123/InkyPi")
_VERSION_CACHE: dict[str, object] = {"latest": None, "checked_at": 0.0, "release_notes": None}
_VERSION_CACHE_TTL = 3600  # 1 hour


def _semver_gt(a: str, b: str) -> bool:
    """Return True if semver string *a* is strictly greater than *b*."""
    try:
        return tuple(int(x) for x in a.split(".")) > tuple(int(x) for x in b.split("."))
    except (ValueError, AttributeError):
        return False


def _check_latest_version() -> str | None:
    """Fetch the latest release tag from the GitHub Releases API. Returns None on failure."""
    now = time.time()
    if _VERSION_CACHE["latest"] and (now - float(_VERSION_CACHE["checked_at"] or 0)) < _VERSION_CACHE_TTL:
        return _VERSION_CACHE["latest"]  # type: ignore[return-value]
    try:
        resp = _requests.get(
            f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest",
            timeout=10,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        resp.raise_for_status()
        data = resp.json()
        tag = data.get("tag_name", "")
        if re.match(r"^v?\d+\.\d+\.\d+$", tag):
            latest = tag.lstrip("v")
            _VERSION_CACHE["latest"] = latest
            _VERSION_CACHE["checked_at"] = now
            _VERSION_CACHE["release_notes"] = data.get("body")
            return latest
    except Exception:
        logger.debug("Failed to check latest version via GitHub API", exc_info=True)
    return None


@settings_bp.route("/api/version")
def api_version():
    """Return current and latest version info."""
    try:
        current = current_app.config.get("APP_VERSION", "unknown")
        latest = _check_latest_version()
        update_available = False
        if latest and current != "unknown":
            update_available = _semver_gt(latest, current)
        return jsonify({
            "current": current,
            "latest": latest,
            "update_available": update_available,
            "update_running": bool(_UPDATE_STATE.get("running")),
            "release_notes": _VERSION_CACHE.get("release_notes"),
        })
    except Exception as e:
        return json_internal_error("version check", details={"error": str(e)})


@settings_bp.route("/api/benchmarks/summary")
def benchmarks_summary():
    if not _benchmarks_enabled():
        return json_error("Benchmarks API disabled", status=404)
    conn = None
    try:
        since = _window_since_seconds(request.args.get("window", "24h"))
        conn = sqlite3.connect(_get_bench_db_path())
        conn.row_factory = sqlite3.Row
        _ensure_bench_schema(conn)
        rows = conn.execute(
            """
            SELECT request_ms, generate_ms, preprocess_ms, display_ms
            FROM refresh_events
            WHERE ts >= ?
            ORDER BY ts DESC
            """,
            (since,),
        ).fetchall()
        req = [int(r["request_ms"]) for r in rows if r["request_ms"] is not None]
        gen = [int(r["generate_ms"]) for r in rows if r["generate_ms"] is not None]
        pre = [int(r["preprocess_ms"]) for r in rows if r["preprocess_ms"] is not None]
        dsp = [int(r["display_ms"]) for r in rows if r["display_ms"] is not None]
        return jsonify(
            {
                "success": True,
                "count": len(rows),
                "summary": {
                    "request_ms": {"p50": _pct(req, 0.5), "p95": _pct(req, 0.95)},
                    "generate_ms": {"p50": _pct(gen, 0.5), "p95": _pct(gen, 0.95)},
                    "preprocess_ms": {"p50": _pct(pre, 0.5), "p95": _pct(pre, 0.95)},
                    "display_ms": {"p50": _pct(dsp, 0.5), "p95": _pct(dsp, 0.95)},
                },
            }
        )
    except Exception as e:
        return json_internal_error("benchmarks summary", details={"error": str(e)})
    finally:
        if conn:
            conn.close()


@settings_bp.route("/api/benchmarks/refreshes")
def benchmarks_refreshes():
    if not _benchmarks_enabled():
        return json_error("Benchmarks API disabled", status=404)
    conn = None
    try:
        limit = max(1, min(200, int(request.args.get("limit", "50"))))
        cursor = request.args.get("cursor")
        since = _window_since_seconds(request.args.get("window", "24h"))
        conn = sqlite3.connect(_get_bench_db_path())
        conn.row_factory = sqlite3.Row
        _ensure_bench_schema(conn)
        if cursor:
            rows = conn.execute(
                """
                SELECT id, ts, refresh_id, plugin_id, instance, playlist, used_cached,
                       request_ms, generate_ms, preprocess_ms, display_ms
                FROM refresh_events
                WHERE ts >= ? AND id < ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (since, int(cursor), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, ts, refresh_id, plugin_id, instance, playlist, used_cached,
                       request_ms, generate_ms, preprocess_ms, display_ms
                FROM refresh_events
                WHERE ts >= ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (since, limit),
            ).fetchall()
        next_cursor = str(rows[-1]["id"]) if rows else None
        return jsonify(
            {
                "success": True,
                "items": [dict(r) for r in rows],
                "next_cursor": next_cursor,
            }
        )
    except Exception as e:
        return json_internal_error("benchmarks refreshes", details={"error": str(e)})
    finally:
        if conn:
            conn.close()


@settings_bp.route("/api/benchmarks/plugins")
def benchmarks_plugins():
    if not _benchmarks_enabled():
        return json_error("Benchmarks API disabled", status=404)
    conn = None
    try:
        since = _window_since_seconds(request.args.get("window", "24h"))
        conn = sqlite3.connect(_get_bench_db_path())
        conn.row_factory = sqlite3.Row
        _ensure_bench_schema(conn)
        rows = conn.execute(
            """
            SELECT plugin_id,
                   COUNT(*) AS runs,
                   AVG(request_ms) AS request_avg,
                   AVG(generate_ms) AS generate_avg,
                   AVG(display_ms) AS display_avg
            FROM refresh_events
            WHERE ts >= ?
            GROUP BY plugin_id
            ORDER BY runs DESC
            """,
            (since,),
        ).fetchall()
        items = []
        for r in rows:
            items.append(
                {
                    "plugin_id": r["plugin_id"],
                    "runs": int(r["runs"] or 0),
                    "request_avg": int(round(r["request_avg"])) if r["request_avg"] is not None else None,
                    "generate_avg": int(round(r["generate_avg"])) if r["generate_avg"] is not None else None,
                    "display_avg": int(round(r["display_avg"])) if r["display_avg"] is not None else None,
                }
            )
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return json_internal_error("benchmarks plugins", details={"error": str(e)})
    finally:
        if conn:
            conn.close()


@settings_bp.route("/api/benchmarks/stages")
def benchmarks_stages():
    if not _benchmarks_enabled():
        return json_error("Benchmarks API disabled", status=404)
    refresh_id = request.args.get("refresh_id")
    if not refresh_id:
        return json_error(
            "refresh_id is required",
            status=422,
            code="validation_error",
            details={"field": "refresh_id"},
        )
    conn = None
    try:
        conn = sqlite3.connect(_get_bench_db_path())
        conn.row_factory = sqlite3.Row
        _ensure_bench_schema(conn)
        rows = conn.execute(
            """
            SELECT id, ts, stage, duration_ms, extra_json
            FROM stage_events
            WHERE refresh_id = ?
            ORDER BY id ASC
            """,
            (refresh_id,),
        ).fetchall()
        return jsonify({"success": True, "items": [dict(r) for r in rows]})
    except Exception as e:
        return json_internal_error("benchmarks stages", details={"error": str(e)})
    finally:
        if conn:
            conn.close()


@settings_bp.route("/api/progress/stream")
def progress_stream():
    if os.getenv("INKYPI_PROGRESS_SSE_ENABLED", "true").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return json_error("Progress SSE disabled", status=404)

    bus = get_progress_bus()
    try:
        last_seq = int(request.args.get("last_seq", "0"))
    except Exception:
        last_seq = 0

    @stream_with_context
    def gen():
        # Backfill
        for ev in bus.recent(limit=100):
            if int(ev.get("seq", 0)) > last_seq:
                yield to_sse(str(ev.get("state", "event")), ev)
        local_seq = last_seq
        while True:
            events = bus.wait_for(local_seq, timeout_s=15.0)
            if not events:
                yield ": keep-alive\n\n"
                continue
            for ev in events:
                local_seq = max(local_seq, int(ev.get("seq", 0)))
                yield to_sse(str(ev.get("state", "event")), ev)

    return Response(gen(), mimetype="text/event-stream")


@settings_bp.route("/api/health/plugins")
def health_plugins():
    try:
        rt = current_app.config["REFRESH_TASK"]
        health = rt.get_health_snapshot() if hasattr(rt, "get_health_snapshot") else {}
        try:
            window_min = int(os.getenv("INKYPI_HEALTH_WINDOW_MIN", "1440") or "1440")
        except Exception:
            window_min = 1440
        if isinstance(health, dict) and window_min > 0:
            cutoff = datetime.now() - timedelta(minutes=window_min)
            filtered = {}
            for plugin_id, item in health.items():
                last_seen = item.get("last_seen") if isinstance(item, dict) else None
                if not last_seen:
                    filtered[plugin_id] = item
                    continue
                try:
                    dt = datetime.fromisoformat(last_seen)
                except Exception:
                    filtered[plugin_id] = item
                    continue
                if dt >= cutoff:
                    filtered[plugin_id] = item
            health = filtered
        return jsonify({"success": True, "items": health})
    except Exception as e:
        return json_internal_error("health plugins", details={"error": str(e)})


@settings_bp.route("/api/health/system")
def health_system():
    try:
        data: dict[str, Any] = {"success": True}
        try:
            import psutil  # type: ignore

            data["cpu_percent"] = psutil.cpu_percent(interval=None)
            data["memory_percent"] = psutil.virtual_memory().percent
            data["disk_percent"] = psutil.disk_usage("/").percent
            data["uptime_seconds"] = int(time.time() - psutil.boot_time())
        except Exception:
            data["cpu_percent"] = None
            data["memory_percent"] = None
            data["disk_percent"] = None
            data["uptime_seconds"] = None
        return jsonify(data)
    except Exception as e:
        return json_internal_error("health system", details={"error": str(e)})


@settings_bp.route("/settings/isolation", methods=["GET", "POST", "DELETE"])
def plugin_isolation():
    device_config = current_app.config["DEVICE_CONFIG"]
    isolated = device_config.get_config("isolated_plugins", default=[])
    if not isinstance(isolated, list):
        isolated = []

    if request.method == "GET":
        return jsonify({"success": True, "isolated_plugins": sorted(set(isolated))})

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return json_error("Request body must be a JSON object", status=400)
    plugin_id = body.get("plugin_id")
    if not isinstance(plugin_id, str) or not plugin_id.strip():
        return json_error(
            "plugin_id is required and must be a non-empty string",
            status=422,
            code="validation_error",
            details={"field": "plugin_id"},
        )

    if request.method == "POST":
        if plugin_id not in isolated:
            isolated.append(plugin_id)
            device_config.update_value("isolated_plugins", sorted(set(isolated)), write=True)
        return jsonify({"success": True, "isolated_plugins": sorted(set(isolated))})

    # DELETE
    isolated = [p for p in isolated if p != plugin_id]
    device_config.update_value("isolated_plugins", sorted(set(isolated)), write=True)
    return jsonify({"success": True, "isolated_plugins": sorted(set(isolated))})


@settings_bp.route("/settings/safe_reset", methods=["POST"])
def safe_reset():
    try:
        device_config = current_app.config["DEVICE_CONFIG"]
        config = device_config.get_config().copy()
        keep = {
            "playlist_config": config.get("playlist_config"),
            "plugins_enabled": config.get("plugins_enabled"),
            "name": config.get("name"),
            "timezone": config.get("timezone"),
            "time_format": config.get("time_format"),
            "display_type": config.get("display_type"),
            "resolution": config.get("resolution"),
            "orientation": config.get("orientation"),
            "preview_size_mode": config.get("preview_size_mode"),
        }
        # Reset selected runtime controls to safe defaults while preserving plugins/playlists.
        keep["plugin_cycle_interval_seconds"] = 3600
        keep["log_system_stats"] = False
        keep["isolated_plugins"] = []
        device_config.update_config(keep)
        return jsonify({"success": True, "message": "Safe reset applied."})
    except Exception as e:
        return json_internal_error("safe reset", details={"error": str(e)})


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
        include_keys = request.args.get("include_keys", "0").strip().lower() in (
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


_ALLOWED_IMPORT_CONFIG_KEYS = frozenset({
    "name", "resolution", "orientation", "timezone", "color_mode",
    "playlist_config", "refresh_info", "plugins",
    "plugin_cycle_interval_seconds", "time_format", "image_settings",
    "display_type", "preview_size_mode", "saved_settings",
    "inverted_image", "log_system_stats",
})

_ALLOWED_IMPORT_ENV_KEYS = frozenset({
    "OPEN_AI_SECRET", "OPEN_WEATHER_MAP_SECRET", "NASA_SECRET",
    "UNSPLASH_ACCESS_KEY", "GITHUB_SECRET", "GOOGLE_AI_SECRET",
})


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
            # Filter to allowed keys only
            filtered_cfg = {k: v for k, v in cfg.items() if k in _ALLOWED_IMPORT_CONFIG_KEYS}
            device_config.update_config(filtered_cfg)

        env_keys = payload.get("env_keys") or {}
        if isinstance(env_keys, dict):
            for k, v in env_keys.items():
                if k not in _ALLOWED_IMPORT_ENV_KEYS or v is None:
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
            if len(value) >= 4:
                return f"...{value[-4:]} ({len(value)} chars)"
            return f"set ({len(value)} chars)"
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
    api_key_plugins = {
        "OPEN_AI_SECRET": ["AI Image", "AI Text"],
        "OPEN_WEATHER_MAP_SECRET": ["Weather"],
        "NASA_SECRET": ["NASA APOD"],
        "UNSPLASH_ACCESS_KEY": ["Unsplash Background"],
        "GITHUB_SECRET": ["GitHub"],
    }
    return render_template(
        "api_keys.html",
        api_keys_mode="managed",
        entries=[],
        masked=masked,
        api_key_plugins=api_key_plugins,
    )


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
            return json_error(
                "Plugin cycle interval unit is required",
                status=422,
                code="validation_error",
                details={"field": "unit"},
            )
        if not interval or not interval.isnumeric():
            return json_error(
                "Refresh interval is required",
                status=422,
                code="validation_error",
                details={"field": "interval"},
            )
        if not form_data.get("timezoneName"):
            return json_error(
                "Time Zone is required",
                status=422,
                code="validation_error",
                details={"field": "timezoneName"},
            )
        if not time_format or time_format not in ["12h", "24h"]:
            return json_error(
                "Time format is required",
                status=422,
                code="validation_error",
                details={"field": "timeFormat"},
            )
        previous_interval_seconds = device_config.get_config(
            "plugin_cycle_interval_seconds"
        )
        plugin_cycle_interval_seconds = calculate_seconds(int(interval), unit)
        if plugin_cycle_interval_seconds > 86400 or plugin_cycle_interval_seconds <= 0:
            return json_error(
                "Plugin cycle interval must be less than 24 hours",
                status=422,
                code="validation_error",
                details={"field": "interval"},
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
        if "inky_saturation" in form_data:
            settings["image_settings"]["inky_saturation"] = float(form_data.get("inky_saturation", "0.5"))
        device_config.update_config(settings)

        if plugin_cycle_interval_seconds != previous_interval_seconds:
            # wake the background thread up to signal interval config change
            refresh_task = current_app.config["REFRESH_TASK"]
            refresh_task.signal_config_change()
    except RuntimeError:
        return json_error("An internal error occurred", status=500, code="internal_error")
    except Exception:
        logger.exception("Error saving device settings")
        return json_internal_error(
            "saving device settings",
            details={"hint": "Check numeric values and config file permissions."},
        )
    return jsonify({"success": True, "message": "Saved settings."})


# Legacy route aliases used by older UI/tests.
@settings_bp.route("/settings/device", methods=["GET", "POST"])
def save_device_settings():
    if request.method == "GET":
        return settings_page()
    return save_settings()


@settings_bp.route("/settings/display", methods=["GET", "POST"])
def save_display_settings():
    if request.method == "GET":
        return settings_page()
    return save_settings()


@settings_bp.route("/settings/network", methods=["GET", "POST"])
def save_network_settings():
    if request.method == "GET":
        return settings_page()
    return save_settings()


@settings_bp.route("/settings/client_log", methods=["POST"])
def client_log():
    """Accept lightweight client logs and emit them to server logs.

    Intended for front-end flows (e.g., browser geolocation) where we need
    visibility in terminal logs without failing the UX if logging fails.
    """
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return json_error("Request body must be a JSON object", status=400)
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


_last_shutdown_time: float = 0.0
_SHUTDOWN_COOLDOWN_SECONDS: float = 30.0
_shutdown_lock = threading.Lock()


@settings_bp.route("/shutdown", methods=["POST"])
def shutdown():
    """Reboot or shut down the device.

    Rate-limited to one call per 30 seconds to prevent accidental repeats.
    """
    global _last_shutdown_time
    now = time.monotonic()
    with _shutdown_lock:
        if now - _last_shutdown_time < _SHUTDOWN_COOLDOWN_SECONDS:
            remaining = int(_SHUTDOWN_COOLDOWN_SECONDS - (now - _last_shutdown_time))
            return json_error(
                f"Please wait {remaining}s before requesting another reboot/shutdown",
                status=429,
            )
        _last_shutdown_time = now

    data = request.get_json(silent=True)
    if data is None and request.content_type and "application/json" in request.content_type:
        return json_error("Invalid JSON payload", status=400)
    if not isinstance(data, dict):
        data = {}
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
