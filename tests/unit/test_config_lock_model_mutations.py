# pyright: reportMissingImports=false
"""Model mutations from other threads must survive an update_atomic rollback.

``Config.update_atomic`` snapshots the model objects, runs the callback and
restores the snapshot if the callback or the write fails. A thread that
mutates the same objects *without* the config lock can land inside that
window, and the rollback then silently restores the old value — e.g. the
refresh thread's circuit-breaker counter, lost because a web request's
settings save failed at the same moment.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from typing import Any

import pytest

from model import PluginInstance, RefreshInfo
from refresh_task.health import PluginHealthTracker

_PLUGIN_ID = "race_plugin"
_INSTANCE = "race_inst"


def _add_instance(device_config: Any) -> PluginInstance:
    instance = PluginInstance(
        plugin_id=_PLUGIN_ID,
        name=_INSTANCE,
        settings={},
        refresh={"interval": 3600},
    )
    pm = device_config.get_playlist_manager()
    playlist = pm.get_playlist("Default")
    if playlist is None:
        pm.add_default_playlist()
        playlist = pm.get_playlist("Default")
    playlist.plugins.append(instance)
    device_config.write_config()
    return instance


def _persisted_instance(device_config: Any) -> dict[str, Any]:
    with open(device_config.config_file, encoding="utf-8") as fh:
        data = json.load(fh)
    for playlist in data["playlist_config"]["playlists"]:
        for plugin in playlist["plugins"]:
            if plugin["plugin_id"] == _PLUGIN_ID:
                return dict(plugin)
    raise AssertionError("plugin instance missing from persisted config")


def _race_with_failed_update(
    device_config: Any, mutated: Any, mutate_in_other_thread: Any
) -> None:
    """Run *mutate_in_other_thread* while a failing update_atomic is in flight.

    The update callback waits — bounded — for the other thread's change to
    appear before raising. Without the lock the change appears inside the
    window and is rolled back; with it the other thread blocks until the
    rollback is done, the wait simply times out, and the change applies after.
    """
    started = threading.Event()
    errors: list[BaseException] = []

    def _failing_update(_config: dict[str, Any]) -> None:
        started.set()
        deadline = time.monotonic() + 0.5
        while not mutated() and time.monotonic() < deadline:
            time.sleep(0.005)
        raise RuntimeError("simulated save failure")

    def _web_request() -> None:
        try:
            device_config.update_atomic(_failing_update)
        except RuntimeError:
            pass
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    web = threading.Thread(target=_web_request)
    web.start()
    assert started.wait(timeout=5)
    other = threading.Thread(target=mutate_in_other_thread)
    other.start()
    web.join(timeout=5)
    other.join(timeout=5)
    assert not web.is_alive()
    assert not other.is_alive()
    assert errors == []


def test_failure_counter_survives_concurrent_failed_update(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
    instance = _add_instance(device_config_dev)
    tracker = PluginHealthTracker(device_config_dev)

    _race_with_failed_update(
        device_config_dev,
        mutated=lambda: instance.consecutive_failure_count != 0,
        mutate_in_other_thread=lambda: tracker.on_failure(
            instance, _PLUGIN_ID, _INSTANCE
        ),
    )

    assert instance.consecutive_failure_count == 1
    assert _persisted_instance(device_config_dev)["consecutive_failure_count"] == 1


def test_circuit_breaker_reset_survives_concurrent_failed_update(
    device_config_dev: Any,
) -> None:
    instance = _add_instance(device_config_dev)
    instance.consecutive_failure_count = 5
    instance.paused = True
    instance.disabled_reason = "Paused after 5 consecutive failures"
    device_config_dev.write_config()
    tracker = PluginHealthTracker(device_config_dev)

    _race_with_failed_update(
        device_config_dev,
        mutated=lambda: not instance.paused,
        mutate_in_other_thread=lambda: tracker.reset_circuit_breaker(
            _PLUGIN_ID, _INSTANCE
        ),
    )

    assert instance.paused is False
    assert instance.consecutive_failure_count == 0
    persisted = _persisted_instance(device_config_dev)
    assert persisted["paused"] is False
    assert persisted["consecutive_failure_count"] == 0


def test_refresh_info_survives_concurrent_failed_update(
    device_config_dev: Any,
) -> None:
    from unittest.mock import MagicMock

    from refresh_task import RefreshTask

    task = RefreshTask(device_config_dev, MagicMock())
    refreshed_at = datetime(2026, 10, 2, 12, 0, tzinfo=UTC).isoformat()
    original = device_config_dev.refresh_info

    _race_with_failed_update(
        device_config_dev,
        mutated=lambda: device_config_dev.refresh_info is not original,
        mutate_in_other_thread=lambda: task._update_refresh_info(
            {
                "refresh_type": "Playlist",
                "plugin_id": _PLUGIN_ID,
                "refresh_time": refreshed_at,
                "image_hash": "abc",
            },
            {"request_ms": 1},
            used_cached=False,
        ),
    )

    assert isinstance(device_config_dev.refresh_info, RefreshInfo)
    assert device_config_dev.refresh_info.refresh_time == refreshed_at
    with open(device_config_dev.config_file, encoding="utf-8") as fh:
        assert json.load(fh)["refresh_info"]["refresh_time"] == refreshed_at
