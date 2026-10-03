"""SSE streams must never starve waitress worker threads (bounded count + lifetime)."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from utils import sse
from utils.event_bus import EventBus, get_event_bus
from utils.progress_events import ProgressEventBus, get_progress_bus

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


class TestStreamCap:
    @pytest.mark.parametrize(
        ("threads", "expected"), [("4", 2), ("6", 4), ("3", 1), ("2", 1), ("1", 1)]
    )
    def test_cap_leaves_two_threads_free(
        self, monkeypatch: pytest.MonkeyPatch, threads: str, expected: int
    ) -> None:
        monkeypatch.delenv("INKYPI_SSE_MAX_STREAMS", raising=False)
        monkeypatch.setenv("INKYPI_WEB_THREADS", threads)
        assert sse.max_concurrent_streams() == expected

    def test_default_cap_matches_default_threads(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("INKYPI_SSE_MAX_STREAMS", raising=False)
        monkeypatch.delenv("INKYPI_WEB_THREADS", raising=False)
        assert sse.web_threads() == 4
        assert sse.max_concurrent_streams() == 2

    def test_env_override_and_invalid_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INKYPI_WEB_THREADS", "4")
        monkeypatch.setenv("INKYPI_SSE_MAX_STREAMS", "0")
        assert sse.max_concurrent_streams() == 0
        monkeypatch.setenv("INKYPI_SSE_MAX_STREAMS", "bogus")
        assert sse.max_concurrent_streams() == 2

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(None, 55.0), ("0.5", 0.5), ("0", 55.0), ("-3", 55.0), ("x", 55.0)],
    )
    def test_lifetime_env(
        self, monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: float
    ) -> None:
        if raw is None:
            monkeypatch.delenv("INKYPI_SSE_MAX_LIFETIME_S", raising=False)
        else:
            monkeypatch.setenv("INKYPI_SSE_MAX_LIFETIME_S", raw)
        assert sse.stream_max_lifetime_s() == expected

    def test_newest_stream_evicts_oldest_at_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INKYPI_SSE_MAX_STREAMS", "2")
        slots = sse.StreamSlots()
        first, second = slots.try_acquire(), slots.try_acquire()
        assert first is not None and second is not None
        third = slots.try_acquire()
        assert third is not None
        assert first.evicted() and not second.evicted() and not third.evicted()
        assert slots.active() == 2 and slots.evicting()
        # Only one eviction may wind down at a time: threads stay <= cap + 1.
        assert slots.try_acquire() is None
        slots.release(first)
        assert not slots.evicting()
        fourth = slots.try_acquire()
        assert fourth is not None and second.evicted()
        for lease in (second, third, fourth, fourth):  # Double release is safe.
            slots.release(lease)
        assert slots.active() == 0 and not slots.evicting()

    def test_zero_cap_rejects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INKYPI_SSE_MAX_STREAMS", "0")
        assert sse.StreamSlots().try_acquire() is None

    def test_lease_stop_check_combines_eviction_and_disconnect(self) -> None:
        gone = threading.Event()
        lease = sse.StreamLease()
        check = lease.stop_check({"waitress.client_disconnected": gone.is_set})
        assert check() is False
        gone.set()
        assert check() is True
        other = sse.StreamLease()
        bare = other.stop_check({})
        assert bare() is False
        other.evict()
        assert bare() is True

    def test_slots_are_per_app(self) -> None:
        first, second = Flask("a"), Flask("b")
        assert sse.get_stream_slots(first) is sse.get_stream_slots(first)
        assert sse.get_stream_slots(first) is not sse.get_stream_slots(second)


# ---------------------------------------------------------------------------
# Bounded lifetime at the generator level
# ---------------------------------------------------------------------------


class TestBoundedGenerators:
    def test_event_bus_stream_ends_after_lifetime(self) -> None:
        bus = EventBus()
        q = bus.subscribe()
        assert q is not None
        bus.publish("refresh_started", {"plugin": "clock"})
        started = time.monotonic()
        chunks = list(bus.stream(q, heartbeat_s=0.05, max_lifetime_s=0.3))
        elapsed = time.monotonic() - started
        assert 0.25 <= elapsed < 2.0
        assert chunks[0].startswith("event: refresh_started\n")
        assert ": ping\n\n" in chunks[1:]

    def test_stream_ends_promptly_when_client_disconnects(self) -> None:
        bus = EventBus()
        q = bus.subscribe()
        assert q is not None
        gone = threading.Event()
        threading.Timer(0.2, gone.set).start()
        started = time.monotonic()
        chunks = list(bus.stream(q, heartbeat_s=15.0, should_stop=gone.is_set))
        # Detected by the ~1 s disconnect poll, not the 15 s heartbeat write.
        assert time.monotonic() - started < 2.0
        assert chunks == []

    def test_bounded_stream_heartbeat_accumulates_short_waits(self) -> None:
        waits: list[float] = []

        def wait(timeout_s: float) -> list[str] | None:
            waits.append(timeout_s)
            return [] if len(waits) < 4 else None

        frames = list(
            sse.bounded_stream(
                wait,
                heartbeat=": hb\n\n",
                heartbeat_s=1.0,
                should_stop=lambda: False,
                poll_s=0.5,
            )
        )
        # Two 0.5 s idle polls make one heartbeat window.
        assert waits == [0.5, 0.5, 0.5, 0.5]
        assert frames == [": hb\n\n"]

    def test_socket_probe_detects_peer_close(self) -> None:
        ours, peer = socket.socketpair()
        try:
            probe = sse.disconnect_probe({"werkzeug.socket": ours})
            assert probe is not None
            assert probe() is False
            peer.close()
            assert probe() is True
        finally:
            ours.close()

    def test_waitress_probe_preferred_and_unknown_server_has_none(self) -> None:
        probe = sse.disconnect_probe({"waitress.client_disconnected": lambda: True})
        assert probe is not None and probe() is True
        assert sse.disconnect_probe({}) is None

    def test_progress_iterator_ends_after_lifetime(self) -> None:
        from blueprints.settings import _health

        bus = ProgressEventBus()
        bus.publish({"state": "queued", "plugin_id": "clock"})
        started = time.monotonic()
        chunks = list(_health._iter_progress_events(bus, 0, max_lifetime_s=0.3))
        assert time.monotonic() - started < 2.0
        assert chunks[0].startswith("event: queued\n")
        assert "\nid: 1\n" in chunks[0]


# ---------------------------------------------------------------------------
# Endpoints through the Flask test client
# ---------------------------------------------------------------------------


@pytest.fixture()
def short_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INKYPI_SSE_MAX_LIFETIME_S", "0.3")
    monkeypatch.setenv("INKYPI_PROGRESS_SSE_ENABLED", "true")


@pytest.mark.parametrize("path", ["/api/events", "/api/progress/stream"])
def test_stream_terminates_after_max_lifetime(
    client: FlaskClient, flask_app: Flask, short_streams: None, path: str
) -> None:
    started = time.monotonic()
    response = client.get(path)
    try:
        assert response.status_code == 200
        body = response.get_data(as_text=True)
    finally:
        response.close()
    assert time.monotonic() - started < 3.0
    assert body.startswith(f"retry: {sse.RETRY_MS}\n\n")
    assert response.headers["Cache-Control"] == "no-cache"
    assert sse.get_stream_slots(flask_app).active() == 0


def test_events_stream_releases_subscriber(
    client: FlaskClient, short_streams: None
) -> None:
    bus = get_event_bus()
    before = bus.subscriber_count()
    response = client.get("/api/events")
    response.get_data()
    response.close()
    assert bus.subscriber_count() == before


@pytest.mark.parametrize("path", ["/api/events", "/api/progress/stream"])
def test_stream_cap_returns_503_with_retry_after(
    client: FlaskClient,
    flask_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    monkeypatch.setenv("INKYPI_SSE_MAX_STREAMS", "0")
    monkeypatch.setenv("INKYPI_PROGRESS_SSE_ENABLED", "true")
    before = get_event_bus().subscriber_count()
    response = client.get(path)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == str(sse.RETRY_AFTER_S)
    # A rejected stream holds neither a slot nor a bus subscription.
    assert sse.get_stream_slots(flask_app).active() == 0
    assert get_event_bus().subscriber_count() == before


@pytest.mark.parametrize("path", ["/api/events", "/api/progress/stream"])
def test_returns_503_while_an_eviction_is_winding_down(
    client: FlaskClient,
    flask_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    monkeypatch.setenv("INKYPI_SSE_MAX_STREAMS", "1")
    monkeypatch.setenv("INKYPI_PROGRESS_SSE_ENABLED", "true")
    slots = sse.get_stream_slots(flask_app)
    old, newer = slots.try_acquire(), slots.try_acquire()
    assert old is not None and newer is not None and old.evicted()
    try:
        response = client.get(path)
        assert response.status_code == 503
        assert response.headers["Retry-After"] == str(sse.RETRY_AFTER_S)
        assert not newer.evicted(), "A rejected request must not evict"
    finally:
        slots.release(old)
        slots.release(newer)


def test_event_bus_cap_releases_reserved_slot(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_event_bus(), "subscribe", lambda: None)
    response = client.get("/api/events")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == str(sse.RETRY_AFTER_S)
    assert sse.get_stream_slots(flask_app).active() == 0


def test_progress_stream_resumes_from_last_event_id(
    client: FlaskClient, short_streams: None
) -> None:
    bus = get_progress_bus()
    first = bus.publish({"state": "queued", "plugin_id": "resume-a"})
    second = bus.publish({"state": "running", "plugin_id": "resume-b"})
    response = client.get(
        "/api/progress/stream", headers={"Last-Event-ID": str(first["seq"])}
    )
    body = response.get_data(as_text=True)
    response.close()
    assert '"plugin_id":"resume-a"' not in body
    assert '"plugin_id":"resume-b"' in body
    assert f"\nid: {second['seq']}\n" in body


def test_progress_stream_replays_when_last_event_id_is_from_old_server(
    client: FlaskClient, short_streams: None
) -> None:
    bus = get_progress_bus()
    event = bus.publish({"state": "queued", "plugin_id": "after-restart"})
    response = client.get(
        "/api/progress/stream",
        headers={"Last-Event-ID": str(bus.latest_seq() + 1000)},
    )
    body = response.get_data(as_text=True)
    response.close()
    assert f"\nid: {event['seq']}\n" in body


def test_events_route_registered_once(flask_app: Flask) -> None:
    rules = [r for r in flask_app.url_map.iter_rules() if r.rule == "/api/events"]
    assert len(rules) == 1
    assert rules[0].endpoint == "events.sse_events"
    assert rules[0].methods is not None
    assert {"GET"} <= rules[0].methods
    progress = [
        r for r in flask_app.url_map.iter_rules() if r.rule == "/api/progress/stream"
    ]
    assert len(progress) == 1


# ---------------------------------------------------------------------------
# Real waitress server: open streams must not starve normal requests
# ---------------------------------------------------------------------------


@pytest.fixture()
def waitress_server(
    flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[str, int]]:
    from waitress import create_server

    monkeypatch.setenv("INKYPI_WEB_THREADS", "4")
    monkeypatch.delenv("INKYPI_SSE_MAX_STREAMS", raising=False)
    monkeypatch.setenv("INKYPI_PROGRESS_SSE_ENABLED", "true")
    # Long enough to outlast the assertions, short enough for clean teardown.
    monkeypatch.setenv("INKYPI_SSE_MAX_LIFETIME_S", "5")
    # Mirrors inkypi.main(): lookahead makes client disconnects observable.
    server: Any = create_server(
        flask_app,
        host="127.0.0.1",
        port=0,
        threads=4,
        channel_request_lookahead=1,
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", int(server.effective_port)
    finally:
        # Streams end on their own after the lifetime, freeing every worker.
        server.task_dispatcher.shutdown(timeout=10)

        def close_all() -> None:
            for channel in list(server._map.values()):
                channel.close()

        server.trigger.pull_trigger(close_all)
        thread.join(timeout=5)
        assert not thread.is_alive(), "waitress loop did not stop"


def _open_stream(host: str, port: int, path: str) -> tuple[socket.socket, bytes]:
    """Open a raw SSE request and return the socket plus the response head."""
    sock = socket.create_connection((host, port), timeout=5)
    sock.sendall(
        f"GET {path} HTTP/1.1\r\nHost: {host}\r\nAccept: text/event-stream\r\n\r\n".encode()
    )
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = sock.recv(4096)
        if not chunk:
            break
        head += chunk
    return sock, head


def _read_until_end(sock: socket.socket, timeout_s: float) -> bytes:
    """Read a chunked response body until the server terminates it."""
    sock.settimeout(timeout_s)
    body = b""
    while not body.endswith(b"0\r\n\r\n"):
        chunk = sock.recv(4096)
        if not chunk:
            break
        body += chunk
    return body


def test_normal_requests_stay_responsive_with_streams_at_cap(
    waitress_server: tuple[str, int], flask_app: Flask
) -> None:
    import requests

    host, port = waitress_server
    slots = sse.get_stream_slots(flask_app)
    streams: list[socket.socket] = []
    try:
        for path in ("/api/events", "/api/progress/stream"):
            sock, head = _open_stream(host, port, path)
            streams.append(sock)
            assert head.startswith(b"HTTP/1.1 200"), head
        assert slots.active() == 2

        # Normal requests are served promptly while every stream slot is held.
        started = time.monotonic()
        for _ in range(3):
            response = requests.get(f"http://{host}:{port}/healthz", timeout=2)
            assert response.status_code == 200
        assert time.monotonic() - started < 2.0

        # A newer stream wins: the oldest is ended (not the new one rejected).
        newest, head = _open_stream(host, port, "/api/events")
        streams.append(newest)
        assert head.startswith(b"HTTP/1.1 200"), head
        started = time.monotonic()
        evicted_body = _read_until_end(streams[0], timeout_s=3)
        assert evicted_body.endswith(b"0\r\n\r\n"), evicted_body
        assert time.monotonic() - started < 2.5  # ~1 s stop poll, not the 5 s lifetime.
        assert slots.active() == 2
        response = requests.get(f"http://{host}:{port}/healthz", timeout=2)
        assert response.status_code == 200
    finally:
        for sock in streams:
            sock.close()


@pytest.mark.parametrize("path", ["/api/events", "/api/progress/stream"])
def test_closed_client_frees_slot_before_lifetime(
    waitress_server: tuple[str, int], flask_app: Flask, path: str
) -> None:
    host, port = waitress_server
    sock, head = _open_stream(host, port, path)
    assert head.startswith(b"HTTP/1.1 200"), head
    slots = sse.get_stream_slots(flask_app)
    assert slots.active() == 1
    sock.close()
    deadline = time.monotonic() + 3  # Lifetime is 5 s; the poll is ~1 s.
    while slots.active() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert slots.active() == 0, "Disconnected stream kept its worker thread"


def test_stream_slots_free_after_lifetime_on_real_server(
    waitress_server: tuple[str, int], flask_app: Flask
) -> None:
    host, port = waitress_server
    sock, head = _open_stream(host, port, "/api/events")
    try:
        assert head.startswith(b"HTTP/1.1 200"), head
        body = head + _read_until_end(sock, timeout_s=10)
        # The server ends the chunked response itself once the lifetime expires.
        assert body.endswith(b"0\r\n\r\n"), body
        assert b"retry: 3000" in body
        deadline = time.monotonic() + 3
        while sse.get_stream_slots(flask_app).active() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert sse.get_stream_slots(flask_app).active() == 0
    finally:
        sock.close()
