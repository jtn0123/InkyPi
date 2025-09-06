import importlib
import types
import sys
import pytest


def make_fake_gpio_module():
    m = types.ModuleType("gpiozero")
    class LED:
        def __init__(self, pin):
            self.pin = pin
            self._value = False
        def on(self):
            self._value = True
        def off(self):
            self._value = False
        @property
        def value(self):
            return self._value
        def close(self):
            pass

    class Button:
        def __init__(self, pin, pull_up=False):
            self.pin = pin
            self._value = False
        @property
        def value(self):
            return self._value
        def close(self):
            pass

    m.LED = LED  # type: ignore[attr-defined]
    m.Button = Button  # type: ignore[attr-defined]
    return m


def make_fake_spidev_module():
    m = types.ModuleType("spidev")
    class SpiDev:
        def __init__(self):
            self.opened = False
            self.max_speed_hz = None
            self.mode = None
        def open(self, bus, device):
            self.opened = True
        def writebytes(self, data):
            pass
        def writebytes2(self, data):
            pass
        def close(self):
            self.opened = False
    m.SpiDev = SpiDev  # type: ignore[attr-defined]
    return m


def install_fake_modules(monkeypatch):
    # install spidev and gpiozero
    sys.modules['spidev'] = make_fake_spidev_module()
    gpio_mod = make_fake_gpio_module()
    # also provide top-level attributes expected by tests (LED, Button)
    sys.modules['gpiozero'] = gpio_mod


def test_raspberry_selection_and_methods(monkeypatch, monkeypatching=None):
    install_fake_modules(monkeypatch)
    # monkeypatch cpuinfo output to include Raspberry
    # Create a fake subprocess.Popen that returns 'Raspberry' in output
    class FakePopen:
        def __init__(self, *args, **kwargs):
            pass
        def communicate(self):
            return ("Raspberry Pi" , None)

    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: FakePopen())

    epdconfig = importlib.reload(importlib.import_module('display.waveshare_epd.epdconfig'))

    # ensure implementation has expected attributes
    assert hasattr(epdconfig, 'module_init')
    assert hasattr(epdconfig, 'spi_writebyte')

    # call module_init (non-cleanup path) to exercise SPI open
    epdconfig.module_init(cleanup=False)


def test_jetson_imports_guarded(monkeypatch):
    # Ensure Jetson.GPIO is not present and module still loads
    if 'Jetson' in sys.modules:
        del sys.modules['Jetson']
    if 'Jetson.GPIO' in sys.modules:
        del sys.modules['Jetson.GPIO']

    # Simulate cpuinfo without Raspberry to force Jetson selection path
    class FakePopen2:
        def __init__(self, *args, **kwargs):
            pass
        def communicate(self):
            return ("", None)

    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: FakePopen2())

    epdconfig = importlib.reload(importlib.import_module('display.waveshare_epd.epdconfig'))
    # module should expose functions even without Jetson.GPIO present
    assert hasattr(epdconfig, 'module_init')
    assert hasattr(epdconfig, 'spi_writebyte')


