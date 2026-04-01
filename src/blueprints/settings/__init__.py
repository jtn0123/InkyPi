# pyright: reportMissingImports=false, reportMissingTypeStubs=false, reportMissingModuleSource=false, reportRedeclaration=false
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

from flask import (
    Blueprint,
    current_app,
)

from utils.http_utils import http_get
from utils.progress_events import get_progress_bus
from utils.time_utils import get_timezone, now_device_tz

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

LOG_TIMESTAMP_FORMAT = "%b %d %H:%M:%S"
UPDATE_SCRIPT_NAMES = ("do_update.sh", "update.sh")

# Guardrails and limits for logs APIs
MAX_LOG_HOURS = 24
MIN_LOG_HOURS = 1
MAX_LOG_LINES = 2000
MIN_LOG_LINES = 50
MAX_RESPONSE_BYTES = 512 * 1024

# Strict semver pattern for update target tags (e.g. "v1.2.3", "1.0.0-rc1")
_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+(-[\w.]+)?$")  # 512 KB safety cap

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
    val = window.strip().lower()
    try:
        if val.endswith("h"):
            return now - (int(val[:-1]) * 3600)
        if val.endswith("m"):
            return now - (int(val[:-1]) * 60)
        if val.endswith("d"):
            return now - (int(val[:-1]) * 86400)
    except ValueError:
        logger.warning("Invalid benchmark window provided, defaulting to 24h")
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
            timestamp = datetime.fromtimestamp(record.created).strftime(
                LOG_TIMESTAMP_FORMAT
            )
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
        lines.append(
            f"Showing logs from the last {hours} hours (max {DEV_LOG_BUFFER_SIZE} entries)"
        )
        lines.append(
            "For complete logs, check your terminal output where Flask is running."
        )
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
                formatted_ts = ts.strftime(LOG_TIMESTAMP_FORMAT)
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
                formatted_ts = ts.strftime(LOG_TIMESTAMP_FORMAT)
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
_update_lock = threading.Lock()


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

    def add_install_candidates(base_dir: str) -> None:
        install_dir = os.path.join(base_dir, "install")
        candidates.extend(
            [
                os.path.join(install_dir, script_name)
                for script_name in UPDATE_SCRIPT_NAMES
            ]
        )

    # Resolve the real repo root by following the src symlink (production layout)
    if project_dir:
        src_link = os.path.join(project_dir, "src")
        if os.path.islink(src_link):
            repo_root = os.path.dirname(os.path.realpath(src_link))
            add_install_candidates(repo_root)
        # Direct PROJECT_DIR/install paths
        add_install_candidates(project_dir)

    # Repo-relative path (this file: src/blueprints/settings/__init__.py → repo_root/install/)
    here = os.path.dirname(os.path.abspath(__file__))
    repo_install = os.path.abspath(os.path.join(here, "..", "..", "..", "install"))
    candidates.extend(
        [os.path.join(repo_install, script_name) for script_name in UPDATE_SCRIPT_NAMES]
    )

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
    with _update_lock:
        if not running and _UPDATE_STATE.get("unit"):
            _UPDATE_STATE["last_unit"] = _UPDATE_STATE["unit"]
        _UPDATE_STATE["running"] = bool(running)
        _UPDATE_STATE["unit"] = unit
        _UPDATE_STATE["started_at"] = float(time.time()) if running else None


def _start_update_via_systemd(
    unit_name: str, script_path: str, target_tag: str | None = None
) -> None:
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


def _log_and_publish(msg: str, level: str = "info"):
    """Log and publish update progress to the SSE bus."""
    getattr(logger, level)("update | %s", msg)
    try:
        bus = get_progress_bus()
        bus.publish({"type": "update_log", "line": msg})
    except Exception:
        pass


def _run_real_update(script_path: str, target_tag: str | None = None) -> None:
    cmd = ["/bin/bash", script_path]
    if target_tag:
        cmd.append(target_tag)
    proc = subprocess.Popen(
        cmd,
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


def _run_simulated_update(target_tag: str | None = None) -> None:
    messages = ["Simulated update starting..."]
    if target_tag:
        messages.append(f"Requested target version: {target_tag}")
    messages.extend(
        [
            "Checking connectivity...",
            "Fetching latest dependencies...",
            "Updating application files...",
            "Restarting service...",
            "Update completed.",
        ]
    )
    for msg in messages:
        _log_and_publish(msg)
        time.sleep(0.5)


def _update_runner(script_path: str | None, target_tag: str | None = None) -> None:
    try:
        _log_and_publish("web_update: starting")
        if (
            script_path
            and os.path.isfile(script_path)
            and os.access(script_path, os.X_OK)
        ):
            # Do not run the real script unless explicitly enabled
            allow_real = os.getenv("INKYPI_ALLOW_REAL_UPDATE", "0").strip() in (
                "1",
                "true",
                "yes",
            )
            if allow_real:
                _run_real_update(script_path, target_tag=target_tag)
            else:
                _run_simulated_update(target_tag=target_tag)
        else:
            for i in range(6):
                _log_and_publish(f"step {i + 1}/6")
                time.sleep(0.5)
            if target_tag:
                _log_and_publish(f"Requested target version: {target_tag}")
            _log_and_publish("done (simulated)")
    except Exception:
        logger.exception("web_update: exception while running update")
    finally:
        _set_update_state(False, None)


def _start_update_fallback_thread(
    script_path: str | None, target_tag: str | None = None
) -> None:
    # Development/macOS path: run a simulated update and pipe output into our logger
    # to make it visible in inkypi.service logs and the UI viewer.
    t = threading.Thread(
        target=_update_runner,
        args=(script_path, target_tag),
        name="update-fallback",
        daemon=True,
    )
    t.start()


# --- Version check via GitHub Releases API ---
_GITHUB_REPO = os.getenv("INKYPI_GITHUB_REPO", "jtn0123/InkyPi")
_VERSION_CACHE: dict[str, object] = {
    "latest": None,
    "checked_at": 0.0,
    "release_notes": None,
}
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
    if (
        _VERSION_CACHE["latest"]
        and (now - float(_VERSION_CACHE["checked_at"] or 0)) < _VERSION_CACHE_TTL
    ):
        return _VERSION_CACHE["latest"]  # type: ignore[return-value]
    try:
        resp = http_get(
            f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest",
            timeout=10,
            headers={"Accept": "application/vnd.github.v3+json"},
            use_cache=False,
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


# Import allowlists for settings import
_ALLOWED_IMPORT_CONFIG_KEYS = frozenset(
    {
        "name",
        "resolution",
        "orientation",
        "timezone",
        "color_mode",
        "playlist_config",
        "refresh_info",
        "plugins",
        "plugin_cycle_interval_seconds",
        "time_format",
        "image_settings",
        "display_type",
        "preview_size_mode",
        "saved_settings",
        "inverted_image",
        "log_system_stats",
    }
)

_ALLOWED_IMPORT_ENV_KEYS = frozenset(
    {
        "OPEN_AI_SECRET",
        "OPEN_WEATHER_MAP_SECRET",
        "NASA_SECRET",
        "UNSPLASH_ACCESS_KEY",
        "GITHUB_SECRET",
        "GOOGLE_AI_SECRET",
    }
)

# Shutdown rate limiting
_last_shutdown_time: float = 0.0
_SHUTDOWN_COOLDOWN_SECONDS: float = 30.0
_shutdown_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Route handlers are split into sub-modules for maintainability.
# Import them here so they register their routes on settings_bp.
# ---------------------------------------------------------------------------
from . import _benchmarks, _config, _health, _logs, _system, _updates  # noqa: E402,F401

__all__ = ["settings_bp"]

# Re-export route functions that tests or external code access via the package
health_system = _health.health_system
