from PIL import Image
import os


def test_mock_display_writes_latest_and_timestamp(monkeypatch, device_config_dev, tmp_path):
    device_config_dev.update_value("display_type", "mock")
    device_config_dev.update_value("output_dir", str(tmp_path / "mock_output"))
    os.makedirs(str(tmp_path / "mock_output"), exist_ok=True)

    from display.display_manager import DisplayManager
    dm = DisplayManager(device_config_dev)

    img = Image.new("RGB", (100, 50), "white")
    dm.display_image(img)

    # latest.png exists
    latest = tmp_path / "mock_output" / "latest.png"
    assert latest.exists()

    # at least one timestamped file created
    files = list((tmp_path / "mock_output").glob("display_*.png"))
    assert len(files) >= 1


def test_mock_display_initialize_display_logging(caplog, device_config_dev):
    """Test that mock display logs initialization message."""
    import logging
    caplog.set_level(logging.INFO)

    device_config_dev.update_value("display_type", "mock")
    device_config_dev.update_value("resolution", [200, 100])

    from display.mock_display import MockDisplay
    display = MockDisplay(device_config_dev)

    # Check that initialization logging occurred
    display.initialize_display()  # Explicitly call to trigger logging
    assert "Mock display initialized: 200x100" in caplog.text


def test_mock_display_display_image_with_none_image_settings(device_config_dev, tmp_path):
    """Test that mock display handles None image_settings parameter."""
    device_config_dev.update_value("display_type", "mock")
    device_config_dev.update_value("output_dir", str(tmp_path / "mock_output"))
    os.makedirs(str(tmp_path / "mock_output"), exist_ok=True)

    from display.mock_display import MockDisplay
    display = MockDisplay(device_config_dev)

    img = Image.new("RGB", (100, 50), "white")

    # Call display_image with None image_settings (should not crash)
    display.display_image(img, image_settings=None)

    # Verify files were created
    latest = tmp_path / "mock_output" / "latest.png"
    assert latest.exists()

