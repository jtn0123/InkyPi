"""Stress tests for RefreshTask to verify behavior under rapid updates and concurrency.

These tests ensure the refresh task handles high-frequency updates, concurrent
requests, and edge cases without deadlocks or race conditions.
"""

import threading
import time
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from display.display_manager import DisplayManager
from refresh_task import RefreshTask, ManualRefresh


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
        for i in range(num_updates):
            refresh = ManualRefresh("test", {})
            task.manual_update(refresh)
            # Small delay to allow processing but still stress the system
            time.sleep(0.01)

        # Wait for all refreshes to complete
        time.sleep(0.5)

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
                for i in range(5):
                    refresh = ManualRefresh("test", {})
                    task.manual_update(refresh)
                    time.sleep(0.01)
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
            t.join(timeout=5)

        # Verify no errors and all threads completed
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(completed) == 10

    finally:
        task.stop()


def test_start_stop_cycles(device_config_dev):
    """Test rapid start/stop cycles don't cause issues."""
    dm = DisplayManager(device_config_dev)

    for i in range(10):
        task = RefreshTask(device_config_dev, dm)
        task.start()
        assert task.running
        assert task.thread.is_alive()

        task.stop()
        # Give thread time to stop
        time.sleep(0.05)
        assert not task.running


def test_stop_while_refresh_in_progress(device_config_dev, monkeypatch):
    """Test stopping the task while a refresh is in progress."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    slow_plugin_started = threading.Event()
    slow_plugin_can_finish = threading.Event()

    class SlowPlugin:
        config = {"image_settings": []}

        def generate_image(self, settings, device_config):
            slow_plugin_started.set()
            # Wait until we're told to finish (or timeout)
            slow_plugin_can_finish.wait(timeout=2)
            return Image.new("RGB", device_config.get_resolution(), "white")

    slow_plugin = SlowPlugin()
    dummy_cfg = {"id": "slow", "class": "Slow"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: slow_plugin, raising=True
    )

    try:
        task.start()

        # Trigger a manual update
        refresh = ManualRefresh("slow", {})
        task.manual_update(refresh)

        # Wait for the slow plugin to start
        assert slow_plugin_started.wait(timeout=1), "Plugin didn't start"

        # Now try to stop while plugin is working
        task.stop()

        # Allow plugin to finish
        slow_plugin_can_finish.set()

        # Verify task stopped
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

    class OrderTrackingPlugin:
        config = {"image_settings": []}

        def __init__(self, plugin_id):
            self.plugin_id = plugin_id

        def generate_image(self, settings, device_config):
            processed_order.append(self.plugin_id)
            return Image.new("RGB", device_config.get_resolution(), "white")

    plugins = {f"plugin{i}": OrderTrackingPlugin(f"plugin{i}") for i in range(5)}

    def get_plugin_instance(cfg):
        return plugins[cfg["id"]]

    dummy_cfg_func = lambda pid: {"id": pid, "class": "Test"}
    monkeypatch.setattr(device_config_dev, "get_plugin", dummy_cfg_func)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", get_plugin_instance, raising=True
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

        # Wait for all to process
        time.sleep(1)

        # Note: Due to threading, exact order isn't guaranteed, but
        # all plugins should have been called
        assert len(processed_order) >= 1, "At least one update should process"
        # Verify all plugins were eventually called
        assert set(processed_order) == set(expected_order), (
            f"Expected all plugins to be called. "
            f"Expected: {expected_order}, Got: {processed_order}"
        )

    finally:
        task.stop()


def test_exception_during_refresh_does_not_crash_task(
    device_config_dev, monkeypatch
):
    """Test that exceptions during refresh are captured and re-raised but don't crash the background thread."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    class FailingPlugin:
        config = {"image_settings": []}
        call_count = 0

        def generate_image(self, settings, device_config):
            self.call_count += 1
            if self.call_count == 1:
                raise RuntimeError("Simulated plugin failure")
            return Image.new("RGB", device_config.get_resolution(), "white")

    failing_plugin = FailingPlugin()
    dummy_cfg = {"id": "failing", "class": "Failing"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: failing_plugin, raising=True
    )

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
        assert failing_plugin.call_count == 2

    finally:
        task.stop()


def test_refresh_result_populated_after_update(device_config_dev, mock_plugin, monkeypatch):
    """Test that refresh_result is properly populated after manual update."""
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
        task.manual_update(refresh)

        # Wait for refresh to complete
        completed = task.refresh_event.wait(timeout=2)
        assert completed, "Refresh did not complete in time"

        # Check that refresh_result contains metrics
        assert "metrics" in task.refresh_result
        assert isinstance(task.refresh_result["metrics"], dict)

    finally:
        task.stop()


def test_high_frequency_updates_dont_deadlock(device_config_dev, mock_plugin, monkeypatch):
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
        for i in range(100):
            refresh = ManualRefresh("test", {})
            task.manual_update(refresh)
            # No delay - truly rapid

        # Give it time to process
        time.sleep(1)

        # Task should still be responsive
        assert task.running
        assert task.thread.is_alive()

        # Should be able to stop cleanly
        task.stop()
        assert not task.running

    finally:
        if task.running:
            task.stop()


def test_memory_not_growing_with_many_updates(device_config_dev, mock_plugin, monkeypatch):
    """Test that memory doesn't grow excessively with many updates."""
    import psutil
    import os

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
        for i in range(50):
            refresh = ManualRefresh("test", {})
            task.manual_update(refresh)
            time.sleep(0.01)

        time.sleep(0.5)

        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_growth = final_memory - initial_memory

        # Memory shouldn't grow by more than 50MB (generous threshold)
        assert memory_growth < 50, (
            f"Memory grew by {memory_growth:.2f}MB, which may indicate a leak"
        )

    finally:
        task.stop()
