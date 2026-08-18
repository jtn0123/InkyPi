import inspect
import logging
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from PIL import Image

from display.abstract_display import AbstractDisplay

logger = logging.getLogger(__name__)
_WAVESHARE_DISPLAY_RE = re.compile(r"^epd[A-Za-z0-9_]+$", re.ASCII)

#: Mode argument for drivers whose ``init``/``Clear`` are mode-driven (epd3in7
#: and relatives).  ``1`` selects 1-bit grayscale, which mirrors the standard
#: single-colour path the rest of this class drives; ``0`` would select the
#: 4-grayscale mode, which needs a different buffer and render method.
_GRAYSCALE_MODE_1BIT = 1

#: ``Clear`` colour byte: all bits set is white on these panels.
_CLEAR_WHITE = 0xFF
_WAVESHARE_MANIFEST = (
    Path(__file__).resolve().parents[2] / "install" / "waveshare-manifest.txt"
)


def _allowed_waveshare_display_types() -> set[str]:
    try:
        names: set[str] = set()
        for line in _WAVESHARE_MANIFEST.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            driver_name = line.split(maxsplit=1)[0]
            if driver_name.endswith(".py") and driver_name != "epdconfig.py":
                names.add(driver_name[:-3])
        return names
    except OSError:
        return set()


def _validate_waveshare_display_type(display_type: str) -> str:
    if not _WAVESHARE_DISPLAY_RE.fullmatch(display_type):
        raise ValueError(f"Unsupported Waveshare display type: {display_type}")
    allowed = _allowed_waveshare_display_types()
    if allowed and display_type not in allowed:
        raise ValueError(f"Unsupported Waveshare display type: {display_type}")
    return display_type


def split_image_for_bi_color_epd(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """
    Convert image into two 1-bit layers for bi-color (black and red) e-paper displays.
    """
    black = (0, 0, 0)
    white = (255, 255, 255)
    red = (255, 0, 0)

    palette_data = [*black, *white, *red]
    palette_img = Image.new("P", (1, 1))
    palette_img.putpalette(palette_data)

    # Quantize with an RGB source image; mode "1" and some others are not
    # compatible with palette quantization in all Pillow versions.
    source = image.convert("RGB") if image.mode != "RGB" else image
    indexed_img = source.quantize(
        palette=palette_img,
        dither=Image.Dither.FLOYDSTEINBERG,
    )
    black_layer = indexed_img.point(lambda p: 0 if p == 0 else 1, mode="1")
    red_layer = indexed_img.point(lambda p: 0 if p == 2 else 1, mode="1")
    return black_layer, red_layer


def _requires_mode_argument(method: Callable[..., Any]) -> bool:
    """Whether *method* takes a required ``mode`` parameter.

    Distinguishes the mode-driven drivers (``init(self, mode)``) from the
    common ``init(self)`` shape.  A ``mode`` parameter carrying a default does
    not count — those drivers work unchanged when called with no arguments.
    Signatures that cannot be introspected are treated as the common shape, so
    an exotic driver degrades to today's behaviour rather than failing here.
    """
    try:
        parameter = inspect.signature(method).parameters.get("mode")
    except (TypeError, ValueError):
        return False
    return parameter is not None and parameter.default is inspect.Parameter.empty


class WaveshareDisplay(AbstractDisplay):
    """
    Handles Waveshare e-paper display dynamically based on device type.

    This class loads the appropriate display driver dynamically based on the
    `display_type` specified in the device configuration, allowing support for
    multiple Waveshare EPD models.

    The module drivers are in display.waveshare_epd.
    """

    def initialize_display(self) -> None:
        """
        Initializes the Waveshare display device.

        Retrieves the display type from the device configuration and dynamically
        loads the corresponding Waveshare EPD driver from display.waveshare_epd.

        Raises:
            ValueError: If `display_type` is missing or the specified module is
                        not found.
        """

        logger.info("Initializing Waveshare display")

        # get the device type which should be the model number of the device.
        display_type_raw = self.device_config.get_config("display_type")
        display_type = str(display_type_raw or "")
        logger.info(f"Loading EPD display for {display_type} display")

        if not display_type:
            raise ValueError(
                "Waveshare driver but 'display_type' not specified in configuration."
            )

        safe_display_type = _validate_waveshare_display_type(display_type)
        module_name = f"display.waveshare_epd.{safe_display_type}"

        # Workaround for some Waveshare drivers using 'import epdconfig' causing import errors
        epd_dir = Path(__file__).parent / "waveshare_epd"
        if str(epd_dir) not in sys.path:
            sys.path.insert(0, str(epd_dir))

        try:
            epd_module = __import__(module_name, fromlist=["EPD"])
            self.epd_display: Any = epd_module.EPD()
            # Workaround for init functions with inconsistent casing
            init_method = getattr(self.epd_display, "Init", None)
            if not callable(init_method):
                init_method = getattr(self.epd_display, "init", None)
            if not callable(init_method):
                raise AttributeError("No Init/init method found")

            # Some drivers (epd3in7 and relatives) are mode-driven: init() and
            # Clear() take a required mode argument and there is no generic
            # display() — only display_1Gray/display_4Gray.  Calling them the
            # usual way raises TypeError, which is not one of the errors caught
            # below, so the panel failed with a confusing traceback despite
            # being listed in the driver manifest.
            self.grayscale_mode_display: bool = _requires_mode_argument(init_method)
            if self.grayscale_mode_display:
                mode_init = cast(Callable[[int], None], init_method)

                def init_in_grayscale_mode() -> None:
                    mode_init(_GRAYSCALE_MODE_1BIT)

                self.epd_display_init: Callable[[], None] = init_in_grayscale_mode
            else:
                self.epd_display_init = cast(Callable[[], None], init_method)
            self.epd_display_init()

            if self.grayscale_mode_display:
                # Mode-driven drivers render a single colour plane.
                self.bi_color_display: bool = False
            else:
                display_args_spec = inspect.getfullargspec(self.epd_display.display)
                self.bi_color_display = len(display_args_spec.args) > 2
        except ModuleNotFoundError:
            raise ValueError(
                f"Unsupported Waveshare display type: {display_type}"
            ) from None
        except AttributeError:
            raise ValueError(
                f"Display does not support required methods: {display_type}"
            ) from None

        # update the resolution directly from the loaded device context
        if not self.device_config.get_config("resolution"):
            w, h = int(self.epd_display.width), int(self.epd_display.height)
            resolution = [w, h] if w >= h else [h, w]
            self.device_config.update_value("resolution", resolution, write=True)

    def _clear_display(self) -> None:
        """Clear residual pixels, tolerating each driver's ``Clear`` signature.

        The common shape is ``Clear()``; some take a colour byte, and the
        mode-driven drivers take ``Clear(color, mode)``.  Passing the arguments
        each one actually declares avoids a TypeError on the panels that differ.
        """
        clear = self.epd_display.Clear
        if self.grayscale_mode_display:
            clear(_CLEAR_WHITE, _GRAYSCALE_MODE_1BIT)
            return
        try:
            required = [
                parameter
                for parameter in inspect.signature(clear).parameters.values()
                if parameter.default is inspect.Parameter.empty
                and parameter.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            ]
        except (TypeError, ValueError):
            required = []
        if required:
            clear(_CLEAR_WHITE)
        else:
            clear()

    def display_image(
        self, image: Image.Image, image_settings: list[object] | None = None
    ) -> None:
        if image_settings is None:
            image_settings = []

        """
        Displays an image on the Waveshare display.

        The image has been processed by adjusting orientation, resizing, and converting it
        into the buffer format required for e-paper rendering.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): Additional settings to modify image rendering.

        Raises:
            ValueError: If no image is provided.
        """

        logger.info("Displaying image to Waveshare display.")
        if image is None:
            raise ValueError("No image provided.")

        # Assume device was in sleep mode.
        self.epd_display_init()

        # Clear residual pixels before updating the image.
        self._clear_display()

        # Display the image on the WS display.
        if self.grayscale_mode_display:
            # No generic display() on these drivers — 1-bit grayscale is the
            # equivalent of the standard single-colour path.
            self.epd_display.display_1Gray(self.epd_display.getbuffer(image))
        elif not self.bi_color_display:
            self.epd_display.display(self.epd_display.getbuffer(image))
        else:
            black_layer, red_layer = split_image_for_bi_color_epd(image)

            self.epd_display.display(
                self.epd_display.getbuffer(black_layer),
                self.epd_display.getbuffer(red_layer),
            )

        # Put device into low power mode (EPD displays maintain image when powered off)
        logger.info("Putting Waveshare display into sleep mode for power saving.")
        self.epd_display.sleep()
