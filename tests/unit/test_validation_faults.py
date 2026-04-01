import sqlite3

import pytest
from PIL import Image

from display.display_manager import DisplayManager
from refresh_task import ManualRefresh, RefreshTask


class GoodPlugin:
    config = {"image_settings": []}

    def generate_image(self, settings, device_config):
        return Image.new("RGB", device_config.get_resolution(), "white")


def test_benchmark_lock_does_not_wedge_manual_update(device_config_dev, monkeypatch):
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
        "refresh_task.task.get_plugin_instance",
        lambda cfg: GoodPlugin(),
        raising=True,
    )
    monkeypatch.setattr(
        "refresh_task.task.save_refresh_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("database is locked")
        ),
        raising=True,
    )

    refresh_task.start()
    try:
        metrics = refresh_task.manual_update(ManualRefresh("good", {}))
        assert metrics is not None
        assert refresh_task.running is True
        assert refresh_task.thread.is_alive()
    finally:
        refresh_task.stop()


def test_plugin_failure_remains_actionable_and_task_recovers(
    device_config_dev, monkeypatch
):
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")

    display_manager = DisplayManager(device_config_dev)
    refresh_task = RefreshTask(device_config_dev, display_manager)

    monkeypatch.setattr(
        device_config_dev,
        "get_plugin",
        lambda plugin_id: {"id": plugin_id, "class": "Good"},
    )

    class BrokenPlugin:
        config = {"image_settings": []}

        def generate_image(self, settings, device_config):
            raise OSError("broken PNG stream")

    current_plugin = {"instance": BrokenPlugin()}

    monkeypatch.setattr(
        "refresh_task.task.get_plugin_instance",
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


def test_health_endpoints_still_respond_after_display_failure(client, monkeypatch):
    app = client.application
    display_manager = app.config["DISPLAY_MANAGER"]

    def raise_display(*args, **kwargs):
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
