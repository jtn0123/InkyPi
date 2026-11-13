"""Output validation utilities for plugin-generated images."""

from __future__ import annotations

import logging
from typing import Protocol

from PIL import Image

logger = logging.getLogger(__name__)

#: Relative aspect-ratio difference below which a wrong-size image is simply
#: resized. Two percent is invisible on a photo, and it covers the usual
#: off-by-a-few-pixels rounding a plugin makes when it scales by hand.
SAME_RATIO_TOLERANCE = 0.02

#: Fallback source-size ceiling if Pillow's decompression-bomb limit has been
#: switched off (``Image.MAX_IMAGE_PIXELS = None``). Matches Pillow's default.
_DEFAULT_MAX_FIT_PIXELS = 89_478_485


class SupportsResolution(Protocol):
    """Device-config surface needed to work out the plugin canvas size."""

    def get_resolution(self) -> tuple[int, int]: ...

    def get_config(self, key: str, default: object = ...) -> object: ...


class OutputDimensionMismatch(Exception):
    """Raised when a plugin returns an image with unexpected dimensions.

    Attributes:
        plugin_id: The identifier of the offending plugin.
        expected: The (width, height) expected from device.json.
        actual: The (width, height) of the image that was returned.
    """

    def __init__(
        self,
        plugin_id: str,
        expected: tuple[int, int],
        actual: tuple[int, int],
    ) -> None:
        self.plugin_id = plugin_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Plugin '{plugin_id}' returned image with wrong dimensions: "
            f"expected {expected[0]}x{expected[1]}, got {actual[0]}x{actual[1]}"
        )


def validate_image_dimensions(
    image: Image.Image,
    expected_width: int,
    expected_height: int,
    plugin_id: str = "<unknown>",
    *,
    auto_rotate: bool = True,
) -> Image.Image:
    """Validate that *image* matches the expected display resolution.

    Parameters
    ----------
    image:
        A ``PIL.Image.Image`` object returned by a plugin.
    expected_width:
        The display width taken from device.json (pixels).
    expected_height:
        The display height taken from device.json (pixels).
    plugin_id:
        Human-readable plugin identifier used in error messages.
    auto_rotate:
        When ``True`` (default), attempt a 90-degree rotation if the image
        dimensions are transposed (i.e., actual width == expected height and
        actual height == expected width).  If the rotation fixes the mismatch
        the corrected image is returned without raising.  Set to ``False`` to
        disable this behaviour.

    Returns
    -------
    image
        The original image if dimensions match, or a rotated copy if
        ``auto_rotate=True`` and the transposed dimensions match.

    Raises
    ------
    OutputDimensionMismatch
        If the image dimensions do not match the expected values (and cannot
        be corrected by rotation when ``auto_rotate=True``).
    """
    actual_width, actual_height = image.size

    if actual_width == expected_width and actual_height == expected_height:
        return image

    # Check whether a 90-degree rotation would fix the mismatch.
    if (
        auto_rotate
        and actual_width == expected_height
        and actual_height == expected_width
    ):
        logger.info(
            "output_validator: auto-rotating image for plugin '%s' "
            "(%dx%d -> %dx%d to match display resolution %dx%d)",
            plugin_id,
            actual_width,
            actual_height,
            actual_height,
            actual_width,
            expected_width,
            expected_height,
        )
        return image.rotate(90, expand=True)

    raise OutputDimensionMismatch(
        plugin_id=plugin_id,
        expected=(expected_width, expected_height),
        actual=(actual_width, actual_height),
    )


def oriented_resolution(device_config: SupportsResolution) -> tuple[int, int]:
    """Return the panel (width, height) a plugin is expected to render at.

    Plugins draw in the user's orientation (portrait when ``orientation`` is
    ``vertical``); the display manager rotates the frame afterwards. This is
    the same rule as ``BasePlugin.get_oriented_dimensions``.
    """
    width, height = device_config.get_resolution()
    if device_config.get_config("orientation") == "vertical":
        return int(height), int(width)
    return int(width), int(height)


def max_fit_source_pixels() -> int:
    """Largest source image :func:`fit_image_to_panel` will resample.

    Reuses Pillow's own decompression-bomb limit, which every decode in the
    app is already held to, so fitting never accepts a frame that loading the
    same picture from disk would have refused.
    """
    limit = Image.MAX_IMAGE_PIXELS
    return int(limit) if limit else _DEFAULT_MAX_FIT_PIXELS


def fit_image_to_panel(
    image: Image.Image,
    expected_width: int,
    expected_height: int,
    plugin_id: str = "<unknown>",
) -> Image.Image:
    """Return *image* at exactly the panel size, fitting it if it is not.

    A correctly sized (or exactly transposed) image goes through
    :func:`validate_image_dimensions` unchanged. Anything else is a plugin bug,
    but not one worth blanking the plugin over: the image is scaled to the
    panel and a WARNING names the plugin so the bug stays visible.

    * Aspect ratio within :data:`SAME_RATIO_TOLERANCE` of the panel: a plain
      high-quality resize.
    * Otherwise: scaled to fit inside the panel and centred on white, so no
      content is cropped.

    Raises
    ------
    OutputDimensionMismatch
        If the image cannot sensibly be fitted: an empty image, an empty
        target, or a source larger than :func:`max_fit_source_pixels`.
    """
    try:
        return validate_image_dimensions(
            image, expected_width, expected_height, plugin_id=plugin_id
        )
    except OutputDimensionMismatch as mismatch:
        actual_width, actual_height = mismatch.actual
        if min(actual_width, actual_height, expected_width, expected_height) <= 0:
            raise
        if actual_width * actual_height > max_fit_source_pixels():
            logger.error(
                "output_validator: plugin '%s' returned a %dx%d image, larger "
                "than the %d-pixel limit; refusing to resample it",
                plugin_id,
                actual_width,
                actual_height,
                max_fit_source_pixels(),
            )
            raise
        fitted, how = _fit(image, (expected_width, expected_height))
        logger.warning(
            "output_validator: plugin '%s' returned %dx%d for a %dx%d panel; "
            "%s to fit. The image is shown, but the plugin should render at "
            "the panel size.",
            plugin_id,
            actual_width,
            actual_height,
            expected_width,
            expected_height,
            how,
        )
        return fitted


def fit_image_to_device(
    image: Image.Image, device_config: SupportsResolution, plugin_id: str
) -> Image.Image:
    """:func:`fit_image_to_panel` against *device_config*'s oriented panel size.

    For the direct-render paths (manual "Update now" and "Display next" with no
    refresh task) so they treat a wrong-size image exactly as the refresh task
    does.
    """
    width, height = oriented_resolution(device_config)
    return fit_image_to_panel(image, width, height, plugin_id=plugin_id)


def _fit(image: Image.Image, size: tuple[int, int]) -> tuple[Image.Image, str]:
    """Scale *image* to *size*; returns the image and how it was fitted."""
    target_width, target_height = size
    width, height = image.size
    source_ratio = width / height
    target_ratio = target_width / target_height

    # ``reducing_gap`` lets Pillow shrink by an integer factor first, so a
    # multi-megapixel source never needs a full-resolution LANCZOS pass.
    if abs(source_ratio / target_ratio - 1) <= SAME_RATIO_TOLERANCE:
        resized = image.resize(size, Image.Resampling.LANCZOS, reducing_gap=3.0)
        return resized, "resized"

    # Same treatment the image plugins give "Whole image" with a colour
    # background: contain-scale and centre on white.
    from PIL import ImageOps

    from utils.image_utils import resolve_background_color

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    padded = ImageOps.pad(
        image,
        size,
        method=Image.Resampling.LANCZOS,
        color=resolve_background_color(None, image.mode),
    )
    return padded, "padded"
