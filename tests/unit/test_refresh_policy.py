import os
import time

import pytest
from PIL import Image

from display.display_manager import DisplayManager
from refresh_task import RefreshTask, ManualRefresh


class SlowPlugin:
    config = {"image_settings": []}

    def generate_image(self, settings, device_config):
        time.sleep(0.2)
        return Image.new("RGB", device_config.get_resolution(), color=(255, 255, 255))


class FlakyPlugin:
    config = {"image_settings": []}

    def __init__(self):
        self.calls = 0

    def generate_image(self, settings, device_config):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("first failure")
        return Image.new("RGB", device_config.get_resolution(), color=(0, 255, 0))


def test_plugin_timeout_policy(device_config_dev, monkeypatch):
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    monkeypatch.setenv("INKYPI_PLUGIN_TIMEOUT_S", "0.05")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")

    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: {"id": "slow", "class": "Slow"})
    monkeypatch.setattr("refresh_task.get_plugin_instance", lambda cfg: SlowPlugin(), raising=True)

    task.start()
    try:
        with pytest.raises(TimeoutError):
            task.manual_update(ManualRefresh("slow", {}))
    finally:
        task.stop()


def test_plugin_retry_policy(device_config_dev, monkeypatch):
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    plugin = FlakyPlugin()

    monkeypatch.setenv("INKYPI_PLUGIN_TIMEOUT_S", "5")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "1")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_BACKOFF_MS", "1")

    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: {"id": "flaky", "class": "Flaky"})
    monkeypatch.setattr("refresh_task.get_plugin_instance", lambda cfg: plugin, raising=True)

    task.start()
    try:
        metrics = task.manual_update(ManualRefresh("flaky", {}))
        assert metrics is not None
        assert plugin.calls >= 2
    finally:
        task.stop()
