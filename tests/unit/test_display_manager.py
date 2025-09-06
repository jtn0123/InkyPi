import types
import builtins
from PIL import Image
import pytest


def make_image(w=320, h=240, color="white"):
    return Image.new("RGB", (w, h), color)


def test_display_manager_mock_pipeline(device_config_dev, monkeypatch, tmp_path):
    # Force mock display
    device_config_dev.update_value("display_type", "mock")
    device_config_dev.update_value("resolution", [200, 100])
    device_config_dev.update_value("orientation", "horizontal")
    device_config_dev.update_value("image_settings", {"brightness": 1.2, "contrast": 0.9, "saturation": 1.0, "sharpness": 1.0})

    # Import late to pick up patched sys.path from conftest
    from display.display_manager import DisplayManager

    # Spy on image utils
    called = {"change_orientation": False, "resize_image": False, "apply_image_enhancement": False}

    import utils.image_utils as image_utils
    import display.display_manager as dm_mod
    original_change = image_utils.change_orientation
    original_resize = image_utils.resize_image
    original_apply = image_utils.apply_image_enhancement

    def spy_change(img, orientation, inverted=False):
        called["change_orientation"] = True
        return original_change(img, orientation, inverted)

    def spy_resize(img, desired_size, image_settings=None):
        called["resize_image"] = True
        return original_resize(img, desired_size, image_settings or [])

    def spy_apply(img, settings):
        called["apply_image_enhancement"] = True
        return original_apply(img, settings)

    # Patch the names used inside display_manager module
    monkeypatch.setattr(dm_mod, "change_orientation", spy_change, raising=True)
    monkeypatch.setattr(dm_mod, "resize_image", spy_resize, raising=True)
    monkeypatch.setattr(dm_mod, "apply_image_enhancement", spy_apply, raising=True)

    dm = DisplayManager(device_config_dev)

    img = make_image(300, 200)
    dm.display_image(img)

    # pipeline calls occurred
    assert all(called.values())

    # output saved as current image
    from pathlib import Path
    assert Path(device_config_dev.current_image_file).exists()


def test_display_manager_selects_display_type_mock(device_config_dev):
    device_config_dev.update_value("display_type", "mock")
    from display.display_manager import DisplayManager
    dm = DisplayManager(device_config_dev)
    assert dm.display.__class__.__name__ == "MockDisplay"


def test_display_manager_rejects_unsupported_type(device_config_dev):
    device_config_dev.update_value("display_type", "unknown")
    from display.display_manager import DisplayManager
    with pytest.raises(ValueError):
        DisplayManager(device_config_dev)


def test_display_manager_selects_inky(monkeypatch, device_config_dev):
    # Patch inky display import in display_manager
    device_config_dev.update_value("display_type", "inky")

    # Provide a dummy InkyDisplay class in the expected import path
    class FakeInky:
        def __init__(self, cfg):
            self.cfg = cfg

        def display_image(self, img, image_settings=None):
            self.last = (img.size, tuple(image_settings or []))

    import display
    fake_mod = types.SimpleNamespace(InkyDisplay=FakeInky)
    monkeypatch.setitem(builtins.__dict__, "__cached__", None)  # noop to appease import system
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")

    # Monkeypatch module attribute where display_manager resolves it
    import display.display_manager as dm_mod
    monkeypatch.setattr(dm_mod, "InkyDisplay", FakeInky, raising=False)

    from display.display_manager import DisplayManager
    dm = DisplayManager(device_config_dev)
    assert dm.display.__class__.__name__ == "FakeInky"


def test_display_manager_selects_waveshare(monkeypatch, device_config_dev):
    # display_type pattern epd*in* triggers waveshare
    device_config_dev.update_value("display_type", "epd7in3e")

    class FakeWS:
        def __init__(self, cfg):
            self.cfg = cfg
        def display_image(self, img, image_settings=None):
            self.last = (img.size, tuple(image_settings or []))

    import display.display_manager as dm_mod
    monkeypatch.setattr(dm_mod, "WaveshareDisplay", FakeWS, raising=False)

    from display.display_manager import DisplayManager
    dm = DisplayManager(device_config_dev)
    assert dm.display.__class__.__name__ == "FakeWS"


