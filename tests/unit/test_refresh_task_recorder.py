from __future__ import annotations

from typing import Any

from refresh_task.recorder import RefreshRecorder


class _ProgressBus:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        self.events.append(event)
        return event


class _EventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


def test_publish_running_emits_progress_and_refresh_started(device_config_dev):
    progress_bus = _ProgressBus()
    event_bus = _EventBus()
    recorder = RefreshRecorder(
        device_config_dev,
        progress_bus=progress_bus,
        event_bus=event_bus,
    )

    recorder.publish_running(
        plugin_id="clock",
        instance="Kitchen Clock",
        refresh_id="refresh-1",
        request_id="request-1",
    )

    assert progress_bus.events == [
        {
            "state": "running",
            "plugin_id": "clock",
            "instance": "Kitchen Clock",
            "refresh_id": "refresh-1",
            "request_id": "request-1",
        }
    ]
    assert event_bus.events[0][0] == "refresh_started"
    assert event_bus.events[0][1]["plugin"] == "Kitchen Clock"
    assert event_bus.events[0][1]["plugin_id"] == "clock"


def test_publish_error_can_emit_plugin_failed(device_config_dev):
    progress_bus = _ProgressBus()
    event_bus = _EventBus()
    recorder = RefreshRecorder(
        device_config_dev,
        progress_bus=progress_bus,
        event_bus=event_bus,
    )

    recorder.publish_error(
        plugin_id="weather",
        instance=None,
        refresh_id="refresh-2",
        request_id=None,
        error="boom",
        retained_display=True,
        plugin_failed=True,
    )

    assert progress_bus.events == [
        {
            "state": "error",
            "plugin_id": "weather",
            "request_id": None,
            "error": "boom",
            "refresh_id": "refresh-2",
            "retained_display": True,
        }
    ]
    assert event_bus.events == [
        (
            "plugin_failed",
            {"plugin": "weather", "plugin_id": "weather", "error": "boom"},
        )
    ]


def test_publish_done_emits_progress_and_refresh_complete(device_config_dev):
    progress_bus = _ProgressBus()
    event_bus = _EventBus()
    recorder = RefreshRecorder(
        device_config_dev,
        progress_bus=progress_bus,
        event_bus=event_bus,
    )
    metrics = {"request_ms": 42}

    recorder.publish_done(
        plugin_id="clock",
        instance=None,
        refresh_id="refresh-3",
        request_id="request-3",
        metrics=metrics,
        duration_ms=42,
    )

    assert progress_bus.events == [
        {
            "state": "done",
            "plugin_id": "clock",
            "instance": None,
            "refresh_id": "refresh-3",
            "request_id": "request-3",
            "metrics": metrics,
        }
    ]
    assert event_bus.events == [
        (
            "refresh_complete",
            {"plugin": "clock", "plugin_id": "clock", "duration_ms": 42},
        )
    ]


def test_save_stage_is_best_effort(device_config_dev, monkeypatch):
    recorder = RefreshRecorder(device_config_dev)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("db locked")

    monkeypatch.setattr("refresh_task.recorder.save_stage_event", fail)

    recorder.save_stage("refresh-4", "generate_image", 12)


def test_save_refresh_builds_benchmark_payload(device_config_dev, monkeypatch):
    recorder = RefreshRecorder(device_config_dev)
    captured: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "refresh_task.recorder.save_refresh_event",
        lambda _config, payload: captured.append(payload),
    )

    recorder.save_refresh(
        refresh_id="refresh-5",
        refresh_info={
            "plugin_id": "clock",
            "plugin_instance": "Clock",
            "playlist": "default",
        },
        used_cached=True,
        metrics={
            "request_ms": 10,
            "generate_ms": 4,
            "preprocess_ms": 2,
            "display_ms": 3,
        },
    )

    assert captured
    expected = {
        "refresh_id": "refresh-5",
        "plugin_id": "clock",
        "instance": "Clock",
        "playlist": "default",
        "used_cached": True,
        "request_ms": 10,
        "generate_ms": 4,
        "preprocess_ms": 2,
        "display_ms": 3,
        "notes": None,
    }
    assert {key: captured[0].get(key) for key in expected} == expected
