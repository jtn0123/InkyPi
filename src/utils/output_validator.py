"""Output validation utilities for plugin-generated images."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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
    image,
    expected_width: int,
    expected_height: int,
    plugin_id: str = "<unknown>",
    *,
    auto_rotate: bool = True,
) -> object:
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
