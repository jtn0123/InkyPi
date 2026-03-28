# pyright: reportMissingImports=false

import threading
import time

from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dummy_plugin(device_config):
    class DummyPlugin:
        config = {"image_settings": []}

        def generate_image(self, settings, cfg):
            return Image.new("RGB", cfg.get_resolution(), "white")

    return DummyPlugin()


# ---------------------------------------------------------------------------
# Control / lifecycle tests (from test_refresh_task_controls.py)
# ---------------------------------------------------------------------------


def test_signal_config_change_noop_when_not_running(device_config_dev, monkeypatch):
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    # Not running -> should not error
    task.signal_config_change()


def test_manual_update_raises_exception_from_thread(device_config_dev, monkeypatch):
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    monkeypatch.setattr(
        task,
        "_perform_refresh",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        raising=True,
    )

    try:
        task.start()
        try:
            task.manual_update(ManualRefresh("ai_text", {}))
            assert False, "expected exception"
        except RuntimeError as exc:
            assert "boom" in str(exc)
    finally:
        task.stop()


# ---------------------------------------------------------------------------
# Execute / refresh-flow tests (from test_refresh_task_execute.py)
# ---------------------------------------------------------------------------


def test_manual_refresh_uses_execute(device_config_dev, monkeypatch, tmp_path):
    """Ensure ManualRefresh is executed via the unified execute method."""
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    # Stub plugin retrieval
    dummy_cfg = {"id": "dummy", "class": "Dummy"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance",
        lambda cfg: _dummy_plugin(device_config_dev),
        raising=True,
    )

    refresh = ManualRefresh("dummy", {})
    marker = tmp_path / "manual-execute.txt"

    def fake_execute(self, plugin, device_config, current_dt):
        marker.write_text("called", encoding="utf-8")
        return Image.new("RGB", device_config.get_resolution(), "white")

    monkeypatch.setattr(refresh, "execute", fake_execute.__get__(refresh, ManualRefresh))

    try:
        task.start()
        task.manual_update(refresh)
        assert marker.exists(), "execute was never called"
        assert marker.read_text(encoding="utf-8") == "called"
    finally:
        task.stop()


def test_perform_refresh_calls_execute_with_policy(device_config_dev, monkeypatch):
    """Ensure _perform_refresh delegates to _execute_with_policy."""
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    dummy_cfg = {"id": "dummy", "class": "Dummy"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

    called = {}

    def fake_execute_with_policy(self, action, cfg, dt, request_id=None):
        called["action"] = action
        img = Image.new("RGB", device_config_dev.get_resolution(), "white")
        return img, {}

    monkeypatch.setattr(
        RefreshTask, "_execute_with_policy",
        fake_execute_with_policy,
    )

    refresh = ManualRefresh("dummy", {})
    # Provide a fake latest_refresh with image_hash to avoid NoneType error
    fake_latest = type("LR", (), {"image_hash": None})()
    task._perform_refresh(refresh, fake_latest, __import__("datetime").datetime.now())
    assert "action" in called
    assert called["action"] is refresh
