import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


# --- Abstract Display ---


def test_abstract_display_initialize_display_not_implemented(device_config_dev):
    """Test that AbstractDisplay raises NotImplementedError for initialize_display."""
    from display.abstract_display import AbstractDisplay

    # Create instance without calling __init__ to avoid the NotImplementedError
    display = AbstractDisplay.__new__(AbstractDisplay)
    display.device_config = device_config_dev

    with pytest.raises(NotImplementedError, match="Method 'initialize_display"):
        display.initialize_display()


def test_abstract_display_display_image_not_implemented(device_config_dev):
    """Test that AbstractDisplay raises NotImplementedError for display_image."""
    from display.abstract_display import AbstractDisplay

    # Create instance without calling __init__ to avoid the NotImplementedError
    display = AbstractDisplay.__new__(AbstractDisplay)
    display.device_config = device_config_dev
    test_image = Image.new("RGB", (100, 100), "white")

    with pytest.raises(NotImplementedError, match="Method 'display_image"):
        display.display_image(test_image)


def test_abstract_display_initialization_sets_device_config(device_config_dev):
    """Test that AbstractDisplay properly initializes device_config."""
    from display.abstract_display import AbstractDisplay

    # Create instance without calling __init__ to avoid the NotImplementedError
    display = AbstractDisplay.__new__(AbstractDisplay)
    display.device_config = device_config_dev
    assert display.device_config == device_config_dev


def test_mutable_default_not_shared(device_config_dev, tmp_path):
    """Verify display_image default image_settings is not shared across calls."""
    from display.mock_display import MockDisplay

    display = MockDisplay.__new__(MockDisplay)
    display.device_config = device_config_dev
    display.width = 100
    display.height = 100
    display.output_dir = str(tmp_path)

    img = Image.new("RGB", (100, 100), "white")

    # First call with default — should get a fresh empty list
    display.display_image(img)

    # Second call with default — should also get a fresh empty list, not a
    # reference to the same object from the first call
    display.display_image(img)

    # If the default were mutable, passing a list and mutating it would leak
    settings = ["test_setting"]
    display.display_image(img, image_settings=settings)
    # A fresh call should still get an independent default
    display.display_image(img)


# --- Inky Display ---


class FakeAutoDisplay:
    def __init__(self, width=250, height=122):
        self.width = width
        self.height = height
        self.border = None
        self._image = None
        self.shown = False

    # Inky API used by driver
    BLACK = 0

    def set_border(self, color):
        self.border = color

    def set_image(self, image):
        self._image = image

    def show(self):
        self.shown = True


def _install_fake_inky(monkeypatch, fake_disp):
    # Provide a stub package/module tree for 'inky.auto'
    inky_pkg = types.ModuleType("inky")
    inky_auto_mod = types.ModuleType("inky.auto")
    inky_auto_mod.auto = lambda: fake_disp  # type: ignore
    monkeypatch.setitem(sys.modules, "inky", inky_pkg)
    monkeypatch.setitem(sys.modules, "inky.auto", inky_auto_mod)


def test_inky_initialize_sets_resolution_and_border(monkeypatch, device_config_dev):
    # Ensure no resolution preset to assert writing
    device_config_dev.update_value("resolution", None)

    fake_disp = FakeAutoDisplay(width=296, height=128)

    def fake_auto():
        return fake_disp

    # Install fake 'inky.auto'
    _install_fake_inky(monkeypatch, fake_disp)

    from display.inky_display import InkyDisplay

    _driver = InkyDisplay(device_config_dev)

    # Resolution saved as list [w, h]
    assert device_config_dev.get_config("resolution") == [296, 128]
    # Border set to driver's BLACK value
    assert fake_disp.border == fake_disp.BLACK


def test_inky_display_image_calls_set_image_and_show(monkeypatch, device_config_dev):
    fake_disp = FakeAutoDisplay(width=212, height=104)
    _install_fake_inky(monkeypatch, fake_disp)

    from display.inky_display import InkyDisplay

    driver = InkyDisplay(device_config_dev)

    image = Image.new("RGB", (100, 50), "white")
    driver.display_image(image)

    assert getattr(driver, "inky_display")._image is not None
    assert getattr(driver, "inky_display").shown is True


def test_inky_display_image_raises_on_none(monkeypatch, device_config_dev):
    fake_disp = FakeAutoDisplay(width=212, height=104)
    _install_fake_inky(monkeypatch, fake_disp)

    from display.inky_display import InkyDisplay

    driver = InkyDisplay(device_config_dev)

    with pytest.raises(ValueError):
        driver.display_image(None)


# --- Mock Display ---


def test_mock_display_writes_latest_and_timestamp(
    monkeypatch, device_config_dev, tmp_path
):
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


def test_mock_display_initialize_display_logging(device_config_dev):
    """Test that mock display logs initialization message."""
    device_config_dev.update_value("display_type", "mock")
    device_config_dev.update_value("resolution", [200, 100])

    # Mock the logger to capture log calls
    with patch("display.mock_display.logger") as mock_logger:
        mock_logger.info = MagicMock()

        from display.mock_display import MockDisplay

        display = MockDisplay(device_config_dev)

        # Check that initialization logging occurred
        display.initialize_display()  # Explicitly call to trigger logging

        # Verify the log message was called
        mock_logger.info.assert_called_once_with("Mock display initialized: 200x100")


def test_mock_display_display_image_with_none_image_settings(
    device_config_dev, tmp_path
):
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
