from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

from refresh_task.actions import ManualRefresh, ManualUpdateRequest
from refresh_task.health import PluginHealthTracker
from refresh_task.housekeeping import RefreshHousekeeper
from refresh_task.scheduler import RefreshScheduler


class _FakeSchedulerConfig:
    def __init__(self) -> None:
        self.playlist_manager = object()
        self.refresh_info = object()

    def get_config(self, key: str, default: object = None) -> object:
        if key == "plugin_cycle_interval_seconds":
            return 42
        return default

    def get_playlist_manager(self) -> object:
        return self.playlist_manager

    def get_refresh_info(self) -> object:
        return self.refresh_info


class _StaticRefreshAction:
    def __init__(self, refresh_info: dict[str, str | None]) -> None:
        self._refresh_info = refresh_info

    def get_refresh_info(self) -> dict[str, str | None]:
        return dict(self._refresh_info)


def test_refresh_scheduler_wait_for_trigger_returns_manual_request() -> None:
    config = _FakeSchedulerConfig()
    condition = threading.Condition()
    current_dt = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    manual_request = ManualUpdateRequest("req-1", ManualRefresh("demo", {}))
    manual_update_requests = deque([manual_request], maxlen=50)

    scheduler = RefreshScheduler(
        device_config=config,
        condition=condition,
        manual_update_requests=manual_update_requests,
        get_current_datetime=lambda: current_dt,
    )

    result = scheduler.wait_for_trigger(is_running=lambda: True)

    assert result == (
        config.playlist_manager,
        config.refresh_info,
        current_dt,
        manual_request,
    )
    assert not manual_update_requests


def test_refresh_housekeeper_build_history_meta_prefers_explicit_instance() -> None:
    history_meta = RefreshHousekeeper.build_history_meta(
        _StaticRefreshAction(
            {
                "refresh_type": "Playlist",
                "plugin_id": "weather",
                "playlist": "Default",
                "plugin_instance": "morning",
            }
        ),
        instance_name="override",
    )

    assert history_meta == {
        "refresh_type": "Playlist",
        "plugin_id": "weather",
        "playlist": "Default",
        "plugin_instance": "override",
    }


def test_plugin_health_tracker_update_populates_state_before_failure_hook(
    device_config_dev: Any,
) -> None:
    tracker = PluginHealthTracker(device_config_dev, {})
    observed: dict[str, object] = {}

    def on_failure(_plugin_instance: Any, plugin_id: str, instance: str | None) -> None:
        observed["plugin_id"] = plugin_id
        observed["instance"] = instance
        observed["last_error"] = tracker.plugin_health[plugin_id]["last_error"]

    tracker.update(
        plugin_id="weather",
        instance=None,
        ok=False,
        metrics={"retained_display": True},
        error="boom",
        on_success=lambda *_args: None,
        on_failure=on_failure,
    )

    assert observed == {
        "plugin_id": "weather",
        "instance": None,
        "last_error": "boom",
    }
