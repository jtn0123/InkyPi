import logging
import sqlite3
from typing import Any

import pytest
from flask.testing import FlaskClient
from PIL import Image

from display.display_manager import DisplayManager
from refresh_task import ManualRefresh, RefreshTask


class GoodPlugin:
    config: dict[str, list[Any]] = {"image_settings": []}

    def generate_image(self, settings: Any, device_config: Any) -> Any:
        return Image.new("RGB", device_config.get_resolution(), "white")


def test_benchmark_lock_does_not_wedge_manual_update(
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
    device_config_dev.update_value("enable_benchmarks", True)

    display_manager = DisplayManager(device_config_dev)
    refresh_task = RefreshTask(device_config_dev, display_manager)

    monkeypatch.setattr(
        device_config_dev,
        "get_plugin",
        lambda plugin_id: {"id": plugin_id, "class": "Good"},
    )
    monkeypatch.setattr(
        "refresh_task.plugin_lookup.get_plugin_instance",
        lambda cfg: GoodPlugin(),
        raising=True,
    )
    lock_calls: list[dict[str, Any]] = []

    def locked_save_refresh_event(_cfg: Any, refresh_event: dict[str, Any]) -> None:
        lock_calls.append(refresh_event)
        raise sqlite3.OperationalError("database is locked")

    # Patch the name where RefreshRecorder.save_refresh actually looks it up.
    monkeypatch.setattr(
        "refresh_task.recorder.save_refresh_event",
        locked_save_refresh_event,
        raising=True,
    )

    refresh_task.start()
    try:
        with caplog.at_level(logging.DEBUG, logger="refresh_task.recorder"):
            metrics = refresh_task.manual_update(ManualRefresh("good", {}))
        assert metrics is not None
        # The locked write was really attempted for this refresh ...
        assert len(lock_calls) == 1
        assert lock_calls[0]["plugin_id"] == "good"
        # ... and the failure was logged rather than propagated.
        assert any(
            "Failed to save refresh benchmark event" in rec.getMessage()
            and rec.exc_info is not None
            and isinstance(rec.exc_info[1], sqlite3.OperationalError)
            for rec in caplog.records
        )
        assert refresh_task.running is True
        assert refresh_task.thread is not None
        assert refresh_task.thread.is_alive()

        # The worker is not wedged: a second refresh still completes.
        assert refresh_task.manual_update(ManualRefresh("good", {})) is not None
        assert len(lock_calls) == 2
    finally:
        refresh_task.stop()


def test_plugin_failure_remains_actionable_and_task_recovers(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")

    display_manager = DisplayManager(device_config_dev)
    refresh_task = RefreshTask(device_config_dev, display_manager)

    monkeypatch.setattr(
        device_config_dev,
        "get_plugin",
        lambda plugin_id: {"id": plugin_id, "class": "Good"},
    )

    class BrokenPlugin:
        config: dict[str, list[Any]] = {"image_settings": []}

        def generate_image(self, settings: Any, device_config: Any) -> None:
            raise OSError("broken PNG stream")

    current_plugin: dict[str, Any] = {"instance": BrokenPlugin()}

    monkeypatch.setattr(
        "refresh_task.plugin_lookup.get_plugin_instance",
        lambda cfg: current_plugin["instance"],
        raising=True,
    )

    refresh_task.start()
    try:
        # In subprocess mode OSError is wrapped as RuntimeError; in
        # in-process mode the original OSError propagates directly.
        with pytest.raises(Exception, match="broken PNG stream"):
            refresh_task.manual_update(ManualRefresh("faulty", {}))

        assert refresh_task.running is True
        assert refresh_task.thread is not None
        assert refresh_task.thread.is_alive()

        # Verify failure was recorded
        health_after_fail = refresh_task.get_health_snapshot()
        assert health_after_fail["faulty"]["failure_count"] >= 1

        current_plugin["instance"] = GoodPlugin()
        metrics = refresh_task.manual_update(ManualRefresh("faulty", {}))
        assert metrics is not None

        health = refresh_task.get_health_snapshot()
        # After successful recovery, failure_count is reset to 0
        assert health["faulty"]["failure_count"] == 0
        assert health["faulty"]["success_count"] >= 1
        assert health["faulty"]["last_seen"]
    finally:
        refresh_task.stop()


def test_health_endpoints_still_respond_after_display_failure(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = client.application
    display_manager = app.config["DISPLAY_MANAGER"]

    def raise_display(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(display_manager, "display_image", raise_display, raising=True)

    failed = client.post("/update_now", data={"plugin_id": "clock"})
    assert failed.status_code == 500

    plugins = client.get("/api/health/plugins")
    system = client.get("/api/health/system")
    assert plugins.status_code == 200
    assert system.status_code == 200
    assert plugins.get_json()["success"] is True
    assert system.get_json()["success"] is True
