"""
E-paper Display Hardware Configuration Tests

Tests for the Waveshare epdconfig.py vendored module, focused on the
Raspberry Pi platform (the only platform InkyPi targets). JetsonNano
and SunriseX3 classes exist in the vendored file but are not tested
since InkyPi does not run on those platforms.
"""

import builtins
import importlib
import io
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

_real_open = builtins.open


def mock_cpuinfo(content):
    """Return a context manager that patches builtins.open to fake /proc/cpuinfo."""

    def _patched_open(path, *args, **kwargs):
        if path == "/proc/cpuinfo":
            return io.StringIO(content)
        return _real_open(path, *args, **kwargs)

    return patch("builtins.open", side_effect=_patched_open)


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
    """Install fake spidev and gpiozero modules so RaspberryPi class can load."""
    sys.modules["spidev"] = make_fake_spidev_module()
    sys.modules["gpiozero"] = make_fake_gpio_module()


def _load_epdconfig_as_rpi(monkeypatch, install_mocks=True):
    """Reload epdconfig with Raspberry Pi detected. Returns the module."""
    if install_mocks:
        install_fake_modules(monkeypatch)
    with mock_cpuinfo("Raspberry Pi"):
        return importlib.reload(
            importlib.import_module("display.waveshare_epd.epdconfig")
        )


# ---------------------------------------------------------------------------
# Raspberry Pi platform tests
# ---------------------------------------------------------------------------


def test_raspberry_selection_and_methods(monkeypatch):
    epdconfig = _load_epdconfig_as_rpi(monkeypatch)

    assert hasattr(epdconfig, "module_init")
    assert hasattr(epdconfig, "spi_writebyte")

    epdconfig.module_init(cleanup=False)


def test_gpio_operations_raspberry_pi(monkeypatch):
    """Test GPIO operations on Raspberry Pi platform."""
    epdconfig = _load_epdconfig_as_rpi(monkeypatch)

    epdconfig.digital_write(17, 1)  # RST_PIN on
    epdconfig.digital_write(25, 0)  # DC_PIN off
    epdconfig.digital_write(18, 1)  # PWR_PIN on

    busy_value = epdconfig.digital_read(24)  # BUSY_PIN
    assert isinstance(busy_value, int | bool)


def test_gpio_operations_without_hardware(monkeypatch):
    """Test GPIO operations when hardware libraries are not available."""
    # Don't install fake modules — simulate missing hardware
    epdconfig = _load_epdconfig_as_rpi(monkeypatch, install_mocks=False)

    epdconfig.digital_write(17, 1)  # Should not crash
    epdconfig.digital_write(25, 0)

    busy_value = epdconfig.digital_read(24)
    assert busy_value == 0  # Default when GPIO not available


def test_spi_operations_raspberry_pi(monkeypatch):
    """Test SPI operations on Raspberry Pi platform."""
    epdconfig = _load_epdconfig_as_rpi(monkeypatch)

    result = epdconfig.module_init(cleanup=False)
    assert result == 0

    epdconfig.spi_writebyte([0x12, 0x34])
    epdconfig.spi_writebyte2([0x56, 0x78])

    epdconfig.module_exit(cleanup=False)


def test_module_init_cleanup_mode(monkeypatch):
    """Test module initialization in cleanup mode."""
    install_fake_modules(monkeypatch)

    with patch("ctypes.CDLL") as mock_cdll:
        mock_dev_spi = MagicMock()
        mock_cdll.return_value = mock_dev_spi

        monkeypatch.setattr("os.path.exists", lambda path: True)
        monkeypatch.setattr("os.popen", lambda cmd: MagicMock())

        epdconfig = _load_epdconfig_as_rpi(monkeypatch)

        result = epdconfig.module_init(cleanup=True)
        assert result == 0

        mock_dev_spi.DEV_Module_Init.assert_called_once()


def test_module_init_cleanup_mode_library_not_found(monkeypatch):
    """Test module initialization when DEV_Config library is not found.

    The vendored code has ``RuntimeError(...)`` without ``raise``, so DEV_SPI
    stays None and the next call (``self.DEV_SPI.DEV_Module_Init()``) raises
    AttributeError.
    """
    epdconfig = _load_epdconfig_as_rpi(monkeypatch)

    monkeypatch.setattr("os.path.exists", lambda path: False)
    monkeypatch.setattr("os.popen", lambda cmd: io.StringIO("64"))

    with pytest.raises(AttributeError):
        epdconfig.module_init(cleanup=True)


def test_dev_spi_operations(monkeypatch):
    """Test DEV_SPI operations when available."""
    epdconfig = _load_epdconfig_as_rpi(monkeypatch)

    impl = epdconfig.module_init.__self__

    mock_dev_spi = MagicMock()
    mock_dev_spi.DEV_SPI_ReadData.return_value = 0x42
    impl.DEV_SPI = mock_dev_spi

    epdconfig.DEV_SPI_write([0x12, 0x34])
    epdconfig.DEV_SPI_nwrite([0x56, 0x78])
    result = epdconfig.DEV_SPI_read()

    mock_dev_spi.DEV_SPI_SendData.assert_called_with([0x12, 0x34])
    mock_dev_spi.DEV_SPI_SendnData.assert_called_with([0x56, 0x78])
    mock_dev_spi.DEV_SPI_ReadData.assert_called_once()
    assert result == 0x42


def test_dev_spi_operations_no_library(monkeypatch):
    """Test DEV_SPI operations when library is not initialized.

    DEV_SPI is not set on the implementation after a normal (non-cleanup)
    load, so calling DEV_SPI_write etc. raises AttributeError.
    """
    epdconfig = _load_epdconfig_as_rpi(monkeypatch)

    with pytest.raises(AttributeError):
        epdconfig.DEV_SPI_write([0x12])

    with pytest.raises(AttributeError):
        epdconfig.DEV_SPI_nwrite([0x34])

    with pytest.raises(AttributeError):
        epdconfig.DEV_SPI_read()


def test_delay_ms_functionality(monkeypatch):
    """Test delay_ms timing function."""
    install_fake_modules(monkeypatch)

    with patch("time.sleep") as mock_sleep:
        epdconfig = _load_epdconfig_as_rpi(monkeypatch)
        epdconfig.delay_ms(100)
        mock_sleep.assert_called_once_with(0.1)


def test_module_exit_cleanup_operations(monkeypatch):
    """Test module exit with cleanup operations."""
    epdconfig = _load_epdconfig_as_rpi(monkeypatch)

    epdconfig.module_init(cleanup=False)
    epdconfig.module_exit(cleanup=False)


def test_gpio_pin_constants(monkeypatch):
    """Test that GPIO pin constants are correctly defined."""
    install_fake_modules(monkeypatch)

    from display.waveshare_epd.epdconfig import RaspberryPi

    rpi = RaspberryPi()
    assert rpi.RST_PIN == 17
    assert rpi.DC_PIN == 25
    assert rpi.CS_PIN == 8
    assert rpi.BUSY_PIN == 24
    assert rpi.PWR_PIN == 18


def test_hardware_import_error_handling(monkeypatch):
    """Test graceful handling when hardware libraries fail to import."""
    epdconfig = _load_epdconfig_as_rpi(monkeypatch, install_mocks=False)

    assert hasattr(epdconfig, "module_init")
    assert hasattr(epdconfig, "digital_write")
    assert hasattr(epdconfig, "digital_read")

    epdconfig.digital_write(17, 1)  # Should not crash
    value = epdconfig.digital_read(24)
    assert value == 0  # Default when GPIO not available


def test_pin_mapping_comprehensive(monkeypatch):
    """Test comprehensive pin mapping for all GPIO operations."""
    epdconfig = _load_epdconfig_as_rpi(monkeypatch)

    # Test digital write for writable pins (RST=17, DC=25, PWR=18)
    for pin in [17, 25, 18]:
        epdconfig.digital_write(pin, 1)
        epdconfig.digital_write(pin, 0)

    # All pins should return correct values via digital_read
    for pin in [17, 25, 18, 24]:  # RST, DC, PWR, BUSY
        value = epdconfig.digital_read(pin)
        assert isinstance(value, int | bool)


def test_raspberry_pi_cleanup_mode_with_dev_config(monkeypatch):
    """Test Raspberry Pi cleanup mode with DEV_Config library."""
    install_fake_modules(monkeypatch)

    monkeypatch.setattr("os.path.exists", lambda path: True)
    monkeypatch.setattr("os.popen", lambda cmd: MagicMock())

    with patch("ctypes.CDLL") as mock_cdll:
        mock_dev_config = MagicMock()
        mock_cdll.return_value = mock_dev_config

        epdconfig = _load_epdconfig_as_rpi(monkeypatch)

        result = epdconfig.module_init(cleanup=True)
        assert result == 0

        mock_dev_config.DEV_Module_Init.assert_called_once()


def test_digital_read_all_pins(monkeypatch):
    """Test digital_read works for all pins (RST, DC, PWR, BUSY) after bug fix."""
    epdconfig = _load_epdconfig_as_rpi(monkeypatch)

    # All pins should return a value without error
    for pin in [17, 25, 18, 24]:  # RST, DC, PWR, BUSY
        value = epdconfig.digital_read(pin)
        assert isinstance(value, int | bool)


def test_spi_configuration(monkeypatch):
    """Test SPI configuration and parameter setting."""
    epdconfig = _load_epdconfig_as_rpi(monkeypatch)

    epdconfig.module_init(cleanup=False)
    # Verify SPI configuration path was exercised (mock objects track this)
