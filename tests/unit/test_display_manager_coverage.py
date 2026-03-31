# pyright: reportMissingImports=false
"""Tests for display/display_manager.py — additional coverage."""
import os

from PIL import Image


def test_display_image_hash_skip(device_config_dev):
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)
    img = Image.new("RGB", (800, 480), "red")

    # First call should display
    dm.display_image(img)
    assert dm._last_image_hash is not None

    # Second call with same image should be skipped (no crash, no second write)
    first_hash = dm._last_image_hash
    dm.display_image(img)
    assert dm._last_image_hash == first_hash


def test_display_image_hash_different(device_config_dev):
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)
    img1 = Image.new("RGB", (800, 480), "red")
    img2 = Image.new("RGB", (800, 480), "blue")

    dm.display_image(img1)
    hash1 = dm._last_image_hash

    dm.display_image(img2)
    hash2 = dm._last_image_hash

    assert hash1 != hash2


def test_display_image_inverted(device_config_dev):
    from display.display_manager import DisplayManager

    device_config_dev.update_value("inverted_image", True)
    dm = DisplayManager(device_config_dev)
    img = Image.new("RGB", (800, 480), "green")

    # Should not crash — inverted path applies 180° rotation
    dm.display_image(img)
    assert dm._last_image_hash is not None


def test_display_image_save_failure_graceful(device_config_dev, monkeypatch):
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)
    img = Image.new("RGB", (800, 480), "red")

    # Make save fail by pointing to an invalid path
    monkeypatch.setattr(
        device_config_dev, "current_image_file", "/nonexistent/dir/img.png"
    )

    # Should not raise — save failure is caught gracefully
    dm.display_image(img)


def test_display_preprocessed_image(device_config_dev, tmp_path):
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)

    # Create a preprocessed image file
    img_path = tmp_path / "preprocessed.png"
    Image.new("RGB", (800, 480), "cyan").save(str(img_path))

    dm.display_preprocessed_image(str(img_path))

    # Both current and processed files should exist
    assert os.path.exists(device_config_dev.current_image_file)
    assert os.path.exists(device_config_dev.processed_image_file)
