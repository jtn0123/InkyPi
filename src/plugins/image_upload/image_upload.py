import logging
import os
import random
from collections.abc import Mapping
from typing import Any, cast

from PIL import Image, ImageColor, ImageOps

from plugins.base_plugin.base_plugin import BasePlugin, DeviceConfigLike
from plugins.base_plugin.settings_schema import (
    field,
    option,
    row,
    schema,
    section,
    widget,
)
from utils.app_utils import resolve_path
from utils.image_utils import pad_image_blur
from utils.security_utils import validate_file_path

logger = logging.getLogger(__name__)


def _get_upload_dir() -> str:
    return cast(str, cast(Any, resolve_path)(os.path.join("static", "images", "saved")))


def _resolve_background_color(
    color_value: str | None, mode: str
) -> tuple[int, ...] | int:
    """Return a safe background color, falling back to white on invalid input."""
    try:
        return cast(
            tuple[int, ...] | int, ImageColor.getcolor(color_value or "#ffffff", mode)
        )
    except ValueError:
        logger.warning("Invalid background color %r, defaulting to white", color_value)
        return cast(tuple[int, ...] | int, ImageColor.getcolor("#ffffff", mode))


class ImageUpload(BasePlugin):
    def generate_settings_template(self) -> dict[str, object]:
        # JTN-632: Disable the legacy "Style" collapsible. Its hardcoded
        # `backgroundOption` radios collide with the schema-driven Background
        # Fill radio group and cause two options to render as `checked`,
        # leaving the user's Background Fill selection indeterminate.
        template_params = super().generate_settings_template()
        template_params["style_settings"] = False
        return template_params

    def build_settings_schema(self) -> dict[str, object]:
        return schema(
            section(
                "Display Options",
                row(
                    field(
                        "padImage",
                        "checkbox",
                        label="Scale to Fit",
                        hint="Pad smaller images to match the display aspect ratio.",
                        checked_value="false",
                        unchecked_value="true",
                        submit_unchecked=True,
                    ),
                    field(
                        "randomize",
                        "checkbox",
                        label="Random Order",
                        hint="Shuffle uploaded images during playback.",
                        checked_value="true",
                        unchecked_value="false",
                        submit_unchecked=True,
                    ),
                ),
                row(
                    field(
                        "backgroundOption",
                        "radio_segment",
                        label="Background Fill",
                        default="blur",
                        options=[
                            option("blur", "Blur"),
                            option("color", "Color"),
                        ],
                    ),
                    field(
                        "backgroundColor",
                        "color",
                        label="Background Color",
                        default="#ffffff",
                        visible_if={"field": "backgroundOption", "equals": "color"},
                    ),
                ),
            ),
            section(
                "Images",
                widget("image-upload-list", template="widgets/image_upload_list.html"),
            ),
        )

    def open_image(self, img_index: int, image_locations: list[str]) -> Image:
        if not image_locations:
            raise RuntimeError("No images provided.")

        image_path = image_locations[img_index]
        try:
            image_path = validate_file_path(image_path, _get_upload_dir())
        except ValueError:
            logger.error("Image path outside allowed directory: %s", image_path)
            raise RuntimeError("Invalid image file path.") from None

        # Open the image using Pillow
        try:
            with Image.open(image_path) as img:
                image = img.copy()
        except (OSError, ValueError) as e:
            logger.error("Failed to read image file: %s", e)
            raise RuntimeError("Failed to read image file.") from e
        return image

    def generate_image(
        self, settings: Mapping[str, object], device_config: DeviceConfigLike
    ) -> Image:
        # Get the current index from the device json
        img_index_raw = settings.get("image_index")
        img_index = img_index_raw if isinstance(img_index_raw, int) else 0
        raw_image_locations = settings.get("imageFiles[]")
        image_locations = (
            cast(list[str], raw_image_locations)
            if isinstance(raw_image_locations, list)
            else []
        )

        if not image_locations:
            raise RuntimeError("No images provided.")

        if img_index >= len(image_locations):
            # Prevent Index out of range issues when file list has changed
            img_index = 0

        if settings.get("randomize") == "true":
            img_index = random.randrange(0, len(image_locations))
            image = self.open_image(img_index, image_locations)
        else:
            image = self.open_image(img_index, image_locations)
            img_index = (img_index + 1) % len(image_locations)

        # Write the new index back to the device json
        if isinstance(settings, dict):
            settings["image_index"] = img_index
        if settings.get("padImage") == "true":
            dimensions = self.get_oriented_dimensions(device_config)

            if settings.get("backgroundOption") == "blur":
                return pad_image_blur(image, dimensions)
            raw_background_color = settings.get("backgroundColor")
            background_color_value = (
                raw_background_color if isinstance(raw_background_color, str) else None
            )
            background_color = _resolve_background_color(
                background_color_value,
                "RGB",
            )
            return ImageOps.pad(
                image,
                dimensions,
                color=background_color,
                method=Image.Resampling.LANCZOS,
            )
        return image

    def cleanup(self, settings: Mapping[str, object]) -> None:
        """Delete all uploaded image files associated with this plugin instance."""
        raw_image_locations = settings.get("imageFiles[]", [])
        image_locations = (
            cast(list[str], raw_image_locations)
            if isinstance(raw_image_locations, list)
            else []
        )
        if not image_locations:
            return

        for image_path in image_locations:
            try:
                safe_path = validate_file_path(image_path, _get_upload_dir())
            except ValueError:
                logger.warning(
                    "Skipping cleanup of path outside upload dir: %s", image_path
                )
                continue
            if os.path.exists(safe_path):
                try:
                    os.remove(safe_path)
                    logger.info("Deleted uploaded image: %s", safe_path)
                except OSError as e:
                    logger.warning(
                        "Failed to delete uploaded image %s: %s", safe_path, e
                    )
