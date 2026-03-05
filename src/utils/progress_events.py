from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any


class ProgressEventBus:
    """In-memory pub/sub bus for lightweight progress streaming via SSE."""

    def __init__(self, max_events: int = 500) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._cond = threading.Condition()
        self._seq = 0

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._cond:
            self._seq += 1
            payload = {
                "seq": self._seq,
                "ts": time.time(),
                **event,
            }
            self._events.append(payload)
            self._cond.notify_all()
            return payload

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._cond:
            if limit <= 0:
                return []
            return list(self._events)[-limit:]

    def wait_for(self, last_seq: int, timeout_s: float = 15.0) -> list[dict[str, Any]]:
        with self._cond:
            if self._seq <= last_seq:
                self._cond.wait(timeout=timeout_s)
            return [e for e in self._events if int(e.get("seq", 0)) > last_seq]


def to_sse(event_type: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, separators=(",", ":"))
    return f"event: {event_type}\ndata: {data}\n\n"


_progress_bus = ProgressEventBus()


def get_progress_bus() -> ProgressEventBus:
    return _progress_bus
