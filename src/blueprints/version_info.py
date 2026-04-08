"""Version and uptime info endpoints (JTN-360).

These endpoints are intentionally accessible WITHOUT authentication.
They expose read-only metadata useful for monitoring dashboards,
deployment verification, and support workflows.

Routes
------
GET /api/version/info
    Returns: version, git_sha, git_branch, build_time, python_version

GET /api/uptime
    Returns: process_uptime_seconds, system_uptime_seconds, process_started_at
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from flask import Blueprint, jsonify

version_info_bp = Blueprint("version_info", __name__)

# ---------------------------------------------------------------------------
# Module-level constants — computed once at import time, never on each request
# ---------------------------------------------------------------------------

_PROCESS_START_TIME: float = time.monotonic()
_PROCESS_START_DATETIME: datetime = datetime.now(UTC)


def _read_app_version() -> str:
    """Read the application version from the VERSION file at the repo root."""
    try:
        version_path = Path(__file__).parent.parent.parent / "VERSION"
        return version_path.read_text().strip()
    except Exception:
        return "unknown"


def _run_git(*args: str) -> str:
    """Run a git command and return stdout, or 'unknown' on any error."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _read_build_time() -> str:
    """Return build timestamp from build_time.txt if present, else process start ISO."""
    try:
        build_path = Path(__file__).parent.parent.parent / "build_time.txt"
        text = build_path.read_text().strip()
        if text:
            return text
    except Exception:
        pass
    return _PROCESS_START_DATETIME.isoformat()


# Cached at module import — never recomputed per request
_APP_VERSION: str = _read_app_version()
_GIT_SHA: str = _run_git("rev-parse", "--short", "HEAD")
_GIT_BRANCH: str = _run_git("rev-parse", "--abbrev-ref", "HEAD")
_BUILD_TIME: str = _read_build_time()
_PYTHON_VERSION: str = sys.version


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@version_info_bp.route("/api/version/info", methods=["GET"])
def api_version_info():
    """Return build and runtime version metadata.

    All fields are read-only. git_sha and git_branch may be 'unknown' in
    environments where git is not installed or the repo history is unavailable
    (e.g. Docker images built without .git).
    """
    return jsonify(
        {
            "version": _APP_VERSION,
            "git_sha": _GIT_SHA,
            "git_branch": _GIT_BRANCH,
            "build_time": _BUILD_TIME,
            "python_version": _PYTHON_VERSION,
        }
    )


def _system_uptime_seconds() -> int | None:
    """Return system uptime in seconds from /proc/uptime (Linux only).

    Returns None on macOS, Windows, or any read/parse failure.
    """
    try:
        text = Path("/proc/uptime").read_text()
        return int(float(text.split()[0]))
    except Exception:
        return None


@version_info_bp.route("/api/uptime", methods=["GET"])
def api_uptime():
    """Return process and system uptime information."""
    process_uptime = time.monotonic() - _PROCESS_START_TIME
    return jsonify(
        {
            "process_uptime_seconds": process_uptime,
            "system_uptime_seconds": _system_uptime_seconds(),
            "process_started_at": _PROCESS_START_DATETIME.isoformat(),
        }
    )
