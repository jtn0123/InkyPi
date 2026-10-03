"""events.py — SSE endpoint for live dashboard updates.

GET /api/events streams refresh lifecycle events (refresh_started,
refresh_complete, plugin_failed) published by the refresh task.  Each
response is bounded to ``stream_max_lifetime_s()`` so it cannot pin a
waitress worker indefinitely; the client reconnects automatically and
reconciles on open.  At the shared stream cap the oldest stream is evicted
(see ``utils.sse``); if that is not possible, or the bus subscriber cap is
reached, the endpoint returns HTTP 503 with ``Retry-After`` so the client can
fall back to polling.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from flask import Blueprint, Response, current_app, request

from utils.event_bus import get_event_bus
from utils.sse import (
    get_stream_slots,
    sse_response,
    stream_max_lifetime_s,
    too_many_streams_response,
)

logger = logging.getLogger(__name__)

events_bp = Blueprint("events", __name__)

_TOO_MANY = "Too many SSE connections"


@events_bp.route("/api/events", methods=["GET"])
def sse_events() -> Response:
    """Stream SSE events to the client.

    Yields ``event: <type>`` / ``data: <json>`` pairs for each refresh
    lifecycle event.  A ``: ping`` heartbeat comment is sent every 15 s
    when no event arrives so the connection stays alive through proxies.
    The bus keeps no replay buffer, so clients re-fetch state when the
    stream (re)opens rather than relying on ``Last-Event-ID``.
    """
    slots = get_stream_slots(current_app)
    lease = slots.try_acquire()
    if lease is None:
        return too_many_streams_response("/api/events", _TOO_MANY)

    bus = get_event_bus()
    q = bus.subscribe()
    if q is None:
        slots.release(lease)
        return too_many_streams_response("/api/events", _TOO_MANY)

    def close() -> None:
        bus.unsubscribe(q)
        slots.release(lease)

    lifetime_s = stream_max_lifetime_s()
    should_stop = lease.stop_check(request.environ)

    def generate() -> Iterator[str]:
        yield from bus.stream(q, max_lifetime_s=lifetime_s, should_stop=should_stop)

    return sse_response(generate(), on_close=close)
