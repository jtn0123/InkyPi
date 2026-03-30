"""Stress tests for RefreshTask to verify behavior under rapid updates and concurrency.

These tests ensure the refresh task handles high-frequency updates, concurrent
requests, and edge cases without deadlocks or race conditions.
"""

import os
import threading
import time

import psutil
import pytest
from PIL import Image

from display.display_manager import DisplayManager
from refresh_task import ManualRefresh, RefreshTask


def wait_until(predicate, timeout=1.0, interval=0.01):
    """Poll until a condition becomes true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def mock_plugin():
    """Create a mock plugin that returns images quickly."""

    class FastPlugin:
        config = {"image_settings": []}
        call_count = 0

        def generate_image(self, settings, device_config):
            self.call_count += 1
            # Simulate very fast image generation
            return Image.new("RGB", device_config.get_resolution(), "white")

    return FastPlugin()


@pytest.fixture
def refresh_task(device_config_dev):
    """Create a RefreshTask instance for testing."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    yield task
    # Cleanup
    if task.running:
        task.stop()


def test_rapid_manual_updates(device_config_dev, mock_plugin, monkeypatch):
    """Test handling of many manual updates in quick succession."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    # Stub plugin retrieval
    dummy_cfg = {"id": "test", "class": "Test"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: mock_plugin, raising=True
    )

    try:
        task.start()

        # Send 20 rapid manual updates
        num_updates = 20
        for _i in range(num_updates):
            refresh = ManualRefresh("test", {})
            task.manual_update(refresh)

        # Verify the task is still running and responsive
        assert task.running
        assert task.thread.is_alive()

    finally:
        task.stop()


def test_concurrent_manual_updates_from_multiple_threads(
    device_config_dev, mock_plugin, monkeypatch
):
    """Test concurrent manual update requests from multiple threads."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    dummy_cfg = {"id": "test", "class": "Test"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: mock_plugin, raising=True
    )

    try:
        task.start()

        # Track completion
        completed = []
        errors = []

        def send_update(thread_id):
            try:
                for _i in range(5):
                    refresh = ManualRefresh("test", {})
                    task.manual_update(refresh)
                completed.append(thread_id)
            except Exception as e:
                errors.append((thread_id, e))

        # Spawn 10 threads, each sending 5 updates
        threads = []
        for i in range(10):
            t = threading.Thread(target=send_update, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join(timeout=2)

        # Verify no errors and all threads completed
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(completed) == 10

    finally:
        task.stop()


def test_start_stop_cycles(device_config_dev):
    """Test rapid start/stop cycles don't cause issues."""
    dm = DisplayManager(device_config_dev)

    for _i in range(10):
        task = RefreshTask(device_config_dev, dm)
        task.start()
        assert task.running
        assert task.thread.is_alive()

        task.stop()
        assert not task.running


def test_stop_while_refresh_in_progress(device_config_dev, monkeypatch):
    """Test stopping the task while a refresh is in progress."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    slow_plugin_started = threading.Event()
    slow_plugin_can_finish = threading.Event()

    def fake_perform(refresh_action, latest_refresh, current_dt, request_id=None):
        slow_plugin_started.set()
        slow_plugin_can_finish.wait(timeout=2)
        return (
            {
                "refresh_type": "Manual Update",
                "plugin_id": "slow",
                "refresh_time": current_dt.isoformat(),
                "image_hash": "hash",
            },
            False,
            {"request_ms": 1},
        )

    monkeypatch.setattr(task, "_perform_refresh", fake_perform, raising=True)

    try:
        task.start()

        # Trigger a manual update
        refresh_thread = threading.Thread(
            target=lambda: task.manual_update(ManualRefresh("slow", {}))
        )
        refresh_thread.start()

        # Wait for the slow plugin to start
        assert slow_plugin_started.wait(timeout=1), "Plugin didn't start"

        stop_thread = threading.Thread(target=task.stop)
        stop_thread.start()
        assert wait_until(stop_thread.is_alive, timeout=0.2), "Stop did not start"

        # Allow plugin to finish
        slow_plugin_can_finish.set()
        assert wait_until(
            lambda: not stop_thread.is_alive(), timeout=2
        ), "Stop should finish promptly once the refresh is released"
        refresh_thread.join(timeout=1)

        # Verify task stopped
        assert not stop_thread.is_alive()
        assert not task.running

    finally:
        slow_plugin_can_finish.set()
        if task.running:
            task.stop()


def test_manual_update_queue_ordering(device_config_dev, monkeypatch):
    """Test that manual updates are processed in order."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    processed_order = []
    monkeypatch.setattr(
        task,
        "_perform_refresh",
        lambda refresh_action, latest_refresh, current_dt, request_id=None: (
            processed_order.append(refresh_action.get_plugin_id())
            or (
                {
                    "refresh_type": "Manual Update",
                    "plugin_id": refresh_action.get_plugin_id(),
                    "refresh_time": current_dt.isoformat(),
                    "image_hash": refresh_action.get_plugin_id(),
                },
                False,
                {"request_ms": 1},
            )
        ),
        raising=True,
    )

    try:
        task.start()

        # Queue multiple manual updates
        expected_order = []
        for i in range(5):
            plugin_id = f"plugin{i}"
            expected_order.append(plugin_id)
            refresh = ManualRefresh(plugin_id, {})
            task.manual_update(refresh)

        assert processed_order == expected_order

    finally:
        task.stop()


def test_exception_during_refresh_does_not_crash_task(device_config_dev, monkeypatch):
    """Test that exceptions during refresh are captured and re-raised but don't crash the background thread."""
    monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    calls = {"count": 0}

    def fake_perform(refresh_action, latest_refresh, current_dt, request_id=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("Simulated plugin failure")
        return (
            {
                "refresh_type": "Manual Update",
                "plugin_id": refresh_action.get_plugin_id(),
                "refresh_time": current_dt.isoformat(),
                "image_hash": "hash",
            },
            False,
            {"request_ms": 1},
        )

    monkeypatch.setattr(task, "_perform_refresh", fake_perform, raising=True)

    try:
        task.start()

        # First update should fail and raise exception
        refresh1 = ManualRefresh("failing", {})
        with pytest.raises(RuntimeError, match="Simulated plugin failure"):
            task.manual_update(refresh1)

        # Task should still be running despite the exception
        assert task.running
        assert task.thread.is_alive()

        # Second update should succeed
        refresh2 = ManualRefresh("failing", {})
        metrics = task.manual_update(refresh2)
        assert metrics is not None

        # Verify both calls were made
        assert calls["count"] == 2

    finally:
        task.stop()


def test_manual_update_returns_metrics_after_update(
    device_config_dev, mock_plugin, monkeypatch
):
    """Test that manual updates return per-request metrics."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    dummy_cfg = {"id": "test", "class": "Test"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: mock_plugin, raising=True
    )

    try:
        task.start()

        refresh = ManualRefresh("test", {})
        metrics = task.manual_update(refresh)
        assert isinstance(metrics, dict)
        assert "request_ms" in metrics

    finally:
        task.stop()


def test_high_frequency_updates_dont_deadlock(
    device_config_dev, mock_plugin, monkeypatch
):
    """Test that very high frequency updates don't cause deadlocks."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    dummy_cfg = {"id": "test", "class": "Test"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: mock_plugin, raising=True
    )

    try:
        task.start()

        # Hammer the task with updates as fast as possible
        for _i in range(100):
            refresh = ManualRefresh("test", {})
            task.manual_update(refresh)

        # Task should still be responsive
        assert task.running
        assert task.thread.is_alive()

        # Should be able to stop cleanly
        task.stop()
        assert not task.running

    finally:
        if task.running:
            task.stop()


def test_memory_not_growing_with_many_updates(
    device_config_dev, mock_plugin, monkeypatch
):
    """Test that memory doesn't grow excessively with many updates."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    dummy_cfg = {"id": "test", "class": "Test"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: mock_plugin, raising=True
    )

    try:
        task.start()

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Send many updates
        for _i in range(50):
            refresh = ManualRefresh("test", {})
            task.manual_update(refresh)

        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_growth = final_memory - initial_memory

        # Memory shouldn't grow by more than 50MB (generous threshold)
        assert (
            memory_growth < 50
        ), f"Memory grew by {memory_growth:.2f}MB, which may indicate a leak"

    finally:
        task.stop()
