# /*****************************************************************************
# * | File        :	  epdconfig.py
# * | Author      :   Waveshare team
# * | Function    :   Hardware underlying interface
# * | Info        :
# *----------------
# * | This version:   V1.2
# * | Date        :   2022-10-29
# * | Info        :
# ******************************************************************************
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documnetation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to  whom the Software is
# furished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS OR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

import os
import logging
import sys
import time
import subprocess
import ctypes
import importlib
from typing import Any, cast

logger = logging.getLogger(__name__)


class RaspberryPi:
    # Pin definition
    RST_PIN = 17
    DC_PIN = 25
    CS_PIN = 8
    BUSY_PIN = 24
    PWR_PIN = 18
    MOSI_PIN = 10
    SCLK_PIN = 11

    def __init__(self):
        # Import platform-specific modules dynamically to avoid static import errors
        try:
            spidev = importlib.import_module("spidev")
        except Exception:
            spidev = None
        try:
            gpiozero = importlib.import_module("gpiozero")
        except Exception:
            gpiozero = None

        self.SPI = spidev.SpiDev() if spidev is not None else None
        self.GPIO_RST_PIN = gpiozero.LED(self.RST_PIN) if gpiozero is not None else None
        self.GPIO_DC_PIN = gpiozero.LED(self.DC_PIN) if gpiozero is not None else None
        # self.GPIO_CS_PIN     = gpiozero.LED(self.CS_PIN)
        self.GPIO_PWR_PIN = gpiozero.LED(self.PWR_PIN) if gpiozero is not None else None
        self.GPIO_BUSY_PIN = (
            gpiozero.Button(self.BUSY_PIN, pull_up=False)
            if gpiozero is not None
            else None
        )

    def digital_write(self, pin, value):
        if pin == self.RST_PIN:
            if value:
                cast(Any, self.GPIO_RST_PIN).on()
            else:
                cast(Any, self.GPIO_RST_PIN).off()
        elif pin == self.DC_PIN:
            if value:
                cast(Any, self.GPIO_DC_PIN).on()
            else:
                cast(Any, self.GPIO_DC_PIN).off()
        # elif pin == self.CS_PIN:
        #     if value:
        #         self.GPIO_CS_PIN.on()
        #     else:
        #         self.GPIO_CS_PIN.off()
        elif pin == self.PWR_PIN:
            if value:
                cast(Any, self.GPIO_PWR_PIN).on()
            else:
                cast(Any, self.GPIO_PWR_PIN).off()

    def digital_read(self, pin):
        if pin == self.BUSY_PIN:
            return cast(Any, self.GPIO_BUSY_PIN).value
        elif pin == self.RST_PIN:
            return cast(Any, self.GPIO_RST_PIN).value
        elif pin == self.DC_PIN:
            return cast(Any, self.GPIO_DC_PIN).value
        # elif pin == self.CS_PIN:
        #     return self.CS_PIN.value
        elif pin == self.PWR_PIN:
            return cast(Any, self.GPIO_PWR_PIN).value

    def delay_ms(self, delaytime):
        time.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data):
        cast(Any, self.SPI).writebytes(data)

    def spi_writebyte2(self, data):
        cast(Any, self.SPI).writebytes2(data)

    def DEV_SPI_write(self, data):
        if getattr(self, "DEV_SPI", None) is not None:
            # DEV_SPI is a loaded CDLL at runtime; use typing.cast to satisfy static type checkers
            cast(Any, self.DEV_SPI).DEV_SPI_SendData(data)
        else:
            raise RuntimeError("DEV_SPI not initialized")

    def DEV_SPI_nwrite(self, data):
        if getattr(self, "DEV_SPI", None) is not None:
            cast(Any, self.DEV_SPI).DEV_SPI_SendnData(data)
        else:
            raise RuntimeError("DEV_SPI not initialized")

    def DEV_SPI_read(self):
        if getattr(self, "DEV_SPI", None) is not None:
            return cast(Any, self.DEV_SPI).DEV_SPI_ReadData()
        raise RuntimeError("DEV_SPI not initialized")

    def module_init(self, cleanup=False):
        cast(Any, self.GPIO_PWR_PIN).on()

        if cleanup:
            find_dirs = [
                os.path.dirname(os.path.realpath(__file__)),
                "/usr/local/lib",
                "/usr/lib",
            ]
            self.DEV_SPI = None
            for find_dir in find_dirs:
                try:
                    val = int(os.popen("getconf LONG_BIT").read())
                except Exception:
                    val = 64
                logging.debug("System is %d bit" % val)
                if val == 64:
                    so_filename = os.path.join(find_dir, "DEV_Config_64.so")
                else:
                    so_filename = os.path.join(find_dir, "DEV_Config_32.so")
                if os.path.exists(so_filename):
                    self.DEV_SPI = ctypes.CDLL(so_filename)
                    break
            if self.DEV_SPI is None:
                raise RuntimeError("Cannot find DEV_Config.so")

            if self.DEV_SPI is not None:
                self.DEV_SPI.DEV_Module_Init()

        else:
            # SPI device, bus = 0, device = 0
            cast(Any, self.SPI).open(0, 0)
            cast(Any, self.SPI).max_speed_hz = 4000000
            cast(Any, self.SPI).mode = 0b00
        return 0

    def module_exit(self, cleanup=False):
        logger.debug("spi end")
        cast(Any, self.SPI).close()

        cast(Any, self.GPIO_RST_PIN).off()
        cast(Any, self.GPIO_DC_PIN).off()
        cast(Any, self.GPIO_PWR_PIN).off()
        logger.debug("close 5V, Module enters 0 power consumption ...")

        if cleanup:
            cast(Any, self.GPIO_RST_PIN).close()
            cast(Any, self.GPIO_DC_PIN).close()
            # self.GPIO_CS_PIN.close()
            cast(Any, self.GPIO_PWR_PIN).close()
            cast(Any, self.GPIO_BUSY_PIN).close()


class JetsonNano:
    # Pin definition
    RST_PIN = 17
    DC_PIN = 25
    CS_PIN = 8
    BUSY_PIN = 24
    PWR_PIN = 18

    def __init__(self):
        # ctypes already imported at module level
        find_dirs = [
            os.path.dirname(os.path.realpath(__file__)),
            "/usr/local/lib",
            "/usr/lib",
        ]
        self.SPI = None
        for find_dir in find_dirs:
            so_filename = os.path.join(find_dir, "sysfs_software_spi.so")
            if os.path.exists(so_filename):
                self.SPI = ctypes.cdll.LoadLibrary(so_filename)
                break
        if self.SPI is None:
            # For testing/development: don't fail if SPI library is missing
            # Create a mock SPI object that implements the expected interface
            self.SPI = self._create_mock_spi()

        # Jetson.GPIO is only available on Jetson platforms; import defensively via importlib
        try:
            JetsonGPIO = importlib.import_module("Jetson.GPIO")
        except Exception:
            JetsonGPIO = None
        self.GPIO = JetsonGPIO  # type: Any

    def _create_mock_spi(self):
        """Create a mock SPI object for testing when sysfs_software_spi.so is not available"""

        class MockSPI:
            def SYSFS_software_spi_transfer(self, data):
                pass

            def SYSFS_software_spi_begin(self):
                pass

            def SYSFS_software_spi_end(self):
                pass

        return MockSPI()

    def digital_write(self, pin, value):
        if self.GPIO is None:
            return  # Mock implementation for testing
        self.GPIO.output(pin, value)

    def digital_read(self, pin):
        if self.GPIO is None:
            return 0  # Mock implementation for testing
        return self.GPIO.input(self.BUSY_PIN)

    def delay_ms(self, delaytime):
        time.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data):
        cast(Any, self.SPI).SYSFS_software_spi_transfer(data[0])

    def spi_writebyte2(self, data):
        for i in range(len(data)):
            cast(Any, self.SPI).SYSFS_software_spi_transfer(data[i])

    def module_init(self):
        if self.GPIO is None:
            # Mock implementation for testing - just initialize SPI
            cast(Any, self.SPI).SYSFS_software_spi_begin()
            return 0

        self.GPIO.setmode(self.GPIO.BCM)
        self.GPIO.setwarnings(False)
        self.GPIO.setup(self.RST_PIN, self.GPIO.OUT)
        self.GPIO.setup(self.DC_PIN, self.GPIO.OUT)
        self.GPIO.setup(self.CS_PIN, self.GPIO.OUT)
        self.GPIO.setup(self.PWR_PIN, self.GPIO.OUT)
        self.GPIO.setup(self.BUSY_PIN, self.GPIO.IN)

        self.GPIO.output(self.PWR_PIN, 1)

        cast(Any, self.SPI).SYSFS_software_spi_begin()
        return 0

    def module_exit(self):
        logger.debug("spi end")
        cast(Any, self.SPI).SYSFS_software_spi_end()

        if self.GPIO is None:
            # Mock implementation for testing
            return

        logger.debug("close 5V, Module enters 0 power consumption ...")
        self.GPIO.output(self.RST_PIN, 0)
        self.GPIO.output(self.DC_PIN, 0)
        self.GPIO.output(self.PWR_PIN, 0)

        self.GPIO.cleanup(
            [self.RST_PIN, self.DC_PIN, self.CS_PIN, self.BUSY_PIN, self.PWR_PIN]
        )


class SunriseX3:
    # Pin definition
    RST_PIN = 17
    DC_PIN = 25
    CS_PIN = 8
    BUSY_PIN = 24
    PWR_PIN = 18
    Flag = 0

    def __init__(self):
        try:
            spidev = importlib.import_module("spidev")
        except Exception:
            spidev = None
        try:
            HobotGPIO = importlib.import_module("Hobot.GPIO")
        except Exception:
            HobotGPIO = None

        self.GPIO = HobotGPIO  # type: Any
        self.SPI = spidev.SpiDev() if spidev is not None else None

    def digital_write(self, pin, value):
        cast(Any, self.GPIO).output(pin, value)

    def digital_read(self, pin):
        return cast(Any, self.GPIO).input(pin)

    def delay_ms(self, delaytime):
        time.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data):
        cast(Any, self.SPI).writebytes(data)

    def spi_writebyte2(self, data):
        # for i in range(len(data)):
        #     self.SPI.writebytes([data[i]])
        cast(Any, self.SPI).xfer3(data)

    def module_init(self):
        if self.Flag == 0:
            self.Flag = 1
            cast(Any, self.GPIO).setmode(cast(Any, self.GPIO).BCM)
            cast(Any, self.GPIO).setwarnings(False)
            cast(Any, self.GPIO).setup(self.RST_PIN, cast(Any, self.GPIO).OUT)
            cast(Any, self.GPIO).setup(self.DC_PIN, cast(Any, self.GPIO).OUT)
            cast(Any, self.GPIO).setup(self.CS_PIN, cast(Any, self.GPIO).OUT)
            cast(Any, self.GPIO).setup(self.PWR_PIN, cast(Any, self.GPIO).OUT)
            cast(Any, self.GPIO).setup(self.BUSY_PIN, cast(Any, self.GPIO).IN)

            cast(Any, self.GPIO).output(self.PWR_PIN, 1)

            # SPI device, bus = 0, device = 0
            cast(Any, self.SPI).open(2, 0)
            cast(Any, self.SPI).max_speed_hz = 4000000
            cast(Any, self.SPI).mode = 0b00
            return 0
        else:
            return 0

    def module_exit(self):
        logger.debug("spi end")
        cast(Any, self.SPI).close()

        logger.debug("close 5V, Module enters 0 power consumption ...")
        self.Flag = 0
        cast(Any, self.GPIO).output(self.RST_PIN, 0)
        cast(Any, self.GPIO).output(self.DC_PIN, 0)
        cast(Any, self.GPIO).output(self.PWR_PIN, 0)

        cast(Any, self.GPIO).cleanup(
            [self.RST_PIN, self.DC_PIN, self.CS_PIN, self.BUSY_PIN], self.PWR_PIN
        )


if sys.version_info[0] == 2:
    process = subprocess.Popen(
        "cat /proc/cpuinfo | grep Raspberry", shell=True, stdout=subprocess.PIPE
    )
else:
    process = subprocess.Popen(
        "cat /proc/cpuinfo | grep Raspberry",
        shell=True,
        stdout=subprocess.PIPE,
        text=True,
    )
output, _ = process.communicate()
if sys.version_info[0] == 2:
    output = output.decode(sys.stdout.encoding)

implementation: Any = None
if "Raspberry" in output:
    implementation = RaspberryPi()
elif os.path.exists("/sys/bus/platform/drivers/gpio-x3"):
    implementation = SunriseX3()
else:
    implementation = JetsonNano()

for func in [x for x in dir(implementation) if not x.startswith("_")]:
    setattr(sys.modules[__name__], func, getattr(implementation, func))

### END OF FILE ###
