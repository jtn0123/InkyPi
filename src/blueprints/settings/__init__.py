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
from datetime import UTC, datetime, timedelta

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
# JTN-708: rollback.sh reverts to the tag recorded in /var/lib/inkypi/prev_version.
# It's gated separately from the forward-update path because rollback.sh only
# runs after a failed update (guard enforced at the Flask route level) and
# delegates to update.sh internally.
ROLLBACK_SCRIPT_NAME = "rollback.sh"

# Strict allow-lists for systemd-run command construction (JTN-319).
# CodeQL py/command-line-injection flagged _start_update_via_systemd because
# the validation was not visible to static analysis. The regexes below make
# the validation explicit so both CodeQL and human reviewers can see it.
#
# Script basenames that are allowed to be executed by _start_update_via_systemd.
# The full path is additionally required to be an absolute, canonicalised
# (realpath-resolved) path that lives under one of the trusted install roots
# below — see _validate_update_script_path. Inline ``re.fullmatch`` guards at
# every Popen call site are intentionally not pre-compiled so CodeQL can
# constant-fold them for sanitiser recognition.
_ALLOWED_UPDATE_SCRIPT_BASENAMES = frozenset(UPDATE_SCRIPT_NAMES)
# JTN-708: the rollback script is validated through the same trusted-root /
# basename allow-list machinery as do_update.sh / update.sh.  Keeping a
# dedicated frozenset (rather than adding rollback.sh to
# _ALLOWED_UPDATE_SCRIPT_BASENAMES) means an accidental call to
# _start_update_via_systemd cannot resolve to rollback.sh and vice-versa.
_ALLOWED_ROLLBACK_SCRIPT_BASENAMES = frozenset((ROLLBACK_SCRIPT_NAME,))

# Trusted install roots for update scripts. The realpath of any script we are
# willing to exec via subprocess.Popen MUST be inside one of these directories.
# Repo-relative developer environments are added at runtime via
# ``_trusted_update_dirs()`` so this constant remains a hardcoded literal.
_TRUSTED_UPDATE_DIRS: tuple[str, ...] = (
    "/usr/local/inkypi/install",
    "/opt/inkypi/install",
)

# Hardcoded literal prefix for the transient systemd unit. The dynamic suffix
# is appended in-function from a Python int (time.time()) so the final string
# is provably not user-influenced.
_UPDATE_UNIT_PREFIX = "inkypi-update"
# JTN-708: distinct prefix for rollback transient units so operators (and the
# status endpoint) can distinguish a rollback from a forward update via
# ``systemctl list-units 'inkypi-rollback-*'``.
_ROLLBACK_UNIT_PREFIX = "inkypi-rollback"

# S1192: the canonical PROJECT_DIR + bash interpreter are referenced from
# multiple Popen call sites (_start_update_via_systemd / _start_rollback_via_systemd
# / _get_*_script_path fallbacks), so pull them to module-level constants.
_DEFAULT_PROJECT_DIR = "/usr/local/inkypi"
_BASH_INTERPRETER = "/bin/bash"

# Guardrails and limits for logs APIs
MAX_LOG_HOURS = 24
MIN_LOG_HOURS = 1
MAX_LOG_LINES = 2000
MIN_LOG_LINES = 50
MAX_RESPONSE_BYTES = 512 * 1024

# Strict semver pattern for update target tags (e.g. "v1.2.3", "1.0.0-rc1").
# IMPORTANT: this MUST stay byte-for-byte equivalent to the bash regex used in
# install/do_update.sh — both validators only accept ``v?\d+\.\d+\.\d+`` with
# an optional ``-[A-Za-z0-9.]+`` suffix (no underscores; \w in Python would
# diverge from POSIX bracket classes). ``re.ASCII`` keeps ``\d`` limited to
# ``[0-9]`` so Unicode digit spoofing (e.g. Arabic-Indic numerals) cannot
# smuggle a value past the validator.
_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$", re.ASCII)

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
            timestamp = datetime.fromtimestamp(record.created, tz=UTC).strftime(
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
                ts = datetime.fromtimestamp(
                    record.get_realtime_usec() / 1_000_000, tz=UTC
                )
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
                ts = datetime.fromtimestamp(ts_usec / 1_000_000, tz=UTC)
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


def _get_rollback_script_path() -> str | None:
    """Return absolute path to ``install/rollback.sh`` (JTN-708).

    Uses the same candidate cascade as ``_get_update_script_path`` so a
    developer running the Flask app from a repo checkout sees the in-repo
    rollback.sh, while a production install picks up the
    ``/usr/local/inkypi/install/rollback.sh`` copy.
    """
    candidates: list[str] = []
    project_dir = os.getenv("PROJECT_DIR")

    def add_install_candidate(base_dir: str) -> None:
        candidates.append(os.path.join(base_dir, "install", ROLLBACK_SCRIPT_NAME))

    if project_dir:
        src_link = os.path.join(project_dir, "src")
        if os.path.islink(src_link):
            repo_root = os.path.dirname(os.path.realpath(src_link))
            add_install_candidate(repo_root)
        add_install_candidate(project_dir)

    here = os.path.dirname(os.path.abspath(__file__))
    repo_install = os.path.abspath(os.path.join(here, "..", "..", "..", "install"))
    candidates.append(os.path.join(repo_install, ROLLBACK_SCRIPT_NAME))

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


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
# JTN-319: command-line-injection sanitisers.
#
# CodeQL's py/command-line-injection taint tracker does not propagate sanitiser
# recognition across helper boundaries — the regex guard MUST be visible in
# the same function that calls subprocess.Popen.  We therefore:
#
#   1. Drop ``unit_name``/``script_path`` parameters from
#      ``_start_update_via_systemd`` entirely.  The unit name is built from a
#      hardcoded literal prefix plus a Python int, and the script path is
#      resolved internally via ``_get_update_script_path`` (which itself only
#      walks a fixed candidate list under PROJECT_DIR).
#   2. Validate the resolved script path against a hardcoded list of trusted
#      install roots via ``os.path.realpath`` so symlinks/path-traversal can
#      not escape the allow-list.
#   3. The only parameter that survives is ``target_tag``, and it is matched
#      against ``_TAG_RE`` inline immediately above the Popen call so CodeQL
#      sees the regex sanitiser in the same frame.
# ---------------------------------------------------------------------------


def _trusted_update_dirs() -> tuple[str, ...]:
    """Return the canonical list of directories whose update scripts are exec-allowed.

    The hardcoded ``_TRUSTED_UPDATE_DIRS`` constants are joined with the
    repo-relative ``install/`` directory (developer environments) and the
    realpath of ``$PROJECT_DIR/install`` if PROJECT_DIR is set.  All entries
    are passed through ``os.path.realpath`` so the comparison in
    ``_validate_update_script_path`` is symlink-safe.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    repo_install = os.path.abspath(os.path.join(here, "..", "..", "..", "install"))
    dirs = list(_TRUSTED_UPDATE_DIRS) + [repo_install]
    project_dir = os.getenv("PROJECT_DIR")
    if project_dir and isinstance(project_dir, str) and project_dir.startswith("/"):
        dirs.append(os.path.join(project_dir, "install"))
        # Follow the src→repo symlink production install layout uses.
        src_link = os.path.join(project_dir, "src")
        if os.path.islink(src_link):
            try:
                repo_root = os.path.dirname(os.path.realpath(src_link))
                dirs.append(os.path.join(repo_root, "install"))
            except OSError:
                pass
    return tuple(os.path.realpath(d) for d in dirs)


def _validate_update_script_path(script_path: str) -> str:
    """Resolve and validate an update script path against trusted install roots.

    Returns the canonical (realpath-resolved) path on success.  Raises
    ``ValueError`` if the path is non-string, empty, has a disallowed
    basename, or — after symlink resolution — does not live under one of
    the trusted install directories from ``_trusted_update_dirs``.
    """
    if not isinstance(script_path, str) or not script_path:
        raise ValueError(f"Invalid update script path: {script_path!r}")
    real = os.path.realpath(script_path)
    # Symlink-safe trusted-root enforcement: ``commonpath`` is the canonical
    # primitive for "is X under directory Y" without TOCTOU prefix-string
    # tricks.  Both arguments are absolute realpaths so commonpath cannot
    # raise on differing drives (POSIX-only project).
    trusted = _trusted_update_dirs()
    in_trusted_root = False
    for root in trusted:
        try:
            if os.path.commonpath([real, root]) == root:
                in_trusted_root = True
                break
        except ValueError:
            # Different filesystem roots; not a match.
            continue
    if not in_trusted_root:
        raise ValueError(
            f"Invalid update script path (not under trusted root): {script_path!r}"
        )
    if os.path.basename(real) not in _ALLOWED_UPDATE_SCRIPT_BASENAMES:
        raise ValueError(f"Invalid update script basename: {script_path!r}")
    return real


def _start_update_via_systemd(target_tag: str | None = None) -> str:
    """Launch the update script in a transient systemd unit.

    Returns the ``inkypi-update-<ts>`` unit name actually passed to
    systemd-run so the caller can record the real value in
    ``_UPDATE_STATE["unit"]`` — previously the caller generated its own
    ``int(time.time())`` unit breadcrumb and the two could differ by a
    second, causing the reaper's ``systemctl is-active`` probe to query
    a non-existent unit.

    Security (JTN-319 / CodeQL py/command-line-injection):
        All argv elements passed to ``subprocess.Popen`` are either string
        literals, values derived from hardcoded constants, or — for
        ``target_tag`` — matched against the strict ``_TAG_RE`` semver regex
        in the same function frame so CodeQL's built-in regex sanitiser
        recognition can see the guard.
    """
    # 1. Regex sanitiser — ``_TAG_RE`` is a module-level ``re.Pattern`` compiled
    #    with ``re.ASCII``; CodeQL's Python security model recognises
    #    ``re.Pattern.fullmatch`` as a sanitiser just like the inline form.
    if target_tag is not None and not _TAG_RE.fullmatch(target_tag):
        raise ValueError(f"Invalid target tag format: {target_tag!r}")

    # 2. Resolve PROJECT_DIR from a hardcoded default and validate it has the
    #    shape of an absolute POSIX path.  Anything user-controlled (env var)
    #    falls back to the literal default.
    project_dir = os.getenv("PROJECT_DIR", "/usr/local/inkypi")
    if (
        not isinstance(project_dir, str)
        or not re.fullmatch(r"^/[A-Za-z0-9_./-]{1,255}$", project_dir)
        or ".." in project_dir.split("/")
    ):
        project_dir = "/usr/local/inkypi"

    # 3. Resolve the script path purely from internal candidates (the helper
    #    walks a fixed list under PROJECT_DIR / repo-relative install/) and
    #    re-validate against the trusted-root allow-list.  No caller can
    #    influence this string.
    candidate = _get_update_script_path() or "/usr/local/inkypi/install/do_update.sh"
    script_path = _validate_update_script_path(candidate)

    # 4. Build the unit name from a hardcoded literal prefix + a fresh int.
    unit_name = f"{_UPDATE_UNIT_PREFIX}-{int(time.time())}"

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
    if target_tag is not None:
        cmd.append(target_tag)
    # All argv elements above are either string literals or have been
    # validated by the inline ``re.fullmatch`` guards / trusted-root check.
    subprocess.Popen(cmd)  # noqa: S603  # all inputs sanitized; shell=False
    return f"{unit_name}.service"


def _validate_rollback_script_path(script_path: str) -> str:
    """JTN-708 — mirror ``_validate_update_script_path`` for rollback.sh.

    Same trusted-root machinery as the update-script validator; the only
    difference is the allowed basename, so a mis-wired caller cannot exec
    do_update.sh through the rollback path or vice-versa.
    """
    if not isinstance(script_path, str) or not script_path:
        raise ValueError(f"Invalid rollback script path: {script_path!r}")
    real = os.path.realpath(script_path)
    trusted = _trusted_update_dirs()
    in_trusted_root = False
    for root in trusted:
        try:
            if os.path.commonpath([real, root]) == root:
                in_trusted_root = True
                break
        except ValueError:
            continue
    if not in_trusted_root:
        raise ValueError(
            f"Invalid rollback script path (not under trusted root): {script_path!r}"
        )
    if os.path.basename(real) not in _ALLOWED_ROLLBACK_SCRIPT_BASENAMES:
        raise ValueError(f"Invalid rollback script basename: {script_path!r}")
    return real


def _start_rollback_via_systemd() -> str:
    """Launch rollback.sh in a transient systemd unit (JTN-708).

    Returns the ``inkypi-rollback-<ts>.service`` unit name so callers can
    record the real value in ``_UPDATE_STATE["unit"]`` instead of a
    separately-generated breadcrumb (same fix as _start_update_via_systemd).

    Security posture mirrors ``_start_update_via_systemd``:
        * No caller-controlled values flow into argv — the script path is
          resolved internally via ``_get_rollback_script_path`` and then
          canonicalised + trusted-root-checked via
          ``_validate_rollback_script_path``.
        * The transient unit name is a hardcoded literal prefix plus a fresh
          ``int(time.time())`` so CodeQL can statically prove the value is not
          user-influenced.
        * PROJECT_DIR defaults to the hardcoded ``/usr/local/inkypi``; any
          environment override is re-validated against a strict absolute-POSIX
          path regex before being passed through.
    """
    project_dir = os.getenv("PROJECT_DIR", _DEFAULT_PROJECT_DIR)
    if (
        not isinstance(project_dir, str)
        or not re.fullmatch(r"^/[A-Za-z0-9_./-]{1,255}$", project_dir)
        or ".." in project_dir.split("/")
    ):
        project_dir = _DEFAULT_PROJECT_DIR

    candidate = (
        _get_rollback_script_path()
        or f"{_DEFAULT_PROJECT_DIR}/install/{ROLLBACK_SCRIPT_NAME}"
    )
    script_path = _validate_rollback_script_path(candidate)

    unit_name = f"{_ROLLBACK_UNIT_PREFIX}-{int(time.time())}"

    cmd: list[str] = [
        "systemd-run",
        "--collect",
        f"--unit={unit_name}",
        "--property=StandardOutput=journal",
        "--property=StandardError=journal",
        f"--setenv=PROJECT_DIR={project_dir}",
        _BASH_INTERPRETER,
        script_path,
    ]
    # All argv elements above are string literals or validated internal values.
    subprocess.Popen(cmd)  # noqa: S603  # all inputs sanitized; shell=False
    return f"{unit_name}.service"


def _log_and_publish(msg: str, level: str = "info"):
    """Log and publish update progress to the SSE bus."""
    getattr(logger, level)("update | %s", msg)
    try:
        bus = get_progress_bus()
        bus.publish({"type": "update_log", "line": msg})
    except Exception:
        pass


def _run_real_update(script_path: str, target_tag: str | None = None) -> None:
    # Defense-in-depth (JTN-319): ``_TAG_RE`` (module-level compiled pattern,
    # ASCII-only) sanitises ``target_tag`` and ``_validate_update_script_path``
    # resolves ``script_path`` to a canonical trusted-root path — both in the
    # same frame as the Popen call so CodeQL's sanitiser recognition fires.
    if target_tag is not None and not _TAG_RE.fullmatch(target_tag):
        raise ValueError(f"Invalid target tag format: {target_tag!r}")
    # ``_validate_update_script_path`` returns the canonicalised realpath; the
    # original (possibly symlinked) input is dropped so the value flowing into
    # Popen is provably under a trusted install root.
    script_path = _validate_update_script_path(script_path)

    cmd: list[str] = ["/bin/bash", script_path]
    if target_tag is not None:
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
    # Surface why the last check failed so the UI can distinguish "on latest"
    # from "we never managed to reach GitHub." Cleared on a successful fetch.
    "last_error": None,
}
_VERSION_CACHE_TTL = 3600  # 1 hour


def _semver_gt(a: str, b: str) -> bool:
    """Return True if semver string *a* is strictly greater than *b*."""
    try:
        return tuple(int(x) for x in a.split(".")) > tuple(int(x) for x in b.split("."))
    except (ValueError, AttributeError):
        return False


def _check_latest_version(force_refresh: bool = False) -> str | None:
    """Fetch the latest release tag from the GitHub Releases API.

    Returns the latest version string on success or ``None`` on any failure.
    When the check fails, ``_VERSION_CACHE['last_error']`` is populated with a
    short human-readable reason so the UI can report it to the user instead
    of silently claiming "on latest".

    When ``force_refresh`` is True the cache is bypassed — this is what the
    "Check for updates" button needs so a manual click always hits GitHub.
    """
    now = time.time()
    if (
        not force_refresh
        and _VERSION_CACHE["latest"]
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
            _VERSION_CACHE["last_error"] = None
            return latest
        # Response decoded but the tag isn't a stable X.Y.Z release (e.g. a
        # pre-release tag like v1.2.3-rc1). That's not a network failure, it
        # just means there's nothing auto-installable. Record a message the
        # client can show verbatim so we don't misreport this as "couldn't
        # reach GitHub".
        logger.warning(
            "Latest GitHub release tag %r is not a stable X.Y.Z release; "
            "auto-update skipped.",
            tag,
        )
        _VERSION_CACHE["last_error"] = (
            f"Latest GitHub release ({tag!r}) is not a stable X.Y.Z tag — "
            "nothing to auto-install yet."
        )
    except Exception as exc:
        # Bubble up a short reason to the client. Log at INFO so it lands in
        # the in-app log panel without spamming errors on every check.
        reason = str(exc) or exc.__class__.__name__
        logger.info("Version check via GitHub API failed: %s", reason)
        _VERSION_CACHE["last_error"] = f"Couldn't reach GitHub: {reason}"
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
