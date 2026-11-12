import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

import numpy as np
from PIL import Image

from display.abstract_display import AbstractDisplay
from display.crisp import crisp_image

logger = logging.getLogger(__name__)

Colour = tuple[int, int, int]


@dataclass(frozen=True)
class _Handoff:
    """How to give a colour Inky driver a frame it will show without dithering.

    ``palette`` holds the driver's pure colours in its own order (taken from
    its ``DESATURATED_PALETTE``); ``measured`` the matching
    ``SATURATED_PALETTE`` entries it blends with when it dithers.
    """

    kind: Literal["palette", "index"]
    palette: tuple[Colour, ...]
    measured: tuple[Colour, ...]


# Drivers whose set_image() was read and checked (inky 2.6.0) for an
# undithered path, and how many colours they have:
#   "palette": a mode-P image whose palette holds exactly the driver's pure
#              colours is mapped to them with Image.Dither.NONE.
#   "index":   a mode-P image is copied to the panel buffer as raw colour
#              indexes, in DESATURATED_PALETTE order.
# Anything else (mono pHAT/wHAT, unknown or future drivers) keeps the
# driver's own dithered conversion.
_HANDOFFS: dict[str, tuple[Literal["palette", "index"], int]] = {
    "inky.inky_e673": ("palette", 6),
    "inky.inky_e640": ("palette", 6),
    "inky.inky_el133uf1": ("palette", 6),
    "inky.inky_jd79661": ("palette", 4),
    "inky.inky_jd79668": ("palette", 4),
    "inky.inky_ssd2683": ("palette", 4),
    "inky.inky_uc8159": ("index", 7),
    "inky.inky_ac073tc1a": ("index", 7),
}


def _colours(raw: object, count: int) -> tuple[Colour, ...]:
    rows = list(cast(Any, raw))[:count]
    return tuple((int(r), int(g), int(b)) for r, g, b in rows)


class InkyDisplay(AbstractDisplay):
    """
    Handles the Inky e-paper display.

    This class initializes and manages interactions with the Inky display,
    ensuring proper image rendering and configuration storage.

    The Inky display driver supports auto configuration.
    """

    def initialize_display(self) -> None:
        """
        Initializes the Inky display device.

        Sets the display border and stores the display resolution in the device configuration.

        Raises:
            ValueError: If the resolution cannot be retrieved or stored.
        """

        from inky.auto import auto

        self.inky_display = auto()
        self.inky_display.set_border(self.inky_display.BLACK)

        # store display resolution in device config
        if not self.device_config.get_config("resolution"):
            self.device_config.update_value(
                "resolution",
                [int(self.inky_display.width), int(self.inky_display.height)],
                write=True,
            )

    def _saturation(self) -> float:
        image_settings_cfg = self.device_config.get_config("image_settings")
        if not isinstance(image_settings_cfg, Mapping):
            return 0.5
        raw = image_settings_cfg.get("inky_saturation", 0.5)
        return float(raw) if isinstance(raw, int | float) else 0.5

    def _handoff(self) -> _Handoff | None:
        """Describe the driver's undithered path, or None if it has none we trust."""
        driver: Any = getattr(self, "inky_display", None)
        entry = _HANDOFFS.get(type(driver).__module__)
        if entry is None:
            return None
        kind, count = entry
        try:
            pure = _colours(driver.DESATURATED_PALETTE, count)
            measured = _colours(driver.SATURATED_PALETTE, count)
        except (AttributeError, TypeError, ValueError):
            return None
        if (
            len(set(pure)) != count
            or len(measured) != count
            or (0, 0, 0) not in pure
            or (255, 255, 255) not in pure
        ):
            return None
        return _Handoff(kind, pure, measured)

    def crisp_frame(self, image: Image.Image) -> Image.Image | None:
        """Convert rendered UI to this panel's pure colours without dithering.

        Returns None when the driver has no verified undithered path, so the
        caller keeps the normal (dithered) frame.
        """
        handoff = self._handoff()
        if handoff is None:
            return None
        # Photo regions inside the frame are dithered against the same blend
        # of pure and measured colours the driver itself would use.
        sat = self._saturation()
        blend = [
            tuple(
                int(m * sat + p * (1.0 - sat)) for m, p in zip(meas, pure, strict=True)
            )
            for meas, pure in zip(handoff.measured, handoff.palette, strict=True)
        ]
        return crisp_image(image, handoff.palette, blend)

    def _undithered(self, image: Image.Image) -> Image.Image | None:
        """Return a mode-P frame the driver shows as-is, if *image* allows it.

        Only frames made entirely of the panel's pure colours qualify: crisp
        frames, and the saved copies of them that history redisplay and
        "restore last frame" push again. Everything else returns None.
        """
        handoff = self._handoff()
        if handoff is None:
            return None
        rgb = image.convert("RGB")
        colours = rgb.getcolors(len(handoff.palette))
        if colours is None or any(c not in handoff.palette for _n, c in colours):
            return None
        pixels = np.asarray(rgb, dtype=np.uint32)
        packed = (pixels[..., 0] << 16) | (pixels[..., 1] << 8) | pixels[..., 2]
        pal_packed = np.array([(r << 16) | (g << 8) | b for r, g, b in handoff.palette])
        order = np.argsort(pal_packed)
        indices = order[np.searchsorted(pal_packed[order], packed)].astype(np.uint8)
        frame = Image.fromarray(indices, "P")
        frame.putpalette(bytes(v for colour in handoff.palette for v in colour))
        return frame

    def display_image(
        self, image: Image.Image, image_settings: list[object] | None = None
    ) -> None:
        """
        Displays the provided image on the Inky display.

        The image has been processed by adjusting orientation and resizing
        before being sent to the display. A frame made only of the panel's
        pure colours (see :meth:`crisp_frame`) is handed over in the driver's
        undithered form; anything else goes through the driver's own
        dithered conversion.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): Additional settings to modify image rendering.

        Raises:
            ValueError: If no image is provided.
        """
        logger.info("Displaying image to Inky display.")
        if image is None:
            raise ValueError("No image provided.")

        inky_saturation = self._saturation()
        logger.info("Inky Saturation: %s", inky_saturation)
        frame = self._undithered(image)
        if frame is not None:
            logger.info("Inky: frame uses only panel colours; sending undithered")
            image = frame
        try:
            self.inky_display.set_image(image, saturation=inky_saturation)
        except TypeError as exc:
            msg = str(exc)
            if "saturation" not in msg or "unexpected keyword argument" not in msg:
                raise
            # Backward compatibility with drivers/mocks that do not support saturation kwarg.
            self.inky_display.set_image(image)
        self.inky_display.show()
