"""Health and system monitoring route handlers."""

import logging
import os
import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Response, current_app, request, stream_with_context

import blueprints.settings as _mod
from utils.http_utils import json_error, json_internal_error, json_success
from utils.progress_events import get_progress_bus, to_sse

logger = logging.getLogger(__name__)
_PROGRESS_STREAM_LOCK = threading.Lock()
_PROGRESS_STREAM_ACTIVE = 0


def _progress_stream_limit() -> int:
    try:
        return max(0, int(os.getenv("INKYPI_PROGRESS_SSE_MAX_CONNECTIONS", "4")))
    except Exception:
        return 4


def _reserve_progress_stream() -> bool:
    global _PROGRESS_STREAM_ACTIVE
    with _PROGRESS_STREAM_LOCK:
        if _progress_stream_limit() <= _PROGRESS_STREAM_ACTIVE:
            return False
        _PROGRESS_STREAM_ACTIVE += 1
        return True


def _release_progress_stream() -> None:
    global _PROGRESS_STREAM_ACTIVE
    with _PROGRESS_STREAM_LOCK:
        _PROGRESS_STREAM_ACTIVE = max(0, _PROGRESS_STREAM_ACTIVE - 1)


def _progress_stream_enabled() -> bool:
    return os.getenv("INKYPI_PROGRESS_SSE_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _progress_stream_last_seq() -> int:
    try:
        return int(request.args.get("last_seq", "0"))
    except Exception:
        return 0


def _progress_stream_limit_response() -> Response:
    logger.warning("/api/progress/stream: subscriber cap reached, returning 503")
    return Response(
        "Too many progress SSE connections",
        status=503,
        mimetype="text/plain",
    )


def _iter_progress_events(bus: Any, last_seq: int) -> Generator[str, None, None]:
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


def _filter_health_by_window(health, window_min):
    if not isinstance(health, dict) or window_min <= 0:
        return health
    cutoff = datetime.now(UTC) - timedelta(minutes=window_min)
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
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if dt >= cutoff:
            filtered[plugin_id] = item
    return filtered


@_mod.settings_bp.route("/api/health/plugins", methods=["GET"])
def health_plugins():
    try:
        rt = current_app.config["REFRESH_TASK"]
        health = rt.get_health_snapshot() if hasattr(rt, "get_health_snapshot") else {}
        try:
            window_min = int(os.getenv("INKYPI_HEALTH_WINDOW_MIN", "1440") or "1440")
        except Exception:
            window_min = 1440
        health = _filter_health_by_window(health, window_min)
        return json_success(items=health)
    except Exception as e:
        return json_internal_error("health plugins", details={"error": str(e)})


@_mod.settings_bp.route("/api/health/system", methods=["GET"])
def health_system():
    try:
        data: dict[str, Any] = {}
        try:
            import psutil  # type: ignore

            du = psutil.disk_usage("/")
            vm = psutil.virtual_memory()
            data["cpu_percent"] = psutil.cpu_percent(interval=None)
            data["memory_percent"] = vm.percent
            data["disk_percent"] = du.percent
            data["disk_free_gb"] = round(du.free / (1024**3), 1)
            data["disk_total_gb"] = round(du.total / (1024**3), 1)
            data["uptime_seconds"] = int(time.time() - psutil.boot_time())
        except Exception:
            data["cpu_percent"] = None
            data["memory_percent"] = None
            data["disk_percent"] = None
            data["disk_free_gb"] = None
            data["disk_total_gb"] = None
            data["uptime_seconds"] = None
        return json_success(**data)
    except Exception as e:
        return json_internal_error("health system", details={"error": str(e)})


@_mod.settings_bp.route("/api/progress/stream", methods=["GET"])
def progress_stream():
    if not _progress_stream_enabled():
        return json_error("Progress SSE disabled", status=404)

    bus = get_progress_bus()
    last_seq = _progress_stream_last_seq()

    if not _reserve_progress_stream():
        return _progress_stream_limit_response()

    release_latch = threading.Lock()
    released = False

    def release_once() -> None:
        nonlocal released
        with release_latch:
            if released:
                return
            released = True
        _release_progress_stream()

    @stream_with_context
    def gen() -> Generator[str, None, None]:
        try:
            yield from _iter_progress_events(bus, last_seq)
        finally:
            release_once()

    response = Response(gen(), mimetype="text/event-stream")
    response.call_on_close(release_once)
    return response
