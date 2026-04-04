# pyright: reportMissingImports=false


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
        "refresh_task.task.get_plugin_instance",
        lambda cfg: _dummy_plugin(device_config_dev),
        raising=True,
    )

    refresh = ManualRefresh("dummy", {})
    marker = tmp_path / "manual-execute.txt"

    def fake_execute(self, plugin, device_config, current_dt):
        marker.write_text("called", encoding="utf-8")
        return Image.new("RGB", device_config.get_resolution(), "white")

    monkeypatch.setattr(
        refresh, "execute", fake_execute.__get__(refresh, ManualRefresh)
    )

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
        RefreshTask,
        "_execute_with_policy",
        fake_execute_with_policy,
    )

    refresh = ManualRefresh("dummy", {})
    # Provide a fake latest_refresh with image_hash to avoid NoneType error
    fake_latest = type("LR", (), {"image_hash": None})()
    task._perform_refresh(refresh, fake_latest, __import__("datetime").datetime.now())
    assert "action" in called
    assert called["action"] is refresh


# ---------------------------------------------------------------------------
# Static helper tests (extracted for JTN-209)
# ---------------------------------------------------------------------------


def test_timeout_msg():
    from refresh_task import RefreshTask

    msg = RefreshTask._timeout_msg("weather", 30.0)
    assert msg == "Plugin 'weather' timed out after 30s"


def test_timeout_msg_truncates_float():
    from refresh_task import RefreshTask

    msg = RefreshTask._timeout_msg("clock", 10.7)
    assert "10s" in msg


def test_cleanup_subprocess_terminates(monkeypatch):
    from refresh_task import RefreshTask

    calls = []

    class FakeProc:
        pid = 999
        _alive = True

        def terminate(self):
            calls.append("terminate")
            self._alive = False

        def join(self, timeout=None):
            calls.append(("join", timeout))

        def is_alive(self):
            return self._alive

        def kill(self):
            calls.append("kill")

    proc = FakeProc()
    RefreshTask._cleanup_subprocess(proc, "test_plugin")
    assert "terminate" in calls
    assert not proc.is_alive()


def test_cleanup_subprocess_escalates_to_kill(monkeypatch):
    from refresh_task import RefreshTask

    class StubbornProc:
        pid = 123
        _kill_count = 0

        def terminate(self):
            pass

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return self._kill_count < 1

        def kill(self):
            self._kill_count += 1

    proc = StubbornProc()
    RefreshTask._cleanup_subprocess(proc, "stubborn")
    assert proc._kill_count >= 1


def test_handle_process_result_success():
    import io
    import queue

    from refresh_task import RefreshTask

    img = Image.new("RGB", (100, 100), "red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    q = queue.Queue()
    q.put({"ok": True, "image_bytes": buf.getvalue(), "plugin_meta": {"key": "val"}})

    class FakeProc:
        exitcode = 0

    result_img, meta = RefreshTask._handle_process_result(q, FakeProc(), "test", 1)
    assert result_img is not None
    assert meta == {"key": "val"}


def test_handle_process_result_error():
    import queue

    from refresh_task import RefreshTask

    q = queue.Queue()
    q.put({"ok": False, "error_type": "ValueError", "error_message": "bad input"})

    class FakeProc:
        exitcode = 1

    result_img, exc = RefreshTask._handle_process_result(q, FakeProc(), "test", 1)
    assert result_img is None
    assert isinstance(exc, Exception)


def test_handle_process_result_empty_queue_raises():
    import queue

    import pytest

    from refresh_task import RefreshTask

    q = queue.Queue()

    class FakeProc:
        exitcode = 1

    with pytest.raises(RuntimeError, match="exited with code"):
        RefreshTask._handle_process_result(q, FakeProc(), "test", 1)
