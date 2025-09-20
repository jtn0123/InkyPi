import builtins
import types

import pytest
from PIL import Image
from typing import Any


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


def test_display_preprocessed_image_success(tmp_path, device_config_dev, monkeypatch):
    # Ensure mock display
    device_config_dev.update_value("display_type", "mock")

    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)

    # Create a preprocessed image file
    img_path = tmp_path / "preprocessed.png"
    img = make_image(120, 90)
    img.save(img_path)

    # Spy on underlying display call
    calls = {"display": 0}

    def spy_display(image, image_settings=None):
        calls["display"] += 1

    monkeypatch.setattr(dm.display, "display_image", spy_display, raising=True)

    dm.display_preprocessed_image(str(img_path))

    # Preview/current files updated
    from pathlib import Path

    assert Path(device_config_dev.processed_image_file).exists()
    assert Path(device_config_dev.current_image_file).exists()
    # Underlying display invoked
    assert calls["display"] == 1


def test_display_preprocessed_image_load_failure(device_config_dev):
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)

    with pytest.raises(RuntimeError):
        dm.display_preprocessed_image("/non/existent/file.png")


def test_save_image_only(tmp_path, device_config_dev):
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)
    img = make_image(50, 60)

    dm.save_image_only(img, filename="preview_test.png")

    from pathlib import Path

    preview_dir = Path(device_config_dev.processed_image_file).parent
    assert (preview_dir / "preview_test.png").exists()


def test_display_image_history_sidecar_and_metrics(monkeypatch, device_config_dev):
    # Ensure mock display
    device_config_dev.update_value("display_type", "mock")

    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)

    # Provide a refresh_info object with empty metrics and a benchmark_id
    from model import RefreshInfo

    ri = RefreshInfo(
        refresh_type="Manual Update",
        plugin_id="test_plugin",
        refresh_time=None,
        image_hash=None,
        benchmark_id="b-123",
    )
    device_config_dev.refresh_info = ri

    # Spy save_stage_event
    saved: dict[str, Any] = {}

    def fake_save_stage_event(cfg, benchmark_id, stage, duration_ms, extra=None):
        saved["args"] = (benchmark_id, stage, duration_ms)
        saved["extra"] = extra

    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setattr(
        "benchmarks.benchmark_storage.save_stage_event",
        fake_save_stage_event,
        raising=False,
    )

    # Run display pipeline
    img = make_image(64, 48)
    dm.display_image(img, image_settings=[], history_meta={"foo": "bar"})

    # Sidecar JSON should exist in history dir
    from pathlib import Path
    import json

    history_dir = Path(device_config_dev.history_image_dir)
    # Find a sidecar json created very recently
    jsons = sorted(history_dir.glob("display_*.json"))
    assert jsons, "expected a sidecar json file to be created"
    data = json.loads(jsons[-1].read_text())
    assert data.get("foo") == "bar"
    assert "history_filename" in data
    assert "saved_at" in data

    # Metrics persisted in refresh_info if previously None
    assert ri.preprocess_ms is not None
    assert ri.display_ms is not None

    # Benchmark stage event emitted
    assert saved.get("args") is not None
    args = saved.get("args")
    assert isinstance(args, tuple)
    assert len(args) == 3
    b_id, stage, duration_ms = args
    assert b_id == "b-123"
    assert stage == "display_driver"
    assert isinstance(duration_ms, int)
    extra_any = saved.get("extra")
    if not isinstance(extra_any, dict):
        extra_any = {}
    assert "display_type" in extra_any
