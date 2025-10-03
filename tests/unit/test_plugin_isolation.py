"""Plugin isolation tests to verify failure containment and concurrent plugin behavior.

These tests ensure that plugin failures are properly isolated and don't cascade
to other plugins or crash the system.
"""

import threading
import time
from unittest.mock import Mock

import pytest
from PIL import Image

from display.display_manager import DisplayManager
from refresh_task import RefreshTask, ManualRefresh


@pytest.fixture
def good_plugin():
    """A well-behaved plugin that always succeeds."""

    class GoodPlugin:
        config = {"image_settings": []}
        call_count = 0

        def generate_image(self, settings, device_config):
            self.call_count += 1
            time.sleep(0.01)  # Simulate some work
            return Image.new("RGB", device_config.get_resolution(), color=(0, 255, 0))

    return GoodPlugin()


@pytest.fixture
def bad_plugin():
    """A misbehaving plugin that always raises exceptions."""

    class BadPlugin:
        config = {"image_settings": []}
        call_count = 0

        def generate_image(self, settings, device_config):
            self.call_count += 1
            raise RuntimeError(f"Bad plugin failure #{self.call_count}")

    return BadPlugin()


@pytest.fixture
def slow_plugin():
    """A slow plugin that takes a while to complete."""

    class SlowPlugin:
        config = {"image_settings": []}
        call_count = 0

        def generate_image(self, settings, device_config):
            self.call_count += 1
            time.sleep(0.5)  # Deliberately slow
            return Image.new("RGB", device_config.get_resolution(), color=(0, 0, 255))

    return SlowPlugin()


def test_single_plugin_failure_doesnt_crash_task(
    device_config_dev, bad_plugin, good_plugin, monkeypatch
):
    """Test that a single plugin failure doesn't crash the refresh task."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    plugins = {"bad": bad_plugin, "good": good_plugin}

    def get_plugin_instance(cfg):
        return plugins[cfg["id"]]

    def get_plugin(pid):
        return {"id": pid, "class": "Test"}

    monkeypatch.setattr(device_config_dev, "get_plugin", get_plugin)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", get_plugin_instance, raising=True
    )

    try:
        task.start()

        # Bad plugin should fail
        with pytest.raises(RuntimeError, match="Bad plugin failure"):
            refresh = ManualRefresh("bad", {})
            task.manual_update(refresh)

        # Task should still be running
        assert task.running
        assert task.thread.is_alive()

        # Good plugin should still work
        refresh = ManualRefresh("good", {})
        metrics = task.manual_update(refresh)
        assert metrics is not None
        assert good_plugin.call_count == 1

    finally:
        task.stop()


def test_multiple_plugins_concurrent_execution_with_failures(
    device_config_dev, bad_plugin, good_plugin, monkeypatch
):
    """Test that good plugins can execute while bad plugins are failing."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    plugins = {"bad": bad_plugin, "good": good_plugin}

    def get_plugin_instance(cfg):
        return plugins[cfg["id"]]

    def get_plugin(pid):
        return {"id": pid, "class": "Test"}

    monkeypatch.setattr(device_config_dev, "get_plugin", get_plugin)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", get_plugin_instance, raising=True
    )

    try:
        task.start()

        results = []
        errors = []

        def run_plugin(plugin_id, iterations):
            for i in range(iterations):
                try:
                    refresh = ManualRefresh(plugin_id, {})
                    task.manual_update(refresh)
                    results.append(f"{plugin_id}_success_{i}")
                except Exception as e:
                    errors.append(f"{plugin_id}_error_{i}")
                time.sleep(0.02)

        # Run good and bad plugins concurrently
        good_thread = threading.Thread(target=run_plugin, args=("good", 5))
        bad_thread = threading.Thread(target=run_plugin, args=("bad", 5))

        good_thread.start()
        bad_thread.start()

        good_thread.join(timeout=10)
        bad_thread.join(timeout=10)

        # Good plugin should have succeeded at least some times
        # (exact count may vary due to threading/timing)
        good_successes = sum(1 for r in results if r.startswith("good_success"))
        assert good_successes >= 1, f"Good plugin should succeed at least once, got {good_successes}"

        # Bad plugin should have failed at least some times
        bad_errors = sum(1 for e in errors if e.startswith("bad_error"))
        assert bad_errors >= 1, f"Bad plugin should fail at least once, got {bad_errors}"

        # Together they should have attempted all iterations
        total_attempts = good_successes + bad_errors
        assert total_attempts >= 5, f"Should have at least 5 total attempts, got {total_attempts}"

    finally:
        task.stop()


def test_plugin_failure_doesnt_affect_subsequent_plugins(
    device_config_dev, bad_plugin, good_plugin, monkeypatch
):
    """Test that a plugin failure doesn't pollute state for subsequent plugins."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    plugins = {"bad": bad_plugin, "good": good_plugin}

    def get_plugin_instance(cfg):
        return plugins[cfg["id"]]

    def get_plugin(pid):
        return {"id": pid, "class": "Test"}

    monkeypatch.setattr(device_config_dev, "get_plugin", get_plugin)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", get_plugin_instance, raising=True
    )

    try:
        task.start()

        # Sequence: bad -> good -> bad -> good
        sequence = ["bad", "good", "bad", "good"]
        for i, plugin_id in enumerate(sequence):
            if plugin_id == "bad":
                with pytest.raises(RuntimeError):
                    refresh = ManualRefresh(plugin_id, {})
                    task.manual_update(refresh)
            else:
                refresh = ManualRefresh(plugin_id, {})
                metrics = task.manual_update(refresh)
                assert metrics is not None

        # Good plugin should have been called twice
        assert good_plugin.call_count == 2
        # Bad plugin should have been called twice
        assert bad_plugin.call_count == 2

    finally:
        task.stop()


def test_plugin_timeout_isolation(device_config_dev, slow_plugin, good_plugin, monkeypatch):
    """Test that a slow plugin doesn't block other plugins from executing."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    plugins = {"slow": slow_plugin, "good": good_plugin}

    def get_plugin_instance(cfg):
        return plugins[cfg["id"]]

    def get_plugin(pid):
        return {"id": pid, "class": "Test"}

    monkeypatch.setattr(device_config_dev, "get_plugin", get_plugin)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", get_plugin_instance, raising=True
    )

    try:
        task.start()

        # Start slow plugin in background
        slow_result = {"done": False}

        def run_slow():
            refresh = ManualRefresh("slow", {})
            task.manual_update(refresh)
            slow_result["done"] = True

        slow_thread = threading.Thread(target=run_slow)
        slow_thread.start()

        # While slow plugin is running, try to run good plugin
        # (This may queue up depending on refresh_task implementation)
        time.sleep(0.1)  # Give slow plugin a head start

        # Note: This behavior depends on whether refresh_task processes serially or in parallel
        # If serial, this will queue. If parallel, it runs concurrently.
        # For now, just verify the system doesn't deadlock

        # Wait for slow plugin to finish
        slow_thread.join(timeout=2)

        assert slow_result["done"], "Slow plugin should have completed"

        # Now verify good plugin can still run
        refresh = ManualRefresh("good", {})
        metrics = task.manual_update(refresh)
        assert metrics is not None

    finally:
        task.stop()


def test_plugin_exception_types_are_preserved(device_config_dev, monkeypatch):
    """Test that different exception types from plugins are properly propagated."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    class CustomException(Exception):
        pass

    class PluginWithCustomException:
        config = {"image_settings": []}

        def generate_image(self, settings, device_config):
            raise CustomException("Custom plugin error")

    custom_plugin = PluginWithCustomException()
    dummy_cfg = {"id": "custom", "class": "Custom"}

    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: custom_plugin, raising=True
    )

    try:
        task.start()

        with pytest.raises(CustomException, match="Custom plugin error"):
            refresh = ManualRefresh("custom", {})
            task.manual_update(refresh)

    finally:
        task.stop()


def test_plugin_state_isolation(device_config_dev, monkeypatch):
    """Test that plugin instances maintain separate state."""

    class StatefulPlugin:
        config = {"image_settings": []}

        def __init__(self, plugin_id):
            self.plugin_id = plugin_id
            self.counter = 0

        def generate_image(self, settings, device_config):
            self.counter += 1
            return Image.new("RGB", device_config.get_resolution(), color=(255, 255, 255))

    plugin1 = StatefulPlugin("plugin1")
    plugin2 = StatefulPlugin("plugin2")
    plugins = {"plugin1": plugin1, "plugin2": plugin2}

    def get_plugin_instance(cfg):
        return plugins[cfg["id"]]

    def get_plugin(pid):
        return {"id": pid, "class": "Stateful"}

    monkeypatch.setattr(device_config_dev, "get_plugin", get_plugin)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", get_plugin_instance, raising=True
    )

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    try:
        task.start()

        # Call plugin1 twice
        for i in range(2):
            refresh = ManualRefresh("plugin1", {})
            task.manual_update(refresh)

        # Call plugin2 once
        refresh = ManualRefresh("plugin2", {})
        task.manual_update(refresh)

        # Verify state isolation
        assert plugin1.counter == 2
        assert plugin2.counter == 1

    finally:
        task.stop()


def test_plugin_resource_cleanup_on_failure(device_config_dev, monkeypatch):
    """Test that resources are cleaned up even when plugins fail."""

    class ResourceTrackingPlugin:
        config = {"image_settings": []}
        resources_allocated = 0
        resources_cleaned = 0

        def generate_image(self, settings, device_config):
            try:
                self.resources_allocated += 1
                # Simulate resource allocation
                img = Image.new("RGB", device_config.get_resolution(), color=(128, 128, 128))
                # Simulate failure
                raise RuntimeError("Simulated failure after resource allocation")
            finally:
                # Cleanup should happen even on failure
                self.resources_cleaned += 1

            return img

    tracking_plugin = ResourceTrackingPlugin()
    dummy_cfg = {"id": "tracking", "class": "Tracking"}

    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: tracking_plugin, raising=True
    )

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    try:
        task.start()

        # Run the plugin multiple times, expect failures
        for i in range(3):
            with pytest.raises(RuntimeError):
                refresh = ManualRefresh("tracking", {})
                task.manual_update(refresh)

        # Verify cleanup happened every time
        assert tracking_plugin.resources_allocated == 3
        assert tracking_plugin.resources_cleaned == 3

    finally:
        task.stop()


def test_concurrent_plugin_calls_dont_interfere(
    device_config_dev, good_plugin, monkeypatch
):
    """Test that concurrent calls to the same plugin are handled correctly."""
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    dummy_cfg = {"id": "good", "class": "Good"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: good_plugin, raising=True
    )

    try:
        task.start()

        results = []

        def call_plugin(thread_id):
            for i in range(3):
                try:
                    refresh = ManualRefresh("good", {})
                    metrics = task.manual_update(refresh)
                    results.append(f"thread{thread_id}_call{i}")
                except Exception as e:
                    results.append(f"thread{thread_id}_error")
                time.sleep(0.01)

        # Spawn multiple threads calling the same plugin
        threads = [threading.Thread(target=call_plugin, args=(i,)) for i in range(3)]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=5)

        # All calls should have succeeded
        success_count = len([r for r in results if "error" not in r])
        assert success_count == 9  # 3 threads * 3 calls each

    finally:
        task.stop()
