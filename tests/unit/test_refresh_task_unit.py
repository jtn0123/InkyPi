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


def test_handle_process_result_success(tmp_path):
    import queue

    from refresh_task import RefreshTask

    img = Image.new("RGB", (100, 100), "red")
    png_path = tmp_path / "rendered.png"
    img.save(png_path, format="PNG")

    q = queue.Queue()
    q.put({"ok": True, "image_path": str(png_path), "plugin_meta": {"key": "val"}})

    class FakeProc:
        exitcode = 0

    result_img, meta = RefreshTask._handle_process_result(q, FakeProc(), "test", 1)
    assert result_img is not None
    assert meta == {"key": "val"}
    # _handle_process_result must unlink the tempfile after reading.
    assert not png_path.exists(), "handler should delete the tempfile after read"


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


# ---------------------------------------------------------------------------
# JTN-786: manual_update returns after image-save, not after display finishes
# ---------------------------------------------------------------------------


def test_manual_update_returns_after_image_saved_not_display(
    device_config_dev, monkeypatch
):
    """JTN-786 regression test.

    On slow hardware (Inky 7.3" Impression / Pi Zero 2 W), the e-paper SPI
    write can take ~27s on top of a slow generate phase, pushing the total
    manual-update time past the 60s cap even though the image was safely
    on disk after ~30s.  The API should return as soon as the processed
    image lands on disk — not wait for the hardware to finish.
    """
    import time

    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    def slow_display(image_arg, **kwargs):
        # Simulate: image gets saved quickly, display push drags on for 90s.
        on_image_saved = kwargs.get("on_image_saved")
        if on_image_saved is not None:
            on_image_saved({"preprocess_ms": 100})
        time.sleep(90)
        return {"preprocess_ms": 100, "display_ms": 90000, "display_driver": "Fake"}

    monkeypatch.setattr(dm, "display_image", slow_display, raising=True)

    dummy_cfg = {"id": "dummy", "class": "Dummy"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.task.get_plugin_instance",
        lambda cfg: _dummy_plugin(device_config_dev),
        raising=True,
    )

    def fake_execute_with_policy(self, action, cfg, dt, request_id=None):
        img = Image.new("RGB", device_config_dev.get_resolution(), "white")
        return img, {}

    monkeypatch.setattr(RefreshTask, "_execute_with_policy", fake_execute_with_policy)

    # Keep the manual-update cap at its default 60s — the point of the test
    # is that we return in well under 60s despite the 90s display sleep.
    try:
        task.start()
        t0 = time.perf_counter()
        result = task.manual_update(ManualRefresh("dummy", {}))
        elapsed = time.perf_counter() - t0
        assert elapsed < 10, (
            f"manual_update returned in {elapsed:.1f}s — expected <10s, "
            "not the full 90s display sleep"
        )
        # The early-return metrics payload indicates the image-saved stage.
        assert isinstance(result, dict)
        assert result.get("stage") == "image_saved"
    finally:
        task.stop()


def test_manual_update_still_surfaces_generate_errors(device_config_dev, monkeypatch):
    """JTN-786: errors raised before image-save must still reach the caller.

    If ``_execute_with_policy`` raises (e.g. ``Plugin 'X' is not registered``
    from JTN-783), the background thread sets both ``done`` and
    ``image_saved`` via ``_complete_manual_request``, and the waiter must
    re-raise the underlying exception — not return an "image_saved" stub.
    """
    import pytest

    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    dummy_cfg = {"id": "dummy", "class": "Dummy"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

    def boom(self, action, cfg, dt, request_id=None):
        raise RuntimeError("generate failed")

    monkeypatch.setattr(RefreshTask, "_execute_with_policy", boom)

    try:
        task.start()
        with pytest.raises(RuntimeError, match="generate failed"):
            task.manual_update(ManualRefresh("dummy", {}))
    finally:
        task.stop()


def test_handle_process_result_empty_queue_raises():
    import queue

    import pytest

    from refresh_task import RefreshTask

    q = queue.Queue()

    class FakeProc:
        exitcode = 1

    with pytest.raises(RuntimeError, match="exited with code"):
        RefreshTask._handle_process_result(q, FakeProc(), "test", 1)
