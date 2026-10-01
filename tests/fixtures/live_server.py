"""Own and drain disposable test-server resources without changing runtime SSE."""

import queue
import socket
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol, cast
from weakref import WeakSet

import pytest
from flask import Flask
from werkzeug.serving import ThreadedWSGIServer

from utils.event_bus import _SENTINEL, EventBus
from utils.progress_events import ProgressEventBus

_BROWSER_CONTEXTS = "_TEST_OWNED_BROWSER_CONTEXTS"
_LOCK = threading.Lock()
_StreamQueue = queue.Queue[dict[str, Any] | object]
_TRACKED_SUBSCRIPTIONS: WeakSet[Callable[[], _StreamQueue | None]] = WeakSet()
_REQUEST_OWNERS: dict[threading.Thread, "OwnedTestServer"] = {}


class BrowserContextOwner(Protocol):
    def close(self) -> None: ...


def register_browser_context(app: Flask, context: BrowserContextOwner) -> None:
    contexts = cast(
        list[BrowserContextOwner], app.config.setdefault(_BROWSER_CONTEXTS, [])
    )
    contexts.append(context)


def unregister_browser_context(app: Flask, context: BrowserContextOwner) -> None:
    contexts = cast(list[BrowserContextOwner], app.config.get(_BROWSER_CONTEXTS, []))
    if context in contexts:
        contexts.remove(context)


def track_event_subscriptions(bus: EventBus, monkeypatch: pytest.MonkeyPatch) -> None:
    original = bus.subscribe
    if original in _TRACKED_SUBSCRIPTIONS:
        return

    def subscribe() -> _StreamQueue | None:
        subscriber = original()
        with _LOCK:
            owner = _REQUEST_OWNERS.get(threading.current_thread())
            if owner is not None and subscriber is not None:
                owner.subscribers.append(subscriber)
        return subscriber

    _TRACKED_SUBSCRIPTIONS.add(subscribe)
    monkeypatch.setattr(bus, "subscribe", subscribe)


class OwnedTestServer(ThreadedWSGIServer):
    """Keep ownership even though Werkzeug excludes daemon workers from join."""

    def __init__(
        self, host: str, port: int, app: Flask, *, progress_bus: ProgressEventBus
    ) -> None:
        super().__init__(host, port, app)
        self.progress_bus = progress_bus
        self.workers: dict[threading.Thread, socket.socket] = {}
        self.request_threads: list[threading.Thread] = []
        self.subscribers: list[_StreamQueue] = []

    def process_request(
        self,
        request: socket.socket | tuple[bytes, socket.socket],
        client_address: tuple[str, int],
    ) -> None:
        if not isinstance(request, socket.socket):
            raise TypeError("HTTP test servers require stream sockets")
        worker = threading.Thread(
            target=self.process_request_thread,
            args=(request, client_address),
            daemon=True,
        )
        # Register before start so shutdown cannot miss a dispatched worker.
        with _LOCK:
            self.workers[worker] = request
            self.request_threads.append(worker)
            _REQUEST_OWNERS[worker] = self
        try:
            worker.start()
        except BaseException:
            with _LOCK:
                self.workers.pop(worker, None)
                self.request_threads.remove(worker)
                _REQUEST_OWNERS.pop(worker, None)
            raise

    def process_request_thread(
        self,
        request: socket.socket | tuple[bytes, socket.socket],
        client_address: tuple[str, int],
    ) -> None:
        worker = threading.current_thread()
        try:
            super().process_request_thread(request, client_address)
        finally:
            with _LOCK:
                self.workers.pop(worker, None)
                _REQUEST_OWNERS.pop(worker, None)

    def close_owned_resources(self, app: Flask, timeout: float = 5) -> None:
        context_errors: list[Exception] = []
        try:
            # Only contexts registered by this test's page fixtures are closed.
            contexts = cast(
                list[BrowserContextOwner], app.config.pop(_BROWSER_CONTEXTS, [])
            )
            for context in contexts:
                try:
                    context.close()
                except Exception as error:
                    context_errors.append(error)
        finally:
            self.shutdown()
            # The budget bounds worker drain, not synchronous context/API close.
            deadline = time.monotonic() + timeout
            with _LOCK:
                sockets = list(self.workers.values())
            # Shutdown (not close) keeps descriptors valid for WSGI finally/close.
            for transport in sockets:
                try:
                    transport.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # Already disconnected by its owner.
            closed_subscribers: set[_StreamQueue] = set()
            try:
                while True:
                    with _LOCK:
                        workers = [
                            worker
                            for worker in self.request_threads
                            if worker.is_alive()
                        ]
                        subscribers = [
                            subscriber
                            for subscriber in self.subscribers
                            if subscriber not in closed_subscribers
                        ]
                    for subscriber in subscribers:
                        try:
                            subscriber.put_nowait(_SENTINEL)
                        except queue.Full:
                            pass  # Queued data already wakes the closed transport.
                        closed_subscribers.add(subscriber)
                    if not workers:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError(
                            "Test server teardown left owned request workers alive: "
                            + ", ".join(worker.name for worker in workers)
                        )
                    # Wake waits with an empty heartbeat, never a fake job event.
                    # A different server may wake too; its transport stays open.
                    with self.progress_bus._cond:
                        self.progress_bus._cond.notify_all()
                    # One shared deadline, not a fresh timeout per worker.
                    for worker in workers:
                        worker.join(max(0, min(0.01, deadline - time.monotonic())))
            finally:
                self.server_close()
        if context_errors:
            raise ExceptionGroup("Test browser context cleanup failed", context_errors)
