import sys
import types
from typing import Any

import pytest
from PIL import Image


class FakeMonoEPD:
    def __init__(self):
        self.width = 800
        self.height = 480
        self.inited = False
        self.cleared = False
        self.displayed = []
        self.slept = False

    def Init(self):
        self.inited = True

    def getbuffer(self, img):
        return ("buf", img.size)

    def display(self, buf, *args):
        self.displayed.append((buf, args))

    def Clear(self):
        self.cleared = True

    def sleep(self):
        self.slept = True


class FakeBiColorEPD:
    def __init__(self):
        self.width = 800
        self.height = 480
        self.inited = False
        self.cleared = False
        self.displayed = []
        self.slept = False

    def Init(self):
        self.inited = True

    def getbuffer(self, img):
        return ("buf", img.size)

    def display(self, buf1, buf2):
        # tests expect (buf1, buf2) where both are tuples from getbuffer
        self.displayed.append((buf1, buf2))

    def Clear(self):
        self.cleared = True

    def sleep(self):
        self.slept = True


def install_fake_epd_module(monkeypatch, module_name: str, epd_class):
    # Ensure the real display package is imported first
    if "display" not in sys.modules:
        try:
            import importlib.util

            if importlib.util.find_spec("display"):
                __import__("display")
        except ImportError:
            pass

    # Create fake module: display.waveshare_epd.<module_name>
    ws_pkg = types.ModuleType("display.waveshare_epd")
    # Ensure parent packages exist in sys.modules for importlib to find
    display_pkg = sys.modules.get("display")
    if display_pkg is None:
        display_pkg = types.ModuleType("display")
        sys.modules["display"] = display_pkg
    elif hasattr(display_pkg, "__path__"):
        # If display is already a proper package, don't override it
        pass
    else:
        # If display exists but is not a package, we need to replace it
        display_pkg = types.ModuleType("display")
        sys.modules["display"] = display_pkg
    sys.modules["display.waveshare_epd"] = ws_pkg

    epd_mod = types.ModuleType(f"display.waveshare_epd.{module_name}")

    class EPD(epd_class):
        pass

    # Assign EPD attribute via setattr to avoid static analyzer complaints
    epd_mod.EPD = EPD

    sys.modules[f"display.waveshare_epd.{module_name}"] = epd_mod


def test_waveshare_initialize_sets_resolution(monkeypatch, device_config_dev):
    device_config_dev.update_value("display_type", "epd7in3e")
    device_config_dev.update_value("resolution", None)

    install_fake_epd_module(monkeypatch, "epd7in3e", FakeMonoEPD)

    from display.waveshare_display import WaveshareDisplay

    _driver = WaveshareDisplay(device_config_dev)

    # Resolution stored in config (width >= height order)
    assert device_config_dev.get_config("resolution") == [800, 480]


def test_waveshare_display_image_mono(monkeypatch, device_config_dev):
    device_config_dev.update_value("display_type", "epd7in3e")
    install_fake_epd_module(monkeypatch, "epd7in3e", FakeMonoEPD)

    from display.waveshare_display import WaveshareDisplay

    driver = WaveshareDisplay(device_config_dev)

    img = Image.new("1", (200, 100), 255)
    driver.display_image(img)

    epd = driver.epd_display
    assert epd.inited is True
    assert epd.cleared is True
    assert len(epd.displayed) == 1
    (buf, size), args = epd.displayed[0]
    assert size == img.size
    assert epd.slept is True


def test_waveshare_display_image_bicolor(monkeypatch, device_config_dev):
    device_config_dev.update_value("display_type", "epd7in3e")
    install_fake_epd_module(monkeypatch, "epd7in3e", FakeBiColorEPD)

    from display.waveshare_display import WaveshareDisplay

    driver = WaveshareDisplay(device_config_dev)

    img = Image.new("1", (200, 100), 255)
    driver.display_image(img)

    epd = driver.epd_display
    assert epd.inited is True
    assert epd.cleared is True
    # bi-color path uses two buffers
    assert len(epd.displayed) == 1
    buf1, buf2 = epd.displayed[0]
    assert isinstance(buf1, tuple) and isinstance(buf2, tuple)
    assert buf1[1] == img.size and buf2[1] == img.size
    assert epd.slept is True


def test_waveshare_init_unsupported_module(monkeypatch, device_config_dev):
    # Do not install fake module; expect ValueError
    device_config_dev.update_value("display_type", "epdXunknown")
    from display.waveshare_display import WaveshareDisplay

    with pytest.raises(ValueError):
        WaveshareDisplay(device_config_dev)


def test_waveshare_init_rejects_unsafe_display_type(device_config_dev):
    device_config_dev.update_value("display_type", "../epd7in3e")
    from display.waveshare_display import WaveshareDisplay

    with pytest.raises(ValueError, match="Unsupported Waveshare display type"):
        WaveshareDisplay(device_config_dev)


def test_waveshare_init_missing_display_type(device_config_dev):
    """Test that WaveshareDisplay raises ValueError when display_type is missing."""
    device_config_dev.update_value("display_type", None)
    from display.waveshare_display import WaveshareDisplay

    with pytest.raises(
        ValueError,
        match="Waveshare driver but 'display_type' not specified in configuration",
    ):
        WaveshareDisplay(device_config_dev)


def test_waveshare_display_image_none_raises(monkeypatch, device_config_dev):
    """Test that display_image raises ValueError on None (not truthy check on PIL Image)."""
    device_config_dev.update_value("display_type", "epd7in3e")
    install_fake_epd_module(monkeypatch, "epd7in3e", FakeMonoEPD)

    from display.waveshare_display import WaveshareDisplay

    driver = WaveshareDisplay(device_config_dev)

    with pytest.raises(ValueError, match="No image provided"):
        driver.display_image(None)


def test_waveshare_display_image_valid_pil_image_not_rejected(
    monkeypatch, device_config_dev
):
    """Test that a valid PIL Image is not incorrectly rejected by the None check.

    Pillow 10.x raises a TypeError if you use `if not image:` on a PIL Image object.
    Ensure the explicit `if image is None:` check accepts a real image without error.
    """
    device_config_dev.update_value("display_type", "epd7in3e")
    install_fake_epd_module(monkeypatch, "epd7in3e", FakeMonoEPD)

    from display.waveshare_display import WaveshareDisplay

    driver = WaveshareDisplay(device_config_dev)

    # A 1x1 image would raise TypeError on `if not image:` in modern Pillow
    img = Image.new("RGB", (1, 1), (0, 0, 0))
    # Should not raise
    driver.display_image(img)


class FakeGrayscaleModeEPD:
    """Mirrors the epd3in7 driver shape (upstream fatihak#724).

    Signatures copied from the manifest-pinned epd3in7.py: ``init`` and
    ``Clear`` take required mode arguments and there is no generic ``display``
    — only ``display_1Gray`` / ``display_4Gray``.
    """

    def __init__(self) -> None:
        self.width = 280
        self.height = 480
        self.init_modes = []
        self.clear_calls = []
        self.gray1 = []
        self.gray4 = []
        self.slept = False

    def init(self, mode: Any) -> None:
        self.init_modes.append(mode)

    def getbuffer(self, img: Any):
        return ("buf", img.size)

    def getbuffer_4Gray(self, img: Any):  # noqa: N802 — mirrors the vendor driver
        return ("buf4", img.size)

    def display_1Gray(self, buf: Any) -> None:  # noqa: N802 — mirrors the vendor driver
        self.gray1.append(buf)

    def display_4Gray(self, buf: Any) -> None:  # noqa: N802 — mirrors the vendor driver
        self.gray4.append(buf)

    def Clear(self, color: Any, mode: Any) -> None:
        self.clear_calls.append((color, mode))

    def sleep(self) -> None:
        self.slept = True


class FakeClearWithColorEPD(FakeMonoEPD):
    """A driver whose Clear takes a colour byte but no mode."""

    def __init__(self) -> None:
        super().__init__()
        self.clear_colors = []

    def Clear(self, color: Any) -> None:
        self.clear_colors.append(color)
        self.cleared = True


def test_grayscale_mode_driver_initializes_without_typeerror(
    monkeypatch, device_config_dev
) -> None:
    """epd3in7 is in the driver manifest, so it must actually load."""
    device_config_dev.update_value("display_type", "epd3in7")
    device_config_dev.update_value("resolution", None)
    install_fake_epd_module(monkeypatch, "epd3in7", FakeGrayscaleModeEPD)

    from display.waveshare_display import WaveshareDisplay

    driver = WaveshareDisplay(device_config_dev)

    assert driver.grayscale_mode_display is True
    assert driver.bi_color_display is False
    # 1-bit grayscale mirrors the standard single-colour path.
    assert driver.epd_display.init_modes == [1]
    assert device_config_dev.get_config("resolution") == [480, 280]


def test_grayscale_mode_driver_renders_via_display_1gray(
    monkeypatch, device_config_dev
) -> None:
    device_config_dev.update_value("display_type", "epd3in7")
    install_fake_epd_module(monkeypatch, "epd3in7", FakeGrayscaleModeEPD)

    from display.waveshare_display import WaveshareDisplay

    driver = WaveshareDisplay(device_config_dev)
    img = Image.new("1", (200, 100), 255)
    driver.display_image(img)

    epd = driver.epd_display
    assert len(epd.gray1) == 1, "should render through display_1Gray"
    assert epd.gray4 == [], "4-grayscale needs a different buffer; not our path"
    # Clear takes (color, mode) on these drivers.
    assert epd.clear_calls == [(0xFF, 1)]
    assert epd.slept is True


def test_mode_argument_with_a_default_is_not_treated_as_mode_driven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a *required* mode parameter changes how we drive the panel."""
    from display.waveshare_display import _requires_mode_argument

    def init_required(mode: Any) -> None:
        pass

    def init_defaulted(mode: Any = 0) -> None:
        pass

    def init_plain() -> None:
        pass

    assert _requires_mode_argument(init_required) is True
    assert _requires_mode_argument(init_defaulted) is False
    assert _requires_mode_argument(init_plain) is False


def test_clear_receives_a_color_when_the_driver_requires_one(
    monkeypatch, device_config_dev
) -> None:
    device_config_dev.update_value("display_type", "epd7in3e")
    install_fake_epd_module(monkeypatch, "epd7in3e", FakeClearWithColorEPD)

    from display.waveshare_display import WaveshareDisplay

    driver = WaveshareDisplay(device_config_dev)
    driver.display_image(Image.new("1", (200, 100), 255))

    assert driver.epd_display.clear_colors == [0xFF]
