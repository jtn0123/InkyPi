"""Consolidated diagnostics endpoint (JTN-707).

Surfaces uptime, memory, disk, refresh-task status, plugin health, a tail of
recent log lines, version info, and the last update failure in a single JSON
response. Designed for:

* Support flows ("what's going on with my Pi right now?") without SSH.
* Downstream UI consumers — M2 status badge, K3 rollback UI.

Access control
--------------
The endpoint rides on the app-wide PIN auth gate (see ``app_setup/auth.py``)
when it is enabled. When PIN auth is *disabled* (no ``INKYPI_AUTH_PIN``),
requests are additionally restricted to local/private networks unless
``INKYPI_ENV=dev`` explicitly opts in. The goal is to avoid leaking system
internals to the open internet on unauthenticated deployments.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from utils.http_utils import json_error

logger = logging.getLogger(__name__)

diagnostics_bp = Blueprint("diagnostics", __name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_TAIL_LINES = 100
_PREV_VERSION_PATH = Path("/var/lib/inkypi/prev_version")
_LAST_UPDATE_FAILURE_PATH = Path("/var/lib/inkypi/.last-update-failure")


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def _is_private_address(addr: str | None) -> bool:
    """Return True when *addr* is a loopback or RFC1918/ULA private address.

    Unknown / unparseable values are treated as non-private (fail closed).
    """
    if not addr:
        return False
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _access_allowed() -> tuple[bool, str | None]:
    """Return (allowed, reason-if-denied).

    When PIN auth is enabled app-wide, the before_request hook has already
    authenticated the caller (or redirected them to /login). In that case we
    trust the gate and allow the request.

    When PIN auth is disabled, we fall back to restricting access to private
    network addresses. ``INKYPI_ENV=dev`` disables this guardrail so local
    development / tests are unimpeded.
    """
    if current_app.config.get("AUTH_ENABLED"):
        return True, None

    env = (os.getenv("INKYPI_ENV") or "").strip().lower()
    if env == "dev":
        return True, None

    if _is_private_address(request.remote_addr):
        return True, None

    return False, "diagnostics endpoint requires authentication or local access"


# ---------------------------------------------------------------------------
# System metrics
# ---------------------------------------------------------------------------


def _uptime_seconds() -> int | None:
    """Return system uptime in seconds via psutil; fall back to /proc/uptime."""
    try:
        import psutil  # type: ignore

        return int(time.time() - psutil.boot_time())
    except Exception:
        pass
    try:
        text = Path("/proc/uptime").read_text()
        return int(float(text.split()[0]))
    except Exception:
        return None


def _memory_info() -> dict[str, Any]:
    """Return {total_mb, used_mb, pct} from psutil, else from /proc/meminfo."""
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        total_mb = int(vm.total / (1024 * 1024))
        used_mb = int((vm.total - vm.available) / (1024 * 1024))
        return {"total_mb": total_mb, "used_mb": used_mb, "pct": float(vm.percent)}
    except Exception:
        pass
    try:
        meminfo: dict[str, int] = {}
        with Path("/proc/meminfo").open() as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                parts = rest.strip().split()
                if parts and parts[0].isdigit():
                    # meminfo values are in kB
                    meminfo[key.strip()] = int(parts[0])
        total_kb = meminfo.get("MemTotal", 0)
        avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        total_mb = int(total_kb / 1024)
        used_mb = int((total_kb - avail_kb) / 1024)
        pct = round(100.0 * (total_kb - avail_kb) / total_kb, 1) if total_kb else 0.0
        return {"total_mb": total_mb, "used_mb": used_mb, "pct": pct}
    except Exception:
        return {"total_mb": None, "used_mb": None, "pct": None}


def _disk_info(path: str = "/") -> dict[str, Any]:
    """Return {total_mb, used_mb, pct, path} for the filesystem containing *path*."""
    try:
        du = shutil.disk_usage(path)
        total_mb = int(du.total / (1024 * 1024))
        used_mb = int(du.used / (1024 * 1024))
        pct = round(100.0 * du.used / du.total, 1) if du.total else 0.0
        return {"total_mb": total_mb, "used_mb": used_mb, "pct": pct, "path": path}
    except Exception:
        return {"total_mb": None, "used_mb": None, "pct": None, "path": path}


# ---------------------------------------------------------------------------
# App / deployment metadata
# ---------------------------------------------------------------------------


def _read_version() -> str:
    """Return the version string from the VERSION file at repo root."""
    try:
        repo_root = Path(__file__).resolve().parent.parent.parent
        value = (repo_root / "VERSION").read_text().strip()
        if value and value != "{version}":
            return value
    except Exception:
        pass
    # Fall back to cached APP_VERSION on the flask app if present
    try:
        cfg_version = current_app.config.get("APP_VERSION")
        if isinstance(cfg_version, str) and cfg_version:
            return cfg_version
    except Exception:
        pass
    return "unknown"


def _read_text_file(path: Path) -> str | None:
    """Return the stripped contents of *path* if readable, else None."""
    try:
        value = path.read_text().strip()
        return value or None
    except Exception:
        return None


def _read_last_update_failure() -> Any | None:
    """Return parsed JSON payload at .last-update-failure, else raw string, else None."""
    raw = _read_text_file(_LAST_UPDATE_FAILURE_PATH)
    if not raw:
        return None
    # Best-effort JSON parse — fall back to raw text
    try:
        import json

        return json.loads(raw)
    except Exception:
        return raw


# ---------------------------------------------------------------------------
# Refresh task / plugin introspection
# ---------------------------------------------------------------------------


def _refresh_task_snapshot() -> dict[str, Any]:
    """Return running/last_run_ts/last_error summary of the refresh task singleton."""
    payload: dict[str, Any] = {
        "running": False,
        "last_run_ts": None,
        "last_error": None,
    }
    try:
        rt = current_app.config.get("REFRESH_TASK")
        if rt is None:
            return payload
        payload["running"] = bool(getattr(rt, "running", False))

        # Best signal for "last_run_ts" we have today is the latest_refresh_time
        # on device_config.refresh_info, which the worker updates on every push.
        dc = current_app.config.get("DEVICE_CONFIG")
        if dc is not None:
            try:
                refresh_info = dc.get_refresh_info()
                latest = getattr(refresh_info, "latest_refresh_time", None)
                if isinstance(latest, str) and latest:
                    payload["last_run_ts"] = latest
            except Exception:
                pass

        # Pull the most recent plugin error, if any, as a coarse "last_error".
        try:
            snapshot = (
                rt.get_health_snapshot() if hasattr(rt, "get_health_snapshot") else {}
            )
        except Exception:
            snapshot = {}
        last_error: str | None = None
        last_failure_at: str | None = None
        if isinstance(snapshot, dict):
            for entry in snapshot.values():
                if not isinstance(entry, dict):
                    continue
                err = entry.get("last_error")
                fat = entry.get("last_failure_at")
                if (
                    err
                    and isinstance(err, str)
                    and (
                        last_failure_at is None
                        or (isinstance(fat, str) and fat > last_failure_at)
                    )
                ):
                    last_error = err
                    if isinstance(fat, str):
                        last_failure_at = fat
        payload["last_error"] = last_error
    except Exception:
        logger.exception("diagnostics: failed to introspect refresh task")
    return payload


def _plugin_health_summary() -> dict[str, str]:
    """Return a {plugin_id: 'ok'|'fail'|'unknown'} map for every registered plugin.

    v1 intentionally returns a flat string per plugin for a stable UI shape.
    Detailed per-plugin metrics remain available on /api/health/plugins.
    """
    summary: dict[str, str] = {}

    # Start with every registered plugin id so the shape is complete even when
    # the refresh task hasn't yet run.
    try:
        from plugins.plugin_registry import get_registered_plugin_ids

        for pid in sorted(get_registered_plugin_ids()):
            summary[pid] = "unknown"
    except Exception:
        logger.exception("diagnostics: failed to list registered plugins")

    # Overlay with the refresh-task health snapshot so we report ok/fail where known.
    try:
        rt = current_app.config.get("REFRESH_TASK")
        if rt is not None and hasattr(rt, "get_health_snapshot"):
            snap = rt.get_health_snapshot() or {}
            if isinstance(snap, dict):
                for pid, entry in snap.items():
                    if not isinstance(entry, dict):
                        continue
                    status = entry.get("status")
                    if status == "green":
                        summary[pid] = "ok"
                    elif status == "red":
                        summary[pid] = "fail"
                    else:
                        summary.setdefault(pid, "unknown")
    except Exception:
        logger.exception("diagnostics: failed to read plugin health snapshot")

    return summary


# ---------------------------------------------------------------------------
# Log tail
# ---------------------------------------------------------------------------


def _log_tail(max_lines: int = _LOG_TAIL_LINES) -> list[str]:
    """Return up to *max_lines* most recent log lines, capped by policy."""
    cap = max(0, min(int(max_lines), _LOG_TAIL_LINES))
    if cap == 0:
        return []
    try:
        # Reuse the existing helper from the settings blueprint. It knows how to
        # pull from journald on Linux and falls back to in-memory buffers in
        # dev mode. 2h of history is ample for a 100-line tail.
        from blueprints import settings as settings_mod

        lines = settings_mod._read_log_lines(hours=2)  # type: ignore[attr-defined]
        if not isinstance(lines, list):
            return []
        if len(lines) > cap:
            lines = lines[-cap:]
        return [str(ln) for ln in lines]
    except Exception:
        logger.exception("diagnostics: failed to read log tail")
        return []


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@diagnostics_bp.route("/api/diagnostics", methods=["GET"])
def api_diagnostics():
    """Return a consolidated system + application diagnostics payload.

    Response shape (stable — downstream UIs consume this):

    .. code-block:: json

      {
        "ts": "2026-04-14T12:34:56+00:00",
        "version": "0.51.8",
        "prev_version": "0.51.7",
        "uptime_s": 12345,
        "memory": {"total_mb": 512, "used_mb": 310, "pct": 60.5},
        "disk": {"total_mb": 16000, "used_mb": 5200, "pct": 32.5, "path": "/"},
        "refresh_task": {"running": true, "last_run_ts": "...", "last_error": null},
        "plugin_health": {"clock": "ok", "weather": "fail"},
        "log_tail_100": ["..."],
        "last_update_failure": null
      }
    """
    allowed, reason = _access_allowed()
    if not allowed:
        return json_error(reason or "forbidden", status=403)

    payload: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "version": _read_version(),
        "prev_version": _read_text_file(_PREV_VERSION_PATH),
        "uptime_s": _uptime_seconds(),
        "memory": _memory_info(),
        "disk": _disk_info("/"),
        "refresh_task": _refresh_task_snapshot(),
        "plugin_health": _plugin_health_summary(),
        "log_tail_100": _log_tail(_LOG_TAIL_LINES),
        "last_update_failure": _read_last_update_failure(),
    }
    return jsonify(payload), 200
