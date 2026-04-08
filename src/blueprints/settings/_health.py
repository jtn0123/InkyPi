"""Health and system monitoring route handlers."""

import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Response, current_app, jsonify, request, stream_with_context

import blueprints.settings as _mod
from utils.http_utils import json_error, json_internal_error
from utils.progress_events import get_progress_bus, to_sse


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
        return jsonify({"success": True, "items": health})
    except Exception as e:
        return json_internal_error("health plugins", details={"error": str(e)})


@_mod.settings_bp.route("/api/health/system", methods=["GET"])
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


@_mod.settings_bp.route("/api/progress/stream", methods=["GET"])
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
