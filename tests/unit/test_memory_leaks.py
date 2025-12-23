"""Memory leak detection tests for long-running plugin execution.

These tests verify that plugins and core components don't leak memory
during extended operation, which is critical for device reliability.
"""

import gc
import os
import time
import tracemalloc
from io import BytesIO

import psutil
import pytest
from PIL import Image

from display.display_manager import DisplayManager
from plugins.plugin_registry import get_plugin_instance
from refresh_task import RefreshTask, ManualRefresh
from utils.image_utils import (
    apply_image_enhancement,
    load_image_from_bytes,
    resize_image,
)


@pytest.fixture
def memory_baseline():
    """Establish a memory baseline before each test."""
    # Force garbage collection
    gc.collect()
    gc.collect()  # Double collect to ensure cleanup

    process = psutil.Process(os.getpid())
    baseline = process.memory_info().rss / 1024 / 1024  # MB

    yield baseline

    # Cleanup after test
    gc.collect()
    gc.collect()


def test_image_resize_no_memory_leak(memory_baseline):
    """Test that repeated image resizing doesn't leak memory."""
    # Create a test image
    test_img = Image.new("RGB", (800, 600), color=(100, 150, 200))

    # Perform many resize operations
    num_iterations = 100
    for i in range(num_iterations):
        resized = resize_image(test_img, (400, 300))
        # Explicitly delete to help GC
        del resized

    # Force garbage collection
    gc.collect()
    time.sleep(0.1)

    process = psutil.Process(os.getpid())
    final_memory = process.memory_info().rss / 1024 / 1024
    memory_growth = final_memory - memory_baseline

    # Allow for some variation but catch significant leaks
    # Each resize of 400x300 RGB is ~0.35MB, so 100 retained would be 35MB
    assert memory_growth < 10, f"Memory grew by {memory_growth:.2f}MB (potential leak)"


def test_image_enhancement_no_memory_leak(memory_baseline):
    """Test that repeated image enhancement doesn't leak memory."""
    test_img = Image.new("RGB", (400, 300), color=(128, 128, 128))

    settings = {
        "brightness": 1.2,
        "contrast": 1.1,
        "saturation": 1.0,
        "sharpness": 1.1,
    }

    num_iterations = 100
    for i in range(num_iterations):
        enhanced = apply_image_enhancement(test_img, settings)
        del enhanced

    gc.collect()
    time.sleep(0.1)

    process = psutil.Process(os.getpid())
    final_memory = process.memory_info().rss / 1024 / 1024
    memory_growth = final_memory - memory_baseline

    assert memory_growth < 10, f"Memory grew by {memory_growth:.2f}MB (potential leak)"


def test_image_load_from_bytes_no_memory_leak(memory_baseline):
    """Test that repeatedly loading images from bytes doesn't leak memory."""
    # Create test image bytes
    bio = BytesIO()
    Image.new("RGB", (200, 200), color=(50, 100, 150)).save(bio, format="PNG")
    img_bytes = bio.getvalue()

    num_iterations = 100
    for i in range(num_iterations):
        loaded = load_image_from_bytes(img_bytes)
        if loaded:
            del loaded

    gc.collect()
    time.sleep(0.1)

    process = psutil.Process(os.getpid())
    final_memory = process.memory_info().rss / 1024 / 1024
    memory_growth = final_memory - memory_baseline

    assert memory_growth < 10, f"Memory grew by {memory_growth:.2f}MB (potential leak)"


def test_plugin_execution_no_memory_leak(device_config_dev, monkeypatch, memory_baseline):
    """Test that repeated plugin execution doesn't leak memory."""

    class SimplePlugin:
        config = {"image_settings": []}

        def generate_image(self, settings, device_config):
            # Simulate typical plugin work: create an image, do some processing
            img = Image.new("RGB", device_config.get_resolution(), color=(255, 255, 255))
            # Simulate some processing
            img = img.rotate(45)
            img = img.crop((0, 0, 100, 100))
            return img.resize(device_config.get_resolution())

    simple_plugin = SimplePlugin()
    dummy_cfg = {"id": "simple", "class": "Simple"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: simple_plugin, raising=True
    )

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    try:
        task.start()

        # Execute many plugin updates
        num_iterations = 50
        for i in range(num_iterations):
            refresh = ManualRefresh("simple", {})
            task.manual_update(refresh)
            # Small delay to avoid overwhelming the system
            time.sleep(0.01)

        # Wait for all to complete
        time.sleep(0.5)

        # Force garbage collection
        gc.collect()
        time.sleep(0.1)

        process = psutil.Process(os.getpid())
        final_memory = process.memory_info().rss / 1024 / 1024
        memory_growth = final_memory - memory_baseline

        # Be generous here as plugin execution involves display manager,
        # file I/O, and other components
        assert memory_growth < 30, f"Memory grew by {memory_growth:.2f}MB (potential leak)"

    finally:
        task.stop()


def test_display_manager_no_memory_leak(device_config_dev, memory_baseline):
    """Test that repeated display_image calls don't leak memory."""
    dm = DisplayManager(device_config_dev)

    num_iterations = 50
    for i in range(num_iterations):
        img = Image.new("RGB", (400, 300), color=(i % 256, 100, 150))
        dm.display_image(img)
        del img

    gc.collect()
    time.sleep(0.1)

    process = psutil.Process(os.getpid())
    final_memory = process.memory_info().rss / 1024 / 1024
    memory_growth = final_memory - memory_baseline

    # Display manager saves files, so allow for some caching
    assert memory_growth < 20, f"Memory grew by {memory_growth:.2f}MB (potential leak)"


def test_tracemalloc_image_processing():
    """Use tracemalloc to detect memory allocation patterns in image processing."""
    tracemalloc.start()

    # Baseline
    snapshot1 = tracemalloc.take_snapshot()

    # Perform image operations
    for i in range(50):
        img = Image.new("RGB", (400, 300), color=(128, 128, 128))
        resized = resize_image(img, (200, 150))
        enhanced = apply_image_enhancement(
            resized, {"brightness": 1.1, "contrast": 1.0, "saturation": 1.0, "sharpness": 1.0}
        )
        del img, resized, enhanced

    gc.collect()

    snapshot2 = tracemalloc.take_snapshot()
    top_stats = snapshot2.compare_to(snapshot1, 'lineno')

    # Find the largest memory allocations
    largest_growth = 0
    for stat in top_stats[:10]:
        if stat.size_diff > largest_growth:
            largest_growth = stat.size_diff

    tracemalloc.stop()

    # Largest allocation shouldn't be more than 5MB
    largest_growth_mb = largest_growth / 1024 / 1024
    assert largest_growth_mb < 5, (
        f"Largest memory allocation was {largest_growth_mb:.2f}MB (potential leak)"
    )


def test_long_running_refresh_task(device_config_dev, monkeypatch):
    """Test refresh task over an extended period to detect slow leaks."""

    class CyclingPlugin:
        """Plugin that creates and discards various objects."""
        config = {"image_settings": []}
        call_count = 0

        def generate_image(self, settings, device_config):
            self.call_count += 1
            # Create temporary objects
            temp_img = Image.new("RGB", (100, 100), color=(self.call_count % 256, 128, 200))
            temp_list = list(range(1000))  # Some temp data
            temp_dict = {f"key{i}": f"value{i}" for i in range(100)}

            # Return final image
            return Image.new("RGB", device_config.get_resolution(), color=(255, 255, 255))

    cycling_plugin = CyclingPlugin()
    dummy_cfg = {"id": "cycling", "class": "Cycling"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance", lambda cfg: cycling_plugin, raising=True
    )

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    try:
        task.start()

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024

        # Run for a bit longer to detect slow leaks
        num_iterations = 30
        for i in range(num_iterations):
            refresh = ManualRefresh("cycling", {})
            task.manual_update(refresh)
            time.sleep(0.02)

        time.sleep(0.5)
        gc.collect()

        final_memory = process.memory_info().rss / 1024 / 1024
        memory_growth = final_memory - initial_memory

        # With 30 iterations of complex plugin work, allow for reasonable growth
        assert memory_growth < 25, (
            f"Memory grew by {memory_growth:.2f}MB over {num_iterations} iterations "
            f"(potential slow leak)"
        )

    finally:
        task.stop()


def test_repeated_plugin_instantiation_no_leak(device_config_dev):
    """Test that creating and destroying plugin instances doesn't leak."""
    tracemalloc.start()

    # Baseline
    gc.collect()
    snapshot1 = tracemalloc.take_snapshot()

    # Create and destroy plugin instances (if we had a real plugin)
    # For now, test the pattern with mock objects
    for i in range(100):
        class TempPlugin:
            config = {"id": f"temp_{i}", "image_settings": []}

            def generate_image(self, settings, device_config):
                return Image.new("RGB", (100, 100), color=(128, 128, 128))

        plugin = TempPlugin()
        _ = plugin.generate_image({}, device_config_dev)
        del plugin

    gc.collect()
    snapshot2 = tracemalloc.take_snapshot()

    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
    largest_growth = max((stat.size_diff for stat in top_stats[:10]), default=0)
    largest_growth_mb = largest_growth / 1024 / 1024

    tracemalloc.stop()

    assert largest_growth_mb < 3, (
        f"Largest memory allocation was {largest_growth_mb:.2f}MB (potential leak)"
    )


def test_image_history_doesnt_accumulate_in_memory(device_config_dev):
    """Test that saving history images doesn't accumulate in memory."""
    dm = DisplayManager(device_config_dev)

    process = psutil.Process(os.getpid())
    initial_memory = process.memory_info().rss / 1024 / 1024

    # Create many history entries
    for i in range(30):
        img = Image.new("RGB", (400, 300), color=((i * 10) % 256, 128, 200))
        # This saves to history
        dm.display_image(img)
        del img

    gc.collect()
    time.sleep(0.1)

    final_memory = process.memory_info().rss / 1024 / 1024
    memory_growth = final_memory - initial_memory

    # History is saved to disk, not kept in memory
    # Allow some growth for file handles and metadata
    assert memory_growth < 15, f"Memory grew by {memory_growth:.2f}MB (potential leak)"
