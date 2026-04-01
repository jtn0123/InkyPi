import builtins
import types
from datetime import UTC, datetime

import pytest
from PIL import Image


def make_image(w=320, h=240, color="white"):
    return Image.new("RGB", (w, h), color)


def test_display_manager_mock_pipeline(device_config_dev, monkeypatch, tmp_path):
    # Force mock display
    device_config_dev.update_value("display_type", "mock")
    device_config_dev.update_value("resolution", [200, 100])
    device_config_dev.update_value("orientation", "horizontal")
    device_config_dev.update_value(
        "image_settings",
        {"brightness": 1.2, "contrast": 0.9, "saturation": 1.0, "sharpness": 1.0},
    )

    # Import late to pick up patched sys.path from conftest
    from display.display_manager import DisplayManager

    # Spy on image utils
    called = {
        "change_orientation": False,
        "resize_image": False,
        "apply_image_enhancement": False,
    }

    import display.display_manager as dm_mod
    import utils.image_utils as image_utils

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

    # processed preview image saved
    assert Path(device_config_dev.processed_image_file).exists()


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

    _fake_mod = types.SimpleNamespace(InkyDisplay=FakeInky)
    monkeypatch.setitem(
        builtins.__dict__, "__cached__", None
    )  # noop to appease import system
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


def test_display_manager_writes_history_sidecar(device_config_dev):
    device_config_dev.update_value("display_type", "mock")
    import json
    from pathlib import Path

    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)
    dm.display_image(
        make_image(200, 100),
        history_meta={"plugin_id": "clock", "plugin_instance": "A"},
    )

    history_dir = Path(device_config_dev.history_image_dir)
    pngs = sorted(history_dir.glob("display_*.png"))
    jsons = sorted(history_dir.glob("display_*.json"))
    assert pngs
    assert jsons
    with open(jsons[-1], encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload["plugin_id"] == "clock"
    assert payload["plugin_instance"] == "A"
    assert "refresh_time" in payload


def test_display_manager_history_uses_device_timezone(
    device_config_dev, monkeypatch, tmp_path
):
    device_config_dev.update_value("display_type", "mock")
    import json
    from pathlib import Path

    import display.display_manager as dm_mod
    from display.display_manager import DisplayManager

    device_config_dev.history_image_dir = str(tmp_path / "history_tz")
    frozen_now = datetime(2026, 3, 31, 22, 45, 12, tzinfo=UTC)
    monkeypatch.setattr(dm_mod, "now_device_tz", lambda _config: frozen_now)

    dm = DisplayManager(device_config_dev)
    dm.display_image(make_image(200, 100), history_meta={"plugin_id": "clock"})

    history_dir = Path(device_config_dev.history_image_dir)
    jsons = sorted(history_dir.glob("display_*.json"))
    with open(jsons[-1], encoding="utf-8") as fh:
        payload = json.load(fh)

    assert payload["refresh_time"] == frozen_now.isoformat()
    assert jsons[-1].stem == "display_20260331_224512"


def test_display_manager_history_collision_adds_suffix(device_config_dev, monkeypatch):
    device_config_dev.update_value("display_type", "mock")
    from pathlib import Path

    import display.display_manager as dm_mod
    from display.display_manager import DisplayManager

    frozen_now = datetime(2026, 3, 31, 22, 45, 12, tzinfo=UTC)
    monkeypatch.setattr(dm_mod, "now_device_tz", lambda _config: frozen_now)

    dm = DisplayManager(device_config_dev)
    image = make_image(200, 100)

    dm._save_history_entry(image, history_meta={"plugin_id": "clock"})
    dm._save_history_entry(image, history_meta={"plugin_id": "clock"})

    history_dir = Path(device_config_dev.history_image_dir)
    pngs = sorted(path.stem for path in history_dir.glob("display_*.png"))
    assert "display_20260331_224512" in pngs
    assert "display_20260331_224512_001" in pngs


def test_display_manager_display_preprocessed_image(device_config_dev, tmp_path):
    device_config_dev.update_value("display_type", "mock")
    from pathlib import Path

    from display.display_manager import DisplayManager

    img_path = tmp_path / "preprocessed.png"
    make_image(100, 50).save(img_path)

    dm = DisplayManager(device_config_dev)
    dm.display_preprocessed_image(str(img_path))

    assert Path(device_config_dev.current_image_file).exists()
    assert Path(device_config_dev.processed_image_file).exists()
