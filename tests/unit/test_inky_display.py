import types
import sys
import pytest
from PIL import Image


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
    inky_auto_mod.auto = lambda: fake_disp
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
    driver = InkyDisplay(device_config_dev)

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


