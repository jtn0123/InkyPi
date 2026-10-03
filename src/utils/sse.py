"""sse.py — shared guard rails for Server-Sent-Event endpoints.

Every open SSE response pins one waitress worker thread for as long as the
stream stays open, so unbounded streams can starve normal requests (a
dashboard tab plus a plugin page used to occupy both default threads and hang
every other request).  The helpers here keep that bounded:

* ``max_concurrent_streams()`` caps open streams across *all* SSE endpoints
  so at least two worker threads stay free for ordinary requests.  At the
  cap the *newest* stream wins: the oldest is told to end (it is usually a
  tab the user just navigated away from, or a background tab that will
  reconnect on its own), so at most one extra thread is briefly in use while
  it winds down.
* ``stream_max_lifetime_s()`` bounds how long one response may hold a thread.
  The server then ends the response and ``EventSource`` reconnects after the
  ``retry:`` hint; this also reclaims threads held by clients that vanished
  without the server noticing.
* ``too_many_streams_response()`` returns 503 + ``Retry-After`` (cap of 0,
  or an eviction already in progress) so clients back off instead of
  hammering the server.
* ``bounded_stream()`` is the shared wait loop: heartbeats, the lifetime
  bound, and a cheap once-per-second stop check (eviction or
  ``disconnect_probe()``) so a navigated-away tab frees its thread within
  ~1 s instead of at the next heartbeat write (up to 15 s later).
"""

from __future__ import annotations

import logging
import os
import select
import socket
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

from flask import Flask, Response, stream_with_context

logger = logging.getLogger(__name__)

DEFAULT_WEB_THREADS = 4
# Worker threads always kept free for non-streaming requests.
RESERVED_WEB_THREADS = 2
DEFAULT_STREAM_MAX_LIFETIME_S = 55.0
# Reconnect delay suggested to EventSource after the server ends a stream.
RETRY_MS = 3000
# Back-off suggested to clients rejected because every stream slot is taken.
RETRY_AFTER_S = 30
# How often an idle stream checks whether it was evicted or its client left.
DISCONNECT_POLL_S = 1.0

_EXTENSION_KEY = "inkypi_sse_stream_slots"


def web_threads() -> int:
    """Return the waitress thread count, env-configurable via INKYPI_WEB_THREADS."""
    raw = os.environ.get("INKYPI_WEB_THREADS")
    if raw is None or raw == "":
        return DEFAULT_WEB_THREADS
    try:
        value = int(raw)
    except (ValueError, TypeError):
        logger.warning(
            "Invalid INKYPI_WEB_THREADS=%r, falling back to default (%d)",
            raw,
            DEFAULT_WEB_THREADS,
        )
        return DEFAULT_WEB_THREADS
    return max(1, value)


def max_concurrent_streams() -> int:
    """Return how many SSE streams may be open at once across all endpoints.

    Defaults to ``web_threads() - 2`` (minimum 1) so two worker threads remain
    for normal requests; INKYPI_SSE_MAX_STREAMS overrides (0 disables SSE and
    clients fall back to polling).
    """
    raw = os.environ.get("INKYPI_SSE_MAX_STREAMS")
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            logger.warning("Invalid INKYPI_SSE_MAX_STREAMS=%r, using default", raw)
    return max(web_threads() - RESERVED_WEB_THREADS, 1)


def stream_max_lifetime_s() -> float:
    """Return the max seconds one SSE response may stay open.

    Env-configurable via INKYPI_SSE_MAX_LIFETIME_S (tests use short values).
    """
    raw = os.environ.get("INKYPI_SSE_MAX_LIFETIME_S")
    if raw:
        try:
            value = float(raw)
        except ValueError:
            logger.warning("Invalid INKYPI_SSE_MAX_LIFETIME_S=%r, using default", raw)
        else:
            if value > 0:
                return value
    return DEFAULT_STREAM_MAX_LIFETIME_S


def retry_hint() -> str:
    """Return the SSE ``retry:`` field telling EventSource when to reconnect."""
    return f"retry: {RETRY_MS}\n\n"


def _socket_closed(sock: socket.socket) -> bool:
    """Return True once the peer has closed *sock* (EOF is readable)."""
    try:
        readable, _, _ = select.select([sock], [], [], 0)
        if not readable:
            return False
        return sock.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):
        return True


def disconnect_probe(environ: dict[str, Any]) -> Callable[[], bool] | None:
    """Return a non-blocking "has the client gone?" check for this request.

    Waitress exposes ``waitress.client_disconnected`` (accurate because
    ``serve()`` enables ``channel_request_lookahead``); Werkzeug's dev server
    exposes the raw socket. Other servers fall back to heartbeat writes.
    """
    probe = environ.get("waitress.client_disconnected")
    if callable(probe):
        return lambda: bool(probe())
    sock = environ.get("werkzeug.socket")
    if isinstance(sock, socket.socket):
        return lambda: _socket_closed(sock)
    return None


def bounded_stream(
    wait: Callable[[float], list[str] | None],
    *,
    heartbeat: str,
    heartbeat_s: float = 15.0,
    max_lifetime_s: float | None = None,
    should_stop: Callable[[], bool] | None = None,
    poll_s: float = DISCONNECT_POLL_S,
) -> Iterator[str]:
    """Yield frames from *wait* until the lifetime ends or *should_stop*.

    ``wait(timeout_s)`` blocks up to *timeout_s* and returns the frames to
    send (empty when idle) or ``None`` when the source itself closed.
    *heartbeat* is yielded after *heartbeat_s* of accumulated idle waiting.
    """
    deadline = time.monotonic() + max_lifetime_s if max_lifetime_s is not None else None
    idle_s = 0.0
    while True:
        timeout_s = heartbeat_s - idle_s
        if should_stop is not None:
            timeout_s = min(timeout_s, poll_s)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            timeout_s = min(timeout_s, remaining)
        frames = wait(timeout_s)
        if frames is None:
            return
        if should_stop is not None and should_stop():
            return
        if frames:
            idle_s = 0.0
            yield from frames
            continue
        idle_s += timeout_s
        if idle_s >= heartbeat_s * 0.999:  # Tolerate float accumulation.
            idle_s = 0.0
            yield heartbeat


class StreamLease:
    """One open stream's claim on a slot; evicted when a newer stream needs it."""

    def __init__(self) -> None:
        self._evicted = threading.Event()

    def evict(self) -> None:
        self._evicted.set()

    def evicted(self) -> bool:
        return self._evicted.is_set()

    def stop_check(self, environ: dict[str, Any]) -> Callable[[], bool]:
        """Return the stream's stop condition: evicted or client gone."""
        probe = disconnect_probe(environ)
        if probe is None:
            return self.evicted
        return lambda: self.evicted() or probe()


class StreamSlots:
    """Thread-safe registry of open SSE streams shared by every SSE endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: list[StreamLease] = []  # Oldest first.
        self._evicting: StreamLease | None = None

    def try_acquire(self) -> StreamLease | None:
        """Return a lease, evicting the oldest stream when at the cap.

        Returns None (caller answers 503) when streams are disabled or a
        previous eviction is still winding down, which bounds stream threads
        at ``cap + 1``.
        """
        with self._lock:
            cap = max_concurrent_streams()
            if cap <= 0:
                return None
            if len(self._leases) >= cap:
                if self._evicting is not None:
                    return None
                oldest = self._leases.pop(0)
                oldest.evict()
                self._evicting = oldest
            lease = StreamLease()
            self._leases.append(lease)
            return lease

    def release(self, lease: StreamLease) -> None:
        with self._lock:
            if lease in self._leases:
                self._leases.remove(lease)
            if self._evicting is lease:
                self._evicting = None

    def active(self) -> int:
        """Return the number of streams holding a slot (excludes evictions)."""
        with self._lock:
            return len(self._leases)

    def evicting(self) -> bool:
        with self._lock:
            return self._evicting is not None


def get_stream_slots(app: Flask) -> StreamSlots:
    """Return the per-app stream slot counter (one app per process in prod)."""
    slots = app.extensions.get(_EXTENSION_KEY)
    if not isinstance(slots, StreamSlots):
        slots = StreamSlots()
        app.extensions[_EXTENSION_KEY] = slots
    return slots


def too_many_streams_response(endpoint: str, message: str) -> Response:
    """Return the 503 sent when no stream slot (or subscriber) is available."""
    logger.warning("%s: stream cap reached, returning 503", endpoint)
    response = Response(message, status=503, mimetype="text/plain")
    response.headers["Retry-After"] = str(RETRY_AFTER_S)
    return response


def sse_response(
    stream: Iterator[str], *, on_close: Callable[[], None] | None = None
) -> Response:
    """Wrap *stream* in a non-cached ``text/event-stream`` response.

    ``on_close`` runs exactly once when the stream finishes, the client goes
    away, or the server closes the response — whichever happens first.
    """
    release_latch = threading.Lock()
    released = False

    def close_once() -> None:
        nonlocal released
        if on_close is None:
            return
        with release_latch:
            if released:
                return
            released = True
        on_close()

    def generate() -> Iterator[str]:
        try:
            yield retry_hint()
            yield from stream
        finally:
            close_once()

    # `stream_with_context` is applied to the iterator rather than used as a
    # decorator. Both work, but the decorator form returns a callable at
    # runtime while its type stub declares an Iterator.
    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.call_on_close(close_once)
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # Disable nginx buffering
    return response
