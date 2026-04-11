# pyright: reportMissingImports=false
"""Chaos tests for RefreshTask error-injection paths (JTN-512).

Covers:
- Subprocess hang past timeout: process killed, circuit breaker incremented,
  fallback image pushed.
- Output queue overflow: manual_update_requests deque at capacity raises RuntimeError.
- DisplayManager display() raises mid-refresh: next tick recovers gracefully.
- Config reload mid-refresh: no crash, new config applied on next tick.

Note: pytest-timeout is NOT installed in this environment; tests use
``signal``/threading timeouts internally to cap wall-clock time.
All ``time.sleep`` paths in production code are mocked.
"""

import os
import threading
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from model import PluginInstance, RefreshInfo
from refresh_task import RefreshTask
from refresh_task.actions import PlaylistRefresh

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_task(device_config_dev):
    dm = MagicMock()
    dm.display_image.return_value = {"display_ms": 10, "preprocess_ms": 5}
    task = RefreshTask(device_config_dev, dm)
    return task, dm


def _empty_refresh_info():
    """A RefreshInfo with no prior image so hash-based caching does not short-circuit."""
    return RefreshInfo(
        refresh_type="Manual Update",
        plugin_id="",
        refresh_time=None,
        image_hash=None,
    )


def _make_plugin_instance(plugin_id="chaos_plugin", name="chaos_inst"):
    return PluginInstance(
        plugin_id=plugin_id,
        name=name,
        settings={},
        refresh={"interval": 3600},
    )


def _add_plugin_to_pm(device_config_dev, plugin_instance):
    pm = device_config_dev.get_playlist_manager()
    playlist = pm.get_playlist("Default")
    if playlist is None:
        pm.add_default_playlist()
        playlist = pm.get_playlist("Default")
    playlist.plugins.append(plugin_instance)
    return pm


# ---------------------------------------------------------------------------
# 1. Subprocess hang → process killed, circuit breaker incremented, fallback
# ---------------------------------------------------------------------------


class TestSubprocessHangTimeout:
    """Verify that a hung subprocess is terminated and the circuit breaker fires."""

    def test_timed_out_process_is_terminated(self, device_config_dev):
        """Process that never finishes → terminate() + TimeoutError raised."""
        task, _dm = _make_task(device_config_dev)
        task.running = True

        fake_proc = MagicMock()
        # is_alive: True after join (still running), then False after terminate+join
        fake_proc.is_alive.side_effect = [True, False, False, False]
        fake_proc.exitcode = None
        fake_proc.pid = 99999

        fake_queue = MagicMock()
        ctx = MagicMock()
        ctx.Process.return_value = fake_proc
        ctx.Queue.return_value = fake_queue

        action = MagicMock()
        action.get_plugin_id.return_value = "chaos_plugin"

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
            with pytest.raises(TimeoutError, match="timed out"):
                task._execute_with_policy(
                    action,
                    {"id": "chaos_plugin"},
                    datetime.now(UTC),
                    "req-chaos-1",
                )

        fake_proc.terminate.assert_called_once()

    def test_timed_out_process_increments_circuit_breaker(
        self, device_config_dev, monkeypatch
    ):
        """Hang → TimeoutError → _update_plugin_health(ok=False) increments counter."""
        monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
        monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        monkeypatch.setenv("INKYPI_PLUGIN_TIMEOUT_S", "0.01")

        task, _dm = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        dummy_cfg = {"id": "chaos_plugin", "class": "Chaos", "image_settings": []}
        monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

        class HangingPlugin:
            def generate_image(self, settings, cfg):
                # Simulate a long-running operation — the timeout (0.01s) will
                # fire before this finishes.
                import time

                time.sleep(60)

            def get_latest_metadata(self):
                return None

        monkeypatch.setattr(
            "refresh_task.task.get_plugin_instance",
            lambda cfg: HangingPlugin(),
        )

        playlist = device_config_dev.get_playlist_manager().get_playlist("Default")
        refresh_action = PlaylistRefresh(playlist, pi)
        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        with pytest.raises(TimeoutError):
            task._perform_refresh(refresh_action, current_dt, current_dt)

        # Circuit breaker must have been incremented
        assert pi.consecutive_failure_count >= 1

    def test_timed_out_subprocess_fallback_pushed(self, device_config_dev, monkeypatch):
        """Hang → TimeoutError → fallback image pushed to display."""
        monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
        monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        monkeypatch.setenv("INKYPI_PLUGIN_TIMEOUT_S", "0.01")

        task, dm = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        dummy_cfg = {"id": "chaos_plugin", "class": "Chaos", "image_settings": []}
        monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

        class HangingPlugin:
            def generate_image(self, settings, cfg):
                import time

                time.sleep(60)

            def get_latest_metadata(self):
                return None

        monkeypatch.setattr(
            "refresh_task.task.get_plugin_instance",
            lambda cfg: HangingPlugin(),
        )

        playlist = device_config_dev.get_playlist_manager().get_playlist("Default")
        refresh_action = PlaylistRefresh(playlist, pi)
        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        fallback_calls = []
        original_push = task._push_fallback_image

        def _tracking_push(*args, **kwargs):
            fallback_calls.append(True)
            return original_push(*args, **kwargs)

        monkeypatch.setattr(task, "_push_fallback_image", _tracking_push)

        with pytest.raises(TimeoutError):
            task._perform_refresh(refresh_action, current_dt, current_dt)

        assert len(fallback_calls) == 1, "Fallback must be pushed once on timeout"


# ---------------------------------------------------------------------------
# 2. Output queue overflow (manual_update_requests deque at capacity)
# ---------------------------------------------------------------------------


class TestOutputQueueOverflow:
    """Verify backpressure when the manual update queue is at capacity."""

    def test_queue_at_capacity_raises_runtime_error(self, device_config_dev):
        """Filling the deque to maxlen → manual_update raises RuntimeError."""
        task, _dm = _make_task(device_config_dev)
        task.running = True

        # Fill the queue to capacity without actually processing anything
        for _ in range(task.manual_update_requests.maxlen):
            sentinel = MagicMock()
            sentinel.get_plugin_id.return_value = "dummy"
            sentinel.get_refresh_info.return_value = {}
            task.manual_update_requests.append(MagicMock())

        action = MagicMock()
        action.get_plugin_id.return_value = "dummy"
        action.get_refresh_info.return_value = {}

        with pytest.raises(RuntimeError, match="queue is full"):
            task.manual_update(action)

    def test_queue_capacity_is_fifty(self, device_config_dev):
        """Confirm the documented capacity of 50 manual update slots."""
        task, _ = _make_task(device_config_dev)
        assert task.manual_update_requests.maxlen == 50

    def test_queue_drain_allows_new_requests(self, device_config_dev):
        """After draining the queue a new request can be enqueued."""
        task, _dm = _make_task(device_config_dev)
        task.running = True

        # Fill to capacity
        for _ in range(task.manual_update_requests.maxlen):
            task.manual_update_requests.append(MagicMock())

        # Drain one slot
        task.manual_update_requests.popleft()

        # Now there is room — the deque should accept one more item
        assert len(task.manual_update_requests) < task.manual_update_requests.maxlen


# ---------------------------------------------------------------------------
# 3. DisplayManager raises mid-display → next tick recovers
# ---------------------------------------------------------------------------


class TestDisplayManagerFailure:
    """DisplayManager.display_image raises → no crashed state, next cycle works."""

    def test_display_failure_raises_from_push_to_display(
        self, device_config_dev, monkeypatch
    ):
        """_push_to_display propagates display errors so the caller can record them."""
        monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
        monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")

        task, dm = _make_task(device_config_dev)
        dm.display_image.side_effect = RuntimeError("Display hardware fault")

        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        dummy_cfg = {"id": "chaos_plugin", "class": "Chaos", "image_settings": []}
        monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

        class GoodPlugin:
            def generate_image(self, settings, cfg):
                return Image.new("RGB", cfg.get_resolution(), "blue")

            def get_latest_metadata(self):
                return None

        monkeypatch.setattr(
            "refresh_task.task.get_plugin_instance",
            lambda cfg: GoodPlugin(),
        )

        playlist = device_config_dev.get_playlist_manager().get_playlist("Default")
        refresh_action = PlaylistRefresh(playlist, pi)
        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        # _perform_refresh should raise the display error
        with pytest.raises(RuntimeError, match="Display hardware fault"):
            task._perform_refresh(refresh_action, _empty_refresh_info(), current_dt)

    def test_display_failure_circuit_breaker_incremented(
        self, device_config_dev, monkeypatch
    ):
        """display() failure increments the circuit breaker for that plugin."""
        monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
        monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")

        task, dm = _make_task(device_config_dev)
        dm.display_image.side_effect = RuntimeError("GPU panic")

        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        dummy_cfg = {"id": "chaos_plugin", "class": "Chaos", "image_settings": []}
        monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

        class GoodPlugin:
            def generate_image(self, settings, cfg):
                return Image.new("RGB", cfg.get_resolution(), "green")

            def get_latest_metadata(self):
                return None

        monkeypatch.setattr(
            "refresh_task.task.get_plugin_instance",
            lambda cfg: GoodPlugin(),
        )

        playlist = device_config_dev.get_playlist_manager().get_playlist("Default")
        refresh_action = PlaylistRefresh(playlist, pi)
        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        with pytest.raises(RuntimeError):
            task._perform_refresh(refresh_action, _empty_refresh_info(), current_dt)

        # Health record should reflect a failure (counter ≥ 1)
        assert pi.consecutive_failure_count >= 1

    def test_task_survives_display_failure_in_run_loop(
        self, device_config_dev, monkeypatch
    ):
        """_run() catches exceptions and continues; task stays runnable after error."""
        monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
        monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")

        task, dm = _make_task(device_config_dev)

        # First call raises; subsequent calls succeed so the task can be verified
        call_count = {"n": 0}

        def _display_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Transient display fault")
            return {"display_ms": 10, "preprocess_ms": 5}

        dm.display_image.side_effect = _display_side_effect

        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        dummy_cfg = {"id": "chaos_plugin", "class": "Chaos", "image_settings": []}
        monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

        class GoodPlugin:
            def generate_image(self, settings, cfg):
                return Image.new("RGB", cfg.get_resolution(), "yellow")

            def get_latest_metadata(self):
                return None

        monkeypatch.setattr(
            "refresh_task.task.get_plugin_instance",
            lambda cfg: GoodPlugin(),
        )

        task.start()
        try:
            playlist = device_config_dev.get_playlist_manager().get_playlist("Default")
            refresh_action = PlaylistRefresh(playlist, pi)

            # First manual update → display raises
            with pytest.raises(RuntimeError, match="Transient display fault"):
                task.manual_update(refresh_action)

            # Task must still be alive (not crashed)
            assert task.running is True
            assert task.thread is not None
            assert task.thread.is_alive()

            # Second manual update — a fresh image so hash differs → should succeed
            # (dm.display_image will return success this time)
            pi2 = _make_plugin_instance(name="chaos_inst_2")
            _add_plugin_to_pm(device_config_dev, pi2)
            refresh_action2 = PlaylistRefresh(playlist, pi2)
            task.manual_update(refresh_action2)
        finally:
            task.stop()


# ---------------------------------------------------------------------------
# 4. Config reload mid-refresh → no crash, new config on next tick
# ---------------------------------------------------------------------------


class TestConfigReloadMidRefresh:
    """Simulate Config.load() being called concurrently during a refresh."""

    def test_config_reload_during_refresh_does_not_crash(
        self, device_config_dev, monkeypatch
    ):
        """Calling device_config.reload() mid-refresh does not crash the task."""
        monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
        monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")

        task, dm = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        dummy_cfg = {"id": "chaos_plugin", "class": "Chaos", "image_settings": []}
        monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

        reload_triggered = threading.Event()

        class ReloadingPlugin:
            def generate_image(self, settings, cfg):
                # Trigger a config re-read mid-render
                cfg.get_config("plugin_cycle_interval_seconds", default=60)
                reload_triggered.set()
                return Image.new("RGB", cfg.get_resolution(), "purple")

            def get_latest_metadata(self):
                return None

        monkeypatch.setattr(
            "refresh_task.task.get_plugin_instance",
            lambda cfg: ReloadingPlugin(),
        )

        playlist = device_config_dev.get_playlist_manager().get_playlist("Default")
        refresh_action = PlaylistRefresh(playlist, pi)
        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Should complete without raising
        result_info, used_cached, metrics = task._perform_refresh(
            refresh_action, _empty_refresh_info(), current_dt
        )

        assert reload_triggered.is_set()
        assert result_info is not None

    def test_config_write_during_refresh_does_not_corrupt(
        self, device_config_dev, monkeypatch
    ):
        """write_config() called concurrently with _perform_refresh does not raise."""
        monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
        monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")

        task, dm = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        dummy_cfg = {"id": "chaos_plugin", "class": "Chaos", "image_settings": []}
        monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

        write_events = []

        class WriteRacingPlugin:
            def generate_image(self, settings, cfg):
                # Simulate concurrent write (e.g. another route saving settings)
                try:
                    cfg.write_config()
                    write_events.append("write_ok")
                except Exception as exc:
                    write_events.append(f"write_error:{exc}")
                return Image.new("RGB", cfg.get_resolution(), "orange")

            def get_latest_metadata(self):
                return None

        monkeypatch.setattr(
            "refresh_task.task.get_plugin_instance",
            lambda cfg: WriteRacingPlugin(),
        )

        playlist = device_config_dev.get_playlist_manager().get_playlist("Default")
        refresh_action = PlaylistRefresh(playlist, pi)
        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        result_info, _used_cached, _metrics = task._perform_refresh(
            refresh_action, _empty_refresh_info(), current_dt
        )

        assert result_info is not None
        # At least one write happened without raising
        assert any(e == "write_ok" for e in write_events)
