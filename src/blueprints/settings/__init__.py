# pyright: reportMissingImports=false, reportMissingTypeStubs=false, reportMissingModuleSource=false, reportRedeclaration=false
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    current_app,
)

from utils.http_utils import http_get
from utils.progress_events import get_progress_bus
from utils.rate_limiter import CooldownLimiter, SlidingWindowLimiter
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
UPDATE_SCRIPT_NAMES = ("do_update.sh", "update.sh")

# Strict allow-lists for systemd-run command construction (JTN-319).
# CodeQL py/command-line-injection flagged _start_update_via_systemd because
# the validation was not visible to static analysis. The regexes below make
# the validation explicit so both CodeQL and human reviewers can see it.
#
# Script basenames that are allowed to be executed by _start_update_via_systemd.
# The full path is additionally required to be absolute and to match a strict
# POSIX-safe character class — see _sanitize_update_argv. The inline regex
# patterns at the call sites are intentionally not pre-compiled so CodeQL can
# constant-fold them for sanitiser recognition.
_ALLOWED_UPDATE_SCRIPT_BASENAMES = frozenset(UPDATE_SCRIPT_NAMES)

# Guardrails and limits for logs APIs
MAX_LOG_HOURS = 24
MIN_LOG_HOURS = 1
MAX_LOG_LINES = 2000
MIN_LOG_LINES = 50
MAX_RESPONSE_BYTES = 512 * 1024

# Strict semver pattern for update target tags (e.g. "v1.2.3", "1.0.0-rc1")
_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+(-[\w.]+)?$")  # 512 KB safety cap

# Simple in-process rate limiter (per remote addr)
_logs_limiter = SlidingWindowLimiter(120, 60)

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
    """Thin wrapper kept for test compatibility (monkeypatching)."""
    key = remote_addr or "unknown"
    allowed, _ = _logs_limiter.check(key)
    return allowed


def _clamp_int(value: str | None, default: int, min_value: int, max_value: int) -> int:
    try:
        if value is None:
            return default
        parsed = int(value)
        return max(min_value, min(parsed, max_value))
    except Exception:
        return default


def _format_journal_line(formatted_ts: str, data: dict) -> str:
    priority = str(data.get("PRIORITY", "6"))
    level = _PRIORITY_TO_LEVEL.get(priority, "INFO")
    msg = (data.get("MESSAGE", "") or "").rstrip()
    return f"{formatted_ts} [{level}] {msg}"


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
                line = _format_journal_line(formatted_ts, data)
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


# ---------------------------------------------------------------------------
# JTN-319: command-line-injection sanitiser.
#
# Sanitises (script_path, target_tag) for the two functions that exec the
# update script via subprocess.Popen. Inline ``re.fullmatch`` guards against
# strict character classes are what CodeQL's built-in py/command-line-injection
# sanitiser recognition expects, so this helper exists as a *generator*
# function (returning the validated values via tuple) rather than a plain
# function call — keeping the regex guards inline at every Popen call site
# would be true duplication, but a yield-based helper still inlines the
# guards in the caller's frame.
# ---------------------------------------------------------------------------


def _sanitize_update_argv(
    script_path: str, target_tag: str | None
) -> tuple[str, str | None]:
    """Validate update script path and target tag for ``subprocess.Popen``.

    Returns the (script_path, target_tag) pair unchanged if every guard
    passes; raises ``ValueError`` otherwise. Callers must additionally
    apply the inline ``re.fullmatch`` guard pattern at their own Popen
    call site so CodeQL recognises the sanitisation.
    """
    if (
        not isinstance(script_path, str)
        or not script_path
        or not re.fullmatch(r"^/[A-Za-z0-9_./-]{1,255}$", script_path)
        or ".." in script_path.split("/")
        or os.path.basename(script_path) not in _ALLOWED_UPDATE_SCRIPT_BASENAMES
    ):
        raise ValueError(f"Invalid update script path: {script_path!r}")
    if target_tag is not None and (
        not isinstance(target_tag, str)
        or not re.fullmatch(r"^v?\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?$", target_tag)
    ):
        raise ValueError(f"Invalid target tag format: {target_tag!r}")
    return script_path, target_tag


def _start_update_via_systemd(
    unit_name: str, script_path: str, target_tag: str | None = None
) -> None:
    """Launch the update script in a transient systemd unit.

    Security (JTN-319 / CodeQL py/command-line-injection):
        All three parameters that could influence the ``subprocess.Popen``
        argv are validated against strict regex character classes inline,
        so CodeQL's built-in regex sanitiser recognition can see the
        guards. ``_sanitize_update_argv`` performs the script-path and
        target-tag checks; the unit-name check stays inline below.
    """
    # Inline unit-name guard — kept here (rather than in a helper) so the
    # ``re.fullmatch`` sanitiser is in the same frame as the Popen call.
    if not isinstance(unit_name, str) or not re.fullmatch(
        r"^inkypi-(?:update|rollback)-\d{1,20}$", unit_name
    ):
        raise ValueError(f"Invalid systemd unit name: {unit_name!r}")
    script_path, target_tag = _sanitize_update_argv(script_path, target_tag)

    # Run update script in a transient systemd unit so its logs are visible in
    # journal. Every argv element below is either a string literal or has
    # passed an inline ``re.fullmatch`` sanitiser above.
    project_dir = os.getenv("PROJECT_DIR", "/usr/local/inkypi")
    if (
        not isinstance(project_dir, str)
        or not project_dir
        or not re.fullmatch(r"^/[A-Za-z0-9_./-]{1,255}$", project_dir)
        or ".." in project_dir.split("/")
    ):
        project_dir = "/usr/local/inkypi"

    cmd: list[str] = [
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
    subprocess.Popen(cmd)  # noqa: S603  # all inputs sanitized; shell=False


def _log_and_publish(msg: str, level: str = "info"):
    """Log and publish update progress to the SSE bus."""
    getattr(logger, level)("update | %s", msg)
    try:
        bus = get_progress_bus()
        bus.publish({"type": "update_log", "line": msg})
    except Exception:
        pass


def _run_real_update(script_path: str, target_tag: str | None = None) -> None:
    # Defense-in-depth (JTN-319): apply the same sanitisation as
    # _start_update_via_systemd so this fallback path cannot be coerced
    # into executing an arbitrary script. The inline regex guard immediately
    # below the helper call is what CodeQL recognises as a sanitiser.
    script_path, target_tag = _sanitize_update_argv(script_path, target_tag)
    if not re.fullmatch(r"^/[A-Za-z0-9_./-]{1,255}$", script_path):
        raise ValueError(f"Invalid update script path: {script_path!r}")
    if target_tag is not None and not re.fullmatch(
        r"^v?\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?$", target_tag
    ):
        raise ValueError(f"Invalid target tag format: {target_tag!r}")

    cmd: list[str] = ["/bin/bash", script_path]
    if target_tag:
        cmd.append(target_tag)
    proc = subprocess.Popen(  # noqa: S603  # all inputs sanitized; shell=False
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
            timeout=5,
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
_shutdown_limiter = CooldownLimiter(30)


# ---------------------------------------------------------------------------
# Route handlers are split into sub-modules for maintainability.
# Import them here so they register their routes on settings_bp.
# ---------------------------------------------------------------------------
from . import _benchmarks, _config, _health, _logs, _system, _updates  # noqa: E402,F401

__all__ = ["settings_bp"]

# Re-export route functions that tests or external code access via the package
health_system = _health.health_system
