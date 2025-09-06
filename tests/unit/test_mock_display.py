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

