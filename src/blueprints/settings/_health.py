"""Health and system monitoring route handlers."""

import logging
import os
import threading
import time
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Response, current_app, request

import blueprints.settings as _mod
from utils.http_utils import json_error, json_internal_error, json_success
from utils.progress_events import get_progress_bus, to_sse
from utils.sse import (
    bounded_stream,
    get_stream_slots,
    sse_response,
    stream_max_lifetime_s,
    too_many_streams_response,
)

logger = logging.getLogger(__name__)
_PROGRESS_STREAM_LOCK = threading.Lock()
_PROGRESS_STREAM_ACTIVE = 0
_PROGRESS_TOO_MANY = "Too many progress SSE connections"


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


def _progress_stream_last_seq(latest_seq: int) -> int:
    """Return the last sequence the client has seen.

    EventSource reconnects send ``Last-Event-ID`` (the ``id:`` of the final
    event received); explicit ``?last_seq=`` is honoured for first connects.
    An id newer than the bus has ever produced means the server restarted, so
    the client is replayed from the beginning instead of silently stalling.
    """
    raw = request.headers.get("Last-Event-ID") or request.args.get("last_seq", "0")
    try:
        last_seq = int(raw)
    except Exception:
        return 0
    if last_seq > latest_seq:
        return 0
    return max(0, last_seq)


def _iter_progress_events(
    bus: Any,
    last_seq: int,
    max_lifetime_s: float | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Generator[str, None, None]:
    for ev in bus.recent(limit=100):
        seq = int(ev.get("seq", 0))
        if seq > last_seq:
            yield to_sse(str(ev.get("state", "event")), ev, event_id=seq)
    local_seq = last_seq

    def wait(timeout_s: float) -> list[str]:
        nonlocal local_seq
        frames: list[str] = []
        for ev in bus.wait_for(local_seq, timeout_s=timeout_s):
            seq = int(ev.get("seq", 0))
            local_seq = max(local_seq, seq)
            frames.append(to_sse(str(ev.get("state", "event")), ev, event_id=seq))
        return frames

    yield from bounded_stream(
        wait,
        heartbeat=": keep-alive\n\n",
        max_lifetime_s=max_lifetime_s,
        should_stop=should_stop,
    )


def _filter_health_by_window(health: dict[str, Any], window_min: int) -> dict[str, Any]:
    if not isinstance(health, dict) or window_min <= 0:
        return health
    cutoff = datetime.now(UTC) - timedelta(minutes=window_min)
    filtered: dict[str, Any] = {}
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
def health_plugins() -> tuple[Any, int] | Response:
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
def health_system() -> tuple[Any, int] | Response:
    try:
        data: dict[str, Any] = {}
        try:
            import psutil

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
def progress_stream() -> Response | tuple[Any, int]:
    if not _progress_stream_enabled():
        return json_error("Progress SSE disabled", status=404)

    bus = get_progress_bus()
    last_seq = _progress_stream_last_seq(bus.latest_seq())

    if not _reserve_progress_stream():
        return too_many_streams_response("/api/progress/stream", _PROGRESS_TOO_MANY)
    slots = get_stream_slots(current_app)
    lease = slots.try_acquire()
    if lease is None:
        _release_progress_stream()
        return too_many_streams_response("/api/progress/stream", _PROGRESS_TOO_MANY)

    def close() -> None:
        _release_progress_stream()
        slots.release(lease)

    return sse_response(
        _iter_progress_events(
            bus,
            last_seq,
            max_lifetime_s=stream_max_lifetime_s(),
            should_stop=lease.stop_check(request.environ),
        ),
        on_close=close,
    )
