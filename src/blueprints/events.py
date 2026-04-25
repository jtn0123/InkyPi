"""events.py — SSE endpoint for live dashboard updates.

GET /api/events streams refresh lifecycle events (refresh_started,
refresh_complete, plugin_failed) published by the refresh task.  The
endpoint falls back gracefully: if the subscriber cap is reached it
returns HTTP 503 so the client can fall back to polling.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, stream_with_context

from utils.event_bus import get_event_bus

logger = logging.getLogger(__name__)

events_bp = Blueprint("events", __name__)


@events_bp.route("/api/events", methods=["GET"])  # type: ignore
@events_bp.route("/api/events", methods=["GET"])  # type: ignore
def sse_events() -> Response:
    """Stream SSE events to the client.

    Yields ``event: <type>`` / ``data: <json>`` pairs for each refresh
    lifecycle event.  A ``: ping`` heartbeat comment is sent every 15 s
    when no event arrives so the connection stays alive through proxies.

    If the maximum subscriber count is reached the endpoint returns 503
    so the caller can fall back to polling.
    """
    bus = get_event_bus()
    q = bus.subscribe()
    if q is None:
        logger.warning("/api/events: subscriber cap reached, returning 503")
        return Response("Too many SSE connections", status=503, mimetype="text/plain")

    @stream_with_context  # type: ignore
    def generate() -> Any:
        try:
            yield from bus.stream(q)
        finally:
            bus.unsubscribe(q)

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # Disable nginx buffering
    return response
