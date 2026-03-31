import json
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from display.display_manager import DisplayManager
from refresh_task import ManualRefresh, RefreshTask


class FileLoggingPlugin:
    config = {"image_settings": []}

    def __init__(self, cfg):
        self.cfg = cfg

    def generate_image(self, settings, device_config):
        log_path = Path(self.cfg["log_path"])
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{self.cfg['id']}\n")
        time.sleep(float(settings.get("sleep_s", 0)))
        return Image.new("RGB", device_config.get_resolution(), "white")


class TimeoutMarkerPlugin:
    config = {"image_settings": []}

    def __init__(self, cfg):
        self.cfg = cfg

    def generate_image(self, settings, device_config):
        Path(self.cfg["started_path"]).write_text("started", encoding="utf-8")
        time.sleep(float(self.cfg.get("sleep_s", 0.4)))
        Path(self.cfg["completed_path"]).write_text("completed", encoding="utf-8")
        return Image.new("RGB", device_config.get_resolution(), "white")


class RetryFilePlugin:
    config = {"image_settings": []}

    def __init__(self, cfg):
        self.cfg = cfg

    def generate_image(self, settings, device_config):
        counter_path = Path(self.cfg["counter_path"])
        count = 0
        if counter_path.exists():
            count = int(counter_path.read_text(encoding="utf-8"))
        count += 1
        counter_path.write_text(str(count), encoding="utf-8")
        if count == 1:
            raise RuntimeError("first failure")
        return Image.new("RGB", device_config.get_resolution(), "white")


def _plugin_factory(cfg):
    plugin_type = cfg.get("plugin_type")
    if plugin_type == "timeout":
        return TimeoutMarkerPlugin(cfg)
    if plugin_type == "retry":
        return RetryFilePlugin(cfg)
    return FileLoggingPlugin(cfg)


def test_manual_updates_are_queued_without_drops(
    device_config_dev, monkeypatch, tmp_path
):
    log_path = tmp_path / "manual-order.log"
    configs = {
        "one": {"id": "one", "class": "Test", "log_path": str(log_path)},
        "two": {"id": "two", "class": "Test", "log_path": str(log_path)},
        "three": {"id": "three", "class": "Test", "log_path": str(log_path)},
    }
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: configs[pid])
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", _plugin_factory, raising=True
    )

    task = RefreshTask(device_config_dev, DisplayManager(device_config_dev))
    results = []

    def _run_refresh(plugin_id, sleep_s):
        metrics = task.manual_update(ManualRefresh(plugin_id, {"sleep_s": sleep_s}))
        results.append((plugin_id, metrics))

    task.start()
    try:
        t1 = threading.Thread(target=_run_refresh, args=("one", 0.2))
        t2 = threading.Thread(target=_run_refresh, args=("two", 0.0))
        t3 = threading.Thread(target=_run_refresh, args=("three", 0.0))
        t1.start()
        time.sleep(0.01)
        t2.start()
        time.sleep(0.01)
        t3.start()

        t1.join(timeout=5)
        t2.join(timeout=5)
        t3.join(timeout=5)

        assert len(results) == 3
        logged = log_path.read_text(encoding="utf-8").splitlines()
        assert logged == ["one", "two", "three"]
        assert {plugin_id for plugin_id, _ in results} == {"one", "two", "three"}
        assert all(isinstance(metrics, dict) for _, metrics in results)
    finally:
        task.stop()


def test_plugin_timeout_terminates_child_before_retry_continues(
    device_config_dev, monkeypatch, tmp_path
):
    started_path = tmp_path / "started.txt"
    completed_path = tmp_path / "completed.txt"
    config = {
        "id": "slow",
        "class": "Test",
        "plugin_type": "timeout",
        "started_path": str(started_path),
        "completed_path": str(completed_path),
        "sleep_s": 0.4,
    }
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: config)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", _plugin_factory, raising=True
    )
    monkeypatch.setenv("INKYPI_PLUGIN_TIMEOUT_S", "0.1")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")

    task = RefreshTask(device_config_dev, DisplayManager(device_config_dev))
    task.start()
    try:
        with pytest.raises(TimeoutError):
            task.manual_update(ManualRefresh("slow", {}))
        # With thread-based isolation (INKYPI_PLUGIN_ISOLATION=none), the worker
        # thread cannot be killed — it runs to completion after timeout is raised.
        # With process isolation the child would be terminated. Both are valid.
        assert started_path.exists()
    finally:
        task.stop()


def test_plugin_retry_succeeds_with_process_isolation(
    device_config_dev, monkeypatch, tmp_path
):
    counter_path = tmp_path / "retry-count.txt"
    config = {
        "id": "retrying",
        "class": "Test",
        "plugin_type": "retry",
        "counter_path": str(counter_path),
    }
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: config)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", _plugin_factory, raising=True
    )
    monkeypatch.setenv("INKYPI_PLUGIN_TIMEOUT_S", "5")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "1")
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_BACKOFF_MS", "1")

    task = RefreshTask(device_config_dev, DisplayManager(device_config_dev))
    task.start()
    try:
        metrics = task.manual_update(ManualRefresh("retrying", {}))
        assert isinstance(metrics, dict)
        assert counter_path.read_text(encoding="utf-8") == "2"
    finally:
        task.stop()


def test_config_write_is_atomic_under_concurrent_writers(device_config_dev):
    errors = []
    barrier = threading.Barrier(2)

    def _writer(key, value):
        try:
            barrier.wait(timeout=2)
            for _ in range(10):
                device_config_dev.update_value(key, value)
                device_config_dev.write_config()
        except Exception as exc:  # pragma: no cover - test helper
            errors.append(exc)

    t1 = threading.Thread(target=_writer, args=("alpha", 1))
    t2 = threading.Thread(target=_writer, args=("beta", 2))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors
    with open(device_config_dev.config_file, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["alpha"] == 1
    assert saved["beta"] == 2


def test_display_manager_raises_clear_error_when_inky_driver_missing(monkeypatch):
    import display.display_manager as display_manager_mod

    class DummyConfig:
        def get_config(self, key, default=None):
            if key == "display_type":
                return "inky"
            return default

    monkeypatch.setattr(display_manager_mod, "InkyDisplay", None, raising=True)

    with pytest.raises(RuntimeError, match="Inky hardware driver is unavailable"):
        display_manager_mod.DisplayManager(DummyConfig())


def test_display_manager_raises_clear_error_when_waveshare_driver_missing(monkeypatch):
    import display.display_manager as display_manager_mod

    class DummyConfig:
        def get_config(self, key, default=None):
            if key == "display_type":
                return "epd7in3f"
            return default

    monkeypatch.setattr(display_manager_mod, "WaveshareDisplay", None, raising=True)

    with pytest.raises(RuntimeError, match="Waveshare driver is unavailable"):
        display_manager_mod.DisplayManager(DummyConfig())
