import logging
import os
import random
from collections.abc import Mapping
from typing import Any, cast

from PIL import Image, ImageOps

from plugins.base_plugin.base_plugin import BasePlugin, DeviceConfigLike
from plugins.base_plugin.settings_schema import field, option, row, schema, section
from utils.image_loader import (
    FIT_CONTAIN,
    effective_fit_mode,
    resolve_fit_mode,
)
from utils.image_utils import pad_image_blur, resolve_background_color

logger = logging.getLogger(__name__)


def list_files_in_folder(folder_path: str) -> list[str]:
    """Return a list of image file paths in the given folder, excluding hidden files."""
    image_extensions = (
        ".avif",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".tiff",
        ".webp",
        ".heif",
        ".heic",
    )
    return [
        os.path.join(root, f)
        for root, _dirs, files in os.walk(folder_path, followlinks=False)
        for f in files
        if f.lower().endswith(image_extensions) and not f.startswith(".")
    ]


class ImageFolder(BasePlugin):
    def generate_settings_template(self) -> dict[str, object]:
        # JTN-632: Disable the legacy "Style" collapsible. Its hardcoded
        # `backgroundOption` radios collide with the schema-driven Background
        # Fill radio group and cause two options to render as `checked`,
        # leaving the user's Background Fill selection indeterminate.
        template_params = super().generate_settings_template()
        template_params["style_settings"] = False
        return template_params

    def validate_settings(self, settings: Mapping[str, object]) -> str | None:
        """Reject missing/unreadable/empty folder paths at save time.

        Without this, a bad ``folder_path`` persists in config and only
        surfaces later when ``generate_image`` runs — far from where the
        user can fix the typo. See JTN-355.
        """
        raw_folder_path = settings.get("folder_path")
        folder_path = (
            raw_folder_path.strip() if isinstance(raw_folder_path, str) else ""
        )
        if not folder_path:
            return "Folder path is required."
        if not os.path.isdir(folder_path):
            return "Folder does not exist or is not readable."
        if not os.access(folder_path, os.R_OK):
            return "Folder is not readable."
        if not list_files_in_folder(folder_path):
            return "Folder contains no image files."
        return None

    def build_settings_schema(self) -> dict[str, object]:
        return schema(
            section(
                "Source",
                field(
                    "folder_path",
                    label="Folder Path",
                    placeholder="/home/pi/Pictures",
                    required=True,
                    hint="Any nested image files inside this folder are eligible for random selection.",
                ),
            ),
            section(
                "Display",
                row(
                    field(
                        "fitMode",
                        "select",
                        label="Fit",
                        hint=(
                            "Fill crops to fill the screen. Whole image pads the "
                            "leftover space. Auto picks per image: fill when the "
                            "photo and screen share an orientation, whole image "
                            "when they differ."
                        ),
                        default="cover",
                        options=[
                            option("cover", "Fill display"),
                            option("contain", "Whole image"),
                            option("auto", "Auto"),
                        ],
                    ),
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
        )

    def generate_image(
        self, settings: Mapping[str, object], device_config: DeviceConfigLike
    ) -> Image.Image:
        logger.info("=== Image Folder Plugin: Starting image generation ===")

        folder_path = settings.get("folder_path")
        if not isinstance(folder_path, str):
            logger.error("No folder path provided in settings")
            raise RuntimeError("Folder path is required.")

        if not os.path.exists(folder_path):
            logger.error(f"Folder does not exist: {folder_path}")
            raise RuntimeError(f"Folder does not exist: {folder_path}")

        if not os.path.isdir(folder_path):
            logger.error(f"Path is not a directory: {folder_path}")
            raise RuntimeError(f"Path is not a directory: {folder_path}")

        dimensions = self.get_oriented_dimensions(device_config)

        logger.info(f"Scanning folder: {folder_path}")
        image_files = list_files_in_folder(folder_path)

        if not image_files:
            logger.warning(f"No image files found in folder: {folder_path}")
            raise RuntimeError(f"No image files found in folder: {folder_path}")

        logger.debug(f"Found {len(image_files)} image file(s) in folder")
        image_url = random.choice(image_files)
        logger.info(f"Selected random image: {os.path.basename(image_url)}")
        logger.debug(f"Full path: {image_url}")

        # Check padding options
        requested_fit = resolve_fit_mode(settings)
        background_option = settings.get("backgroundOption")
        if not isinstance(background_option, str):
            background_option = "blur"
        logger.debug(
            f"Settings: fit_mode={requested_fit}, background_option={background_option}"
        )

        try:
            # Use adaptive loader for memory-efficient processing
            # Load without auto-resize first to handle padding options
            # Note: Loader automatically handles EXIF orientation correction
            img = cast(Any, self.image_loader).from_file(
                image_url, dimensions, resize=False
            )

            if not img:
                raise RuntimeError("Failed to load image from file")

            # `auto` needs the image's own orientation, so it can only be
            # settled now that the file is open.
            fit_mode = effective_fit_mode(requested_fit, img.size, dimensions)
            if fit_mode == FIT_CONTAIN:
                logger.debug(f"Applying padding with {background_option} background")
                if background_option == "blur":
                    img = pad_image_blur(img, dimensions)
                else:
                    raw_background_color = settings.get("backgroundColor")
                    background_color_value = (
                        raw_background_color
                        if isinstance(raw_background_color, str)
                        else None
                    )
                    background_color = resolve_background_color(
                        background_color_value,
                        img.mode,
                    )
                    img = ImageOps.pad(
                        img,
                        dimensions,
                        color=background_color,
                        method=Image.Resampling.LANCZOS,
                    )
            else:
                # No padding requested, scale to fit dimensions (crop to preserve aspect ratio)
                logger.debug(
                    f"Scaling to fit dimensions: {dimensions[0]}x{dimensions[1]}"
                )
                img = ImageOps.fit(img, dimensions, method=Image.LANCZOS)

            logger.info("=== Image Folder Plugin: Image generation complete ===")
            return img
        except (OSError, ValueError) as e:
            logger.error(f"Error loading image from {image_url}: {e}")
            raise RuntimeError("Failed to load image, please check logs.") from e
