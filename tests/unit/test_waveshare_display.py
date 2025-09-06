import types
import sys
from PIL import Image
import pytest


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


class FakeBiColorEPD(FakeMonoEPD):
    # Simulate display with signature that accepts two buffers
    def display(self, buf1, buf2=None):
        self.displayed.append((buf1, buf2))


def install_fake_epd_module(monkeypatch, module_name: str, epd_class):
    # Create fake module: display.waveshare_epd.<module_name>
    ws_pkg = types.ModuleType("display.waveshare_epd")
    # Ensure parent packages exist in sys.modules for importlib to find
    display_pkg = sys.modules.get("display")
    if display_pkg is None:
        display_pkg = types.ModuleType("display")
        sys.modules["display"] = display_pkg
    sys.modules["display.waveshare_epd"] = ws_pkg

    epd_mod = types.ModuleType(f"display.waveshare_epd.{module_name}")

    class EPD(epd_class):
        pass
    epd_mod.EPD = EPD

    sys.modules[f"display.waveshare_epd.{module_name}"] = epd_mod


def test_waveshare_initialize_sets_resolution(monkeypatch, device_config_dev):
    device_config_dev.update_value("display_type", "epd7in3e")
    device_config_dev.update_value("resolution", None)

    install_fake_epd_module(monkeypatch, "epd7in3e", FakeMonoEPD)

    from display.waveshare_display import WaveshareDisplay
    driver = WaveshareDisplay(device_config_dev)

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


