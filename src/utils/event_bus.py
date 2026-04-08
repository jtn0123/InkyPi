"""event_bus.py — simple thread-safe pub/sub bus for SSE dashboard updates.

Each subscriber gets its own queue so every connected browser receives every
event independently.  The bus caps the number of concurrent subscribers to
prevent resource exhaustion on a Pi Zero.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Generator
from typing import Any

logger = logging.getLogger(__name__)

_SENTINEL = object()  # placed in a subscriber's queue to signal close


class EventBus:
    """Thread-safe pub/sub bus with per-subscriber queues.

    Attributes:
        max_subscribers: Maximum number of simultaneous subscribers (default 50).
    """

    def __init__(self, max_subscribers: int = 50) -> None:
        self.max_subscribers = max_subscribers
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast *event_type* + *data* to all current subscribers.

        Disconnected (full) queues are silently dropped; the subscriber will be
        cleaned up the next time it tries to read.
        """
        payload = {"event": event_type, "ts": time.time(), **data}
        with self._lock:
            active: list[queue.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(payload)
                    active.append(q)
                except queue.Full:
                    # Subscriber is too slow — drop it
                    logger.debug("EventBus: subscriber queue full, dropping subscriber")
                    try:
                        q.put_nowait(_SENTINEL)
                    except queue.Full:
                        pass
            self._subscribers = active

    def subscribe(self) -> queue.Queue | None:
        """Return a new subscriber queue, or *None* if the cap is reached."""
        with self._lock:
            if len(self._subscribers) >= self.max_subscribers:
                logger.warning(
                    "EventBus: max subscribers (%d) reached, rejecting new subscriber",
                    self.max_subscribers,
                )
                return None
            q: queue.Queue = queue.Queue(maxsize=200)
            self._subscribers.append(q)
            return q

    def unsubscribe(self, q: queue.Queue) -> None:
        """Remove *q* from the subscriber list."""
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def subscriber_count(self) -> int:
        """Return the current number of active subscribers."""
        with self._lock:
            return len(self._subscribers)

    # ------------------------------------------------------------------
    # SSE helpers
    # ------------------------------------------------------------------

    def stream(
        self, q: queue.Queue, heartbeat_s: float = 15.0
    ) -> Generator[str, None, None]:
        """Yield SSE-formatted strings from *q* until the client disconnects.

        A comment heartbeat (`: ping`) is yielded every *heartbeat_s* seconds
        when no event arrives, keeping the connection alive through proxies.

        Usage::

            q = bus.subscribe()
            if q is None:
                abort(503)
            try:
                yield from bus.stream(q)
            finally:
                bus.unsubscribe(q)
        """
        try:
            while True:
                try:
                    item = q.get(timeout=heartbeat_s)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                if item is _SENTINEL:
                    return
                event_type = item.get("event", "message")
                data = json.dumps(item, separators=(",", ":"))
                yield f"event: {event_type}\ndata: {data}\n\n"
        except GeneratorExit:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_event_bus = EventBus()


def get_event_bus() -> EventBus:
    """Return the application-wide EventBus singleton."""
    return _event_bus
