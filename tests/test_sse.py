"""Tests for the SSE event bus and /api/events endpoint."""

from __future__ import annotations

import json
import queue
import threading
import time

import pytest

# ---------------------------------------------------------------------------
# EventBus unit tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def bus():
    from utils.event_bus import EventBus

    return EventBus(max_subscribers=3)


class TestEventBus:
    def test_subscribe_returns_queue(self, bus):
        q = bus.subscribe()
        assert q is not None
        assert isinstance(q, queue.Queue)

    def test_unsubscribe_removes_queue(self, bus):
        q = bus.subscribe()
        assert bus.subscriber_count() == 1
        bus.unsubscribe(q)
        assert bus.subscriber_count() == 0

    def test_publish_delivers_to_subscriber(self, bus):
        q = bus.subscribe()
        bus.publish("refresh_started", {"plugin": "clock", "ts": "2025-01-01T00:00:00"})
        item = q.get_nowait()
        assert item["event"] == "refresh_started"
        assert item["plugin"] == "clock"

    def test_publish_delivers_to_multiple_subscribers(self, bus):
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.publish("refresh_complete", {"plugin": "clock", "duration_ms": 123})
        i1 = q1.get_nowait()
        i2 = q2.get_nowait()
        assert i1["event"] == "refresh_complete"
        assert i2["event"] == "refresh_complete"

    def test_max_subscriber_cap_enforced(self, bus):
        # bus has max_subscribers=3
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        q3 = bus.subscribe()
        q4 = bus.subscribe()  # should be rejected
        assert q1 is not None
        assert q2 is not None
        assert q3 is not None
        assert q4 is None
        assert bus.subscriber_count() == 3

    def test_unsubscribe_nonexistent_is_safe(self, bus):
        q: queue.Queue = queue.Queue()
        bus.unsubscribe(q)  # should not raise

    def test_publish_includes_ts(self, bus):
        q = bus.subscribe()
        before = time.time()
        bus.publish("plugin_failed", {"plugin": "broken", "error": "boom"})
        after = time.time()
        item = q.get_nowait()
        assert before <= item["ts"] <= after

    def test_subscriber_count(self, bus):
        assert bus.subscriber_count() == 0
        q1 = bus.subscribe()
        assert bus.subscriber_count() == 1
        q2 = bus.subscribe()
        assert bus.subscriber_count() == 2
        bus.unsubscribe(q1)
        assert bus.subscriber_count() == 1
        bus.unsubscribe(q2)
        assert bus.subscriber_count() == 0


class TestEventBusStream:
    """Tests for the stream() generator."""

    def test_stream_yields_sse_formatted_event(self, bus):
        q = bus.subscribe()
        bus.publish("refresh_started", {"plugin": "weather"})

        chunks = []
        gen = bus.stream(q, heartbeat_s=0.05)
        chunks.append(next(gen))
        gen.close()

        assert chunks[0].startswith("event: refresh_started\n")
        assert "data:" in chunks[0]
        payload = json.loads(chunks[0].split("data:", 1)[1].strip())
        assert payload["plugin"] == "weather"

    def test_stream_yields_heartbeat_when_idle(self, bus):
        q = bus.subscribe()

        chunks = []

        def _read():
            gen = bus.stream(q, heartbeat_s=0.05)
            chunks.append(next(gen))
            gen.close()

        t = threading.Thread(target=_read)
        t.start()
        t.join(timeout=1.0)
        assert chunks, "No chunk received"
        assert chunks[0] == ": ping\n\n"

    def test_disconnected_subscriber_cleaned_up(self):
        """A full subscriber queue is evicted on next publish."""
        from utils.event_bus import EventBus

        bus = EventBus(max_subscribers=5)
        q = bus.subscribe()
        assert bus.subscriber_count() == 1

        # Fill the queue so the next publish can't put
        for _ in range(q.maxsize):
            q.put_nowait({"event": "filler"})

        bus.publish("refresh_started", {"plugin": "test"})
        # The full queue is evicted and the sentinel sent
        assert bus.subscriber_count() == 0


# ---------------------------------------------------------------------------
# /api/events endpoint tests
# ---------------------------------------------------------------------------


class TestEventsEndpoint:
    def test_get_api_events_returns_200_sse_content_type(self, client, monkeypatch):
        """GET /api/events must return 200 with text/event-stream."""
        from utils.event_bus import get_event_bus

        bus = get_event_bus()
        # Publish an event so the generator yields one item then we stop
        # We test the response headers only (streaming body tested separately)
        called = []

        original_subscribe = bus.subscribe

        def _subscribe_once():
            q = original_subscribe()
            if q is not None:
                # Pre-load an event so the generator doesn't block
                q.put({"event": "refresh_started", "plugin": "test", "ts": 0.0})
                called.append(q)
            return q

        monkeypatch.setattr(bus, "subscribe", _subscribe_once)

        response = client.get("/api/events")
        assert response.status_code == 200
        assert "text/event-stream" in response.content_type
        # Clean up subscriber
        for q in called:
            bus.unsubscribe(q)

    def test_get_api_events_cap_returns_503(self, client, monkeypatch):
        """When subscriber cap is reached, /api/events returns 503."""
        from utils.event_bus import get_event_bus

        bus = get_event_bus()

        monkeypatch.setattr(bus, "subscribe", lambda: None)

        response = client.get("/api/events")
        assert response.status_code == 503

    def test_get_api_events_cache_control_header(self, client, monkeypatch):
        from utils.event_bus import get_event_bus

        bus = get_event_bus()
        original_subscribe = bus.subscribe

        def _subscribe_once():
            q = original_subscribe()
            if q is not None:
                q.put({"event": "refresh_complete", "plugin": "test", "ts": 0.0})
            return q

        monkeypatch.setattr(bus, "subscribe", _subscribe_once)

        response = client.get("/api/events")
        assert response.headers.get("Cache-Control") == "no-cache"

    def test_publish_from_refresh_task_flows_to_subscriber(self, monkeypatch):
        """Publishing via event_bus flows through to the subscriber queue."""
        from utils.event_bus import EventBus

        bus = EventBus()
        q = bus.subscribe()
        assert q is not None
        bus.publish(
            "refresh_started",
            {"plugin": "clock", "plugin_id": "clock", "ts": "2025-01-01T00:00:00"},
        )
        item = q.get_nowait()
        assert item["event"] == "refresh_started"
        assert item["plugin"] == "clock"
        assert item["plugin_id"] == "clock"


# ---------------------------------------------------------------------------
# RefreshTask hook integration
# ---------------------------------------------------------------------------


class TestRefreshTaskHooks:
    """Verify that event_bus.publish is called during a refresh cycle."""

    def _make_task(self, device_config_dev, monkeypatch):
        from display.display_manager import DisplayManager
        from refresh_task.task import RefreshTask

        dm = DisplayManager(device_config_dev)
        task = RefreshTask(device_config_dev, dm)
        return task

    def test_refresh_task_has_event_bus(self, device_config_dev, monkeypatch):
        task = self._make_task(device_config_dev, monkeypatch)
        from utils.event_bus import EventBus

        assert isinstance(task.event_bus, EventBus)

    def test_refresh_started_published(self, device_config_dev, monkeypatch):
        """event_bus.publish called with refresh_started during _perform_refresh."""
        task = self._make_task(device_config_dev, monkeypatch)

        published: list[tuple[str, dict]] = []

        def _capture(event_type, data):
            published.append((event_type, data))

        monkeypatch.setattr(task.event_bus, "publish", _capture)

        # Also stub progress_bus so it doesn't error
        monkeypatch.setattr(task.progress_bus, "publish", lambda _d: None)

        # Provide a minimal plugin config and stub _execute_with_policy to return an image
        from PIL import Image

        img = Image.new("RGB", device_config_dev.get_resolution(), "white")

        monkeypatch.setattr(task, "_execute_with_policy", lambda *a, **kw: (img, {}))
        monkeypatch.setattr(task, "_push_to_display", lambda *a, **kw: (10, 5))
        monkeypatch.setattr(task, "_save_benchmark", lambda *a, **kw: None)
        monkeypatch.setattr(task, "_update_plugin_health", lambda **kw: None)
        monkeypatch.setattr(task, "_stale_display_path", lambda: None)

        # Build a minimal PlaylistRefresh action
        from refresh_task.actions import PlaylistRefresh

        class _FakePlugin:
            plugin_id = "clock"
            name = "My Clock"
            settings = {}

        class _FakePlaylist:
            name = "default"

        action = PlaylistRefresh(_FakePlaylist(), _FakePlugin())

        # Provide a plugin config

        monkeypatch.setattr(
            device_config_dev,
            "get_plugin",
            lambda pid: {"id": pid, "image_settings": []},
        )
        monkeypatch.setattr(
            device_config_dev,
            "get_config",
            lambda key, default=None: [] if key == "isolated_plugins" else default,
        )

        from datetime import UTC, datetime

        task._perform_refresh(
            action, type("R", (), {"image_hash": None})(), datetime.now(UTC)
        )

        event_types = [e[0] for e in published]
        assert "refresh_started" in event_types
        assert "refresh_complete" in event_types

    def test_plugin_failed_published(self, device_config_dev, monkeypatch):
        """event_bus.publish called with plugin_failed when exception raised."""
        task = self._make_task(device_config_dev, monkeypatch)

        published: list[tuple[str, dict]] = []

        def _capture(event_type, data):
            published.append((event_type, data))

        monkeypatch.setattr(task.event_bus, "publish", _capture)
        monkeypatch.setattr(task.progress_bus, "publish", lambda _d: None)
        monkeypatch.setattr(task, "_update_plugin_health", lambda **kw: None)
        monkeypatch.setattr(task, "_stale_display_path", lambda: None)

        def _fail(*a, **kw):
            raise RuntimeError("plugin boom")

        monkeypatch.setattr(task, "_execute_with_policy", _fail)

        from refresh_task.actions import PlaylistRefresh

        class _FakePlugin:
            plugin_id = "broken"
            name = "Broken"
            settings = {}

        class _FakePlaylist:
            name = "default"

        action = PlaylistRefresh(_FakePlaylist(), _FakePlugin())

        monkeypatch.setattr(
            device_config_dev,
            "get_plugin",
            lambda pid: {"id": pid, "image_settings": []},
        )
        monkeypatch.setattr(
            device_config_dev,
            "get_config",
            lambda key, default=None: [] if key == "isolated_plugins" else default,
        )

        from datetime import UTC, datetime

        with pytest.raises(RuntimeError, match="plugin boom"):
            task._perform_refresh(
                action, type("R", (), {"image_hash": None})(), datetime.now(UTC)
            )

        event_types = [e[0] for e in published]
        assert "plugin_failed" in event_types
