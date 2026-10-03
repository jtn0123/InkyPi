"""Disposable HTTP servers must release only the stream resources they own."""

import contextlib
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from flask import Flask, Response

from tests.conftest import live_server


def _connect(url: str, path: str = "/api/progress/stream") -> socket.socket:
    host, port = url.removeprefix("http://").split(":")
    sock = socket.create_connection((host, int(port)), timeout=3)
    sock.sendall(f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())
    body = b""
    while b"event: probe" not in body:
        chunk = sock.recv(4096)
        assert chunk, "Stream ended before its first event"
        body += chunk
    return sock


@contextlib.contextmanager
def _server(app: Flask, ports: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    fixture_factory = live_server._get_wrapped_function()
    fixture = fixture_factory(app, ports, monkeypatch)
    try:
        yield next(fixture)
    finally:
        fixture.close()


def test_server_teardown_releases_only_owned_streams(
    free_tcp_port_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from blueprints import events
    from blueprints.settings import _health
    from utils import event_bus as event_module, progress_events as progress_module
    from utils.event_bus import EventBus
    from utils.progress_events import ProgressEventBus

    bus = ProgressEventBus()
    bus.publish({"state": "probe"})
    monkeypatch.setattr(progress_module, "_progress_bus", bus)
    event_bus = EventBus()
    monkeypatch.setattr(event_module, "_event_bus", event_bus)
    monkeypatch.delenv("INKYPI_PROGRESS_SSE_MAX_CONNECTIONS", raising=False)
    # Each app opens three streams; ownership, not the shared cap, is under test.
    monkeypatch.setenv("INKYPI_SSE_MAX_STREAMS", "8")
    workers: dict[str, list[threading.Thread]] = {"first": [], "second": []}

    def app(name: str) -> Flask:
        application = Flask(name)

        @application.get("/api/progress/stream")
        def stream() -> Any:
            workers.setdefault(name, []).append(threading.current_thread())
            return _health.progress_stream()

        @application.get("/api/events")
        def event_stream() -> Any:
            workers.setdefault(name, []).append(threading.current_thread())
            response = events.sse_events()
            event_bus.publish("probe", {})
            return response

        return application

    def active() -> int:
        with _health._PROGRESS_STREAM_LOCK:
            return _health._PROGRESS_STREAM_ACTIVE

    first = _server(app("first"), free_tcp_port_factory, monkeypatch)
    second = _server(app("second"), free_tcp_port_factory, monkeypatch)
    sockets: list[socket.socket] = []
    try:
        first_url, second_url = first.__enter__(), second.__enter__()
        sockets.extend(_connect(first_url) for _ in range(2))
        sockets.extend(_connect(second_url) for _ in range(2))
        sockets.append(_connect(first_url, "/api/events"))
        sockets.append(_connect(second_url, "/api/events"))
        assert active() == 4
        assert event_bus.subscriber_count() == 2
        first.__exit__(None, None, None)
        assert all(not thread.is_alive() for thread in workers["first"])
        assert active() == 2, "Disposed app must release its own two leases"
        assert event_bus.subscriber_count() == 1
        assert all(thread.is_alive() for thread in workers["second"])
        # A teardown heartbeat may wake the other stream; it must remain open.
        with _server(app("fresh"), free_tcp_port_factory, monkeypatch) as url:
            sockets.append(_connect(url))
            assert active() == 3
        assert active() == 2
        second.__exit__(None, None, None)
        assert all(not thread.is_alive() for thread in workers["second"])
        assert active() == 0
        assert event_bus.subscriber_count() == 0
    finally:
        first.__exit__(None, None, None)
        second.__exit__(None, None, None)
        for sock in sockets:
            sock.close()
        # Bounded cleanup also makes a failing baseline reproduction disposable.
        deadline = time.monotonic() + 3
        while any(thread.is_alive() for group in workers.values() for thread in group):
            with bus._cond:
                bus._cond.notify_all()
            if time.monotonic() >= deadline:
                pytest.fail("Probe cleanup left owned workers alive")
            time.sleep(0.01)


@pytest.mark.parametrize("started", [False, True])
def test_progress_response_close_is_idempotent_before_and_after_iteration(
    started: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from blueprints.settings import _health
    from utils.progress_events import ProgressEventBus

    bus = ProgressEventBus()
    bus.publish({"state": "probe"})
    monkeypatch.setattr(_health, "get_progress_bus", lambda: bus)
    app = Flask("response-owner")
    initial = _health._PROGRESS_STREAM_ACTIVE
    with app.test_request_context("/api/progress/stream"):
        response = _health.progress_stream()
    assert isinstance(response, Response)
    try:
        assert response.status_code == 200
        current = _health._PROGRESS_STREAM_ACTIVE
        assert current == initial + 1
        if started:
            chunks = iter(response.response)
            assert next(chunks) == "retry: 3000\n\n"
            chunk = next(chunks)
            assert isinstance(chunk, str)
            assert chunk.startswith("event: probe")
    finally:
        response.close()
        response.close()
    final = _health._PROGRESS_STREAM_ACTIVE
    assert final == initial


def test_teardown_wakes_subscription_created_after_drain_begins(
    free_tcp_port_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from blueprints import events
    from utils import event_bus as event_module, progress_events as progress_module
    from utils.event_bus import EventBus
    from utils.progress_events import ProgressEventBus

    bus = ProgressEventBus()
    event_bus = EventBus()
    monkeypatch.setattr(progress_module, "_progress_bus", bus)
    monkeypatch.setattr(event_module, "_event_bus", event_bus)
    entered = threading.Event()
    subscribe_after_snapshot = threading.Event()
    original_notify = bus._cond.notify_all

    def notify() -> None:
        # The first worker-drain wake occurs after the old one-time snapshot.
        subscribe_after_snapshot.set()
        original_notify()

    monkeypatch.setattr(bus._cond, "notify_all", notify)
    app = Flask("late-owned-subscriber")
    workers: list[threading.Thread] = []

    @app.get("/api/events")
    def stream() -> Response:
        workers.append(threading.current_thread())
        entered.set()
        assert subscribe_after_snapshot.wait(2), "Teardown did not begin"
        return events.sse_events()

    server = _server(app, free_tcp_port_factory, monkeypatch)
    sock: socket.socket | None = None
    try:
        url = server.__enter__()
        host, port = url.removeprefix("http://").split(":")
        sock = socket.create_connection((host, int(port)), timeout=3)
        sock.sendall(b"GET /api/events HTTP/1.0\r\nHost: localhost\r\n\r\n")
        assert entered.wait(1), "Owned handler was not dispatched"
        server.__exit__(None, None, None)
        assert event_bus.subscriber_count() == 0
        assert all(not worker.is_alive() for worker in workers)
    finally:
        subscribe_after_snapshot.set()
        server.__exit__(None, None, None)
        if sock is not None:
            sock.close()


def test_failed_worker_start_removes_resource_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.live_server import OwnedTestServer
    from utils.progress_events import ProgressEventBus

    server = OwnedTestServer(
        "127.0.0.1", 0, Flask("failed-dispatch"), progress_bus=ProgressEventBus()
    )
    transport, peer = socket.socketpair()

    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError("Injected dispatch failure")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    try:
        with pytest.raises(RuntimeError, match="Injected dispatch failure"):
            server.process_request(transport, ("127.0.0.1", 12345))
        assert server.workers == {}
        assert server.request_threads == []
    finally:
        transport.close()
        peer.close()
        server.server_close()


def test_context_close_failure_still_drains_workers_and_other_contexts(
    free_tcp_port_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from blueprints.settings import _health
    from tests.fixtures.live_server import register_browser_context
    from utils import progress_events as progress_module
    from utils.progress_events import ProgressEventBus

    bus = ProgressEventBus()
    bus.publish({"state": "probe"})
    monkeypatch.setattr(progress_module, "_progress_bus", bus)
    app = Flask("context-close-failure")
    app.add_url_rule("/api/progress/stream", view_func=_health.progress_stream)
    closed: list[str] = []

    class FailingContext:
        def close(self) -> None:
            closed.append("failed")
            raise RuntimeError("Injected context close failure")

    class OtherContext:
        def close(self) -> None:
            closed.append("other")

    register_browser_context(app, FailingContext())
    register_browser_context(app, OtherContext())
    server = _server(app, free_tcp_port_factory, monkeypatch)
    initial = _health._PROGRESS_STREAM_ACTIVE
    sock: socket.socket | None = None
    try:
        sock = _connect(server.__enter__())
        with pytest.raises(ExceptionGroup, match="Test browser context cleanup failed"):
            server.__exit__(None, None, None)
        assert closed == ["failed", "other"]
        final = _health._PROGRESS_STREAM_ACTIVE
        assert final == initial
    finally:
        server.__exit__(None, None, None)
        if sock is not None:
            sock.close()
