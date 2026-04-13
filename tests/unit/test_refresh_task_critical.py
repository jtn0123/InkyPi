# pyright: reportMissingImports=false
"""Tests for critical untested paths in refresh_task.py (JTN-71).

Covers:
- _remote_exception()
- _get_mp_context()
- _execute_refresh_attempt_worker()
- RefreshTask.stop()
- _execute_with_policy() error/timeout paths
"""

import io
import os
import queue
import threading
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from PIL import Image

from refresh_task import (
    ManualUpdateRequest,
    RefreshTask,
    _get_mp_context,
    _remote_exception,
)

# ---------------------------------------------------------------------------
# _remote_exception
# ---------------------------------------------------------------------------


class TestRemoteException:
    def test_known_types(self):
        for name, cls in [
            ("RuntimeError", RuntimeError),
            ("ValueError", ValueError),
            ("TimeoutError", TimeoutError),
            ("TypeError", TypeError),
            ("FileNotFoundError", FileNotFoundError),
        ]:
            exc = _remote_exception(name, "msg")
            assert isinstance(exc, cls)
            assert str(exc) == "msg"

    def test_key_error(self):
        exc = _remote_exception("KeyError", "missing_key")
        assert isinstance(exc, KeyError)
        assert "missing_key" in str(exc)

    def test_unknown_type_defaults_to_runtime_error(self):
        exc = _remote_exception("SomeWeirdError", "oops")
        assert isinstance(exc, RuntimeError)
        assert "oops" in str(exc)


# ---------------------------------------------------------------------------
# _get_mp_context
# ---------------------------------------------------------------------------


class TestGetMpContext:
    def test_returns_context(self):
        ctx = _get_mp_context()
        assert ctx is not None
        assert hasattr(ctx, "Process")
        assert hasattr(ctx, "Queue")


# ---------------------------------------------------------------------------
# _execute_refresh_attempt_worker — success path
# ---------------------------------------------------------------------------


class TestExecuteRefreshAttemptWorker:
    def test_success_puts_ok_payload(self, device_config_dev):
        from refresh_task import _execute_refresh_attempt_worker

        result_queue = queue.Queue()

        class FakePlugin:
            def generate_image(self, settings, cfg):
                return Image.new("RGB", (10, 10), "red")

            def get_latest_metadata(self):
                return {"key": "val"}

        class FakeAction:
            def execute(self, plugin, cfg, dt):
                return plugin.generate_image(None, cfg)

        # Mock get_plugin_instance and _restore_child_config
        with (
            patch("refresh_task.worker.get_plugin_instance", return_value=FakePlugin()),
            patch(
                "refresh_task.worker._restore_child_config",
                return_value=device_config_dev,
            ),
        ):
            _execute_refresh_attempt_worker(
                result_queue,
                {"id": "test"},
                FakeAction(),
                device_config_dev,
                datetime.now(UTC),
            )

        payload = result_queue.get_nowait()
        assert payload["ok"] is True
        assert "image_bytes" in payload
        # Verify it's valid PNG bytes
        img = Image.open(io.BytesIO(payload["image_bytes"]))
        assert img.size == (10, 10)

    def test_none_image_puts_error(self, device_config_dev):
        from refresh_task import _execute_refresh_attempt_worker

        result_queue = queue.Queue()

        class NullPlugin:
            def generate_image(self, settings, cfg):
                return None

        class FakeAction:
            def execute(self, plugin, cfg, dt):
                return None

        with (
            patch("refresh_task.worker.get_plugin_instance", return_value=NullPlugin()),
            patch(
                "refresh_task.worker._restore_child_config",
                return_value=device_config_dev,
            ),
        ):
            _execute_refresh_attempt_worker(
                result_queue,
                {"id": "test"},
                FakeAction(),
                device_config_dev,
                datetime.now(UTC),
            )

        payload = result_queue.get_nowait()
        assert payload["ok"] is False
        assert payload["error_type"] == "RuntimeError"
        assert "None" in payload["error_message"]

    def test_exception_puts_error_payload(self, device_config_dev):
        from refresh_task import _execute_refresh_attempt_worker

        result_queue = queue.Queue()

        class BrokenAction:
            def execute(self, plugin, cfg, dt):
                raise ValueError("bad config")

        with (
            patch("refresh_task.worker.get_plugin_instance", return_value=MagicMock()),
            patch(
                "refresh_task.worker._restore_child_config",
                return_value=device_config_dev,
            ),
        ):
            _execute_refresh_attempt_worker(
                result_queue,
                {"id": "test"},
                BrokenAction(),
                device_config_dev,
                datetime.now(UTC),
            )

        payload = result_queue.get_nowait()
        assert payload["ok"] is False
        assert payload["error_type"] == "ValueError"
        assert "bad config" in payload["error_message"]
        assert "traceback" in payload


# ---------------------------------------------------------------------------
# RefreshTask.stop()
# ---------------------------------------------------------------------------


class TestRefreshTaskStop:
    def _make_task(self, device_config_dev):
        dm = MagicMock()
        return RefreshTask(device_config_dev, dm)

    def test_stop_rejects_pending_requests(self, device_config_dev):
        task = self._make_task(device_config_dev)
        task.running = True

        req1 = ManualUpdateRequest("r1", MagicMock())
        req2 = ManualUpdateRequest("r2", MagicMock())
        task.manual_update_requests.append(req1)
        task.manual_update_requests.append(req2)

        task.stop()

        assert task.running is False
        assert req1.done.is_set()
        assert req2.done.is_set()
        assert isinstance(req1.exception, RuntimeError)
        assert isinstance(req2.exception, RuntimeError)

    def test_stop_when_not_running(self, device_config_dev):
        """stop() on an already-stopped task should not raise."""
        task = self._make_task(device_config_dev)
        task.running = False
        task.stop()  # should not raise

    def test_stop_joins_thread(self, device_config_dev):
        task = self._make_task(device_config_dev)
        task.running = True

        # Create a thread that exits immediately
        done_event = threading.Event()

        def _quick():
            done_event.wait(timeout=5)

        task.thread = threading.Thread(target=_quick, daemon=True)
        task.thread.start()
        done_event.set()

        task.stop()
        assert not task.thread.is_alive()


# ---------------------------------------------------------------------------
# _execute_with_policy — error paths via mocked Process
# ---------------------------------------------------------------------------


class TestExecuteWithPolicyErrors:
    def _make_task(self, device_config_dev):
        dm = MagicMock()
        task = RefreshTask(device_config_dev, dm)
        task.running = True
        return task

    @staticmethod
    def _mock_action():
        action = MagicMock()
        action.get_plugin_id.return_value = "test_plugin"
        return action

    def test_empty_queue_zero_exit_raises(self, device_config_dev):
        """Process exits cleanly but puts nothing in queue."""
        task = self._make_task(device_config_dev)

        fake_proc = MagicMock()
        fake_proc.is_alive.return_value = False
        fake_proc.exitcode = 0
        fake_queue = MagicMock()
        fake_queue.get_nowait.side_effect = queue.Empty

        ctx = MagicMock()
        ctx.Process.return_value = fake_proc
        ctx.Queue.return_value = fake_queue

        with (
            patch("refresh_task.task._get_mp_context", return_value=ctx),
            patch.dict(os.environ, {"INKYPI_PLUGIN_ISOLATION": "process"}),
        ):
            try:
                task._execute_with_policy(
                    self._mock_action(),
                    {"id": "test"},
                    datetime.now(UTC),
                    "req-1",
                )
                assert False, "Expected RuntimeError"
            except RuntimeError as e:
                assert "without returning a result" in str(e)

    def test_empty_queue_nonzero_exit_raises(self, device_config_dev):
        """Process crashes (exit code != 0) and puts nothing in queue."""
        task = self._make_task(device_config_dev)

        fake_proc = MagicMock()
        fake_proc.is_alive.return_value = False
        fake_proc.exitcode = -9
        fake_queue = MagicMock()
        fake_queue.get_nowait.side_effect = queue.Empty

        ctx = MagicMock()
        ctx.Process.return_value = fake_proc
        ctx.Queue.return_value = fake_queue

        with (
            patch("refresh_task.task._get_mp_context", return_value=ctx),
            patch.dict(os.environ, {"INKYPI_PLUGIN_ISOLATION": "process"}),
        ):
            try:
                task._execute_with_policy(
                    self._mock_action(),
                    {"id": "test"},
                    datetime.now(UTC),
                    "req-1",
                )
                assert False, "Expected RuntimeError"
            except RuntimeError as e:
                assert "exited with code -9" in str(e)

    def test_error_payload_raises_remote_exception(self, device_config_dev):
        """Process returns an error payload — should reconstruct the exception."""
        task = self._make_task(device_config_dev)

        fake_proc = MagicMock()
        fake_proc.is_alive.return_value = False
        fake_proc.exitcode = 0
        fake_queue = MagicMock()
        fake_queue.get_nowait.return_value = {
            "ok": False,
            "error_type": "ValueError",
            "error_message": "bad input",
        }

        ctx = MagicMock()
        ctx.Process.return_value = fake_proc
        ctx.Queue.return_value = fake_queue

        with (
            patch("refresh_task.task._get_mp_context", return_value=ctx),
            patch.dict(os.environ, {"INKYPI_PLUGIN_ISOLATION": "process"}),
        ):
            try:
                task._execute_with_policy(
                    self._mock_action(),
                    {"id": "test"},
                    datetime.now(UTC),
                    "req-1",
                )
                assert False, "Expected ValueError"
            except ValueError as e:
                assert "bad input" in str(e)

    def test_timeout_terminates_process(self, device_config_dev):
        """Process hangs past timeout — should terminate and raise TimeoutError."""
        task = self._make_task(device_config_dev)

        fake_proc = MagicMock()
        # is_alive: True after join (still running), then False after terminate+join
        # Provide extra False values for any additional checks
        fake_proc.is_alive.side_effect = [True, False, False, False]
        fake_proc.exitcode = None
        fake_proc.pid = 12345
        fake_queue = MagicMock()

        ctx = MagicMock()
        ctx.Process.return_value = fake_proc
        ctx.Queue.return_value = fake_queue

        with (
            patch("refresh_task.task._get_mp_context", return_value=ctx),
            patch.dict(
                os.environ,
                {
                    "INKYPI_PLUGIN_ISOLATION": "process",
                    "INKYPI_PLUGIN_RETRY_MAX": "0",
                },
            ),
        ):
            try:
                task._execute_with_policy(
                    self._mock_action(),
                    {"id": "test"},
                    datetime.now(UTC),
                    "req-1",
                )
                assert False, "Expected TimeoutError"
            except TimeoutError as e:
                assert "timed out" in str(e)
            fake_proc.terminate.assert_called_once()
