import logging
import os
import random

from PIL import Image, ImageColor, ImageOps

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import field, option, row, schema, section
from utils.image_utils import pad_image_blur

logger = logging.getLogger(__name__)


def _resolve_background_color(
    color_value: str | None, mode: str
) -> tuple[int, ...] | int:
    """Return a safe background color, falling back to white on invalid input."""
    try:
        return ImageColor.getcolor(color_value or "#ffffff", mode)
    except ValueError:
        logger.warning("Invalid background color %r, defaulting to white", color_value)
        return ImageColor.getcolor("#ffffff", mode)


def list_files_in_folder(folder_path):
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
    image_files = [
        os.path.join(root, f)
        for root, _dirs, files in os.walk(folder_path, followlinks=False)
        for f in files
        if f.lower().endswith(image_extensions) and not f.startswith(".")
    ]

    return image_files


class ImageFolder(BasePlugin):
    def generate_settings_template(self):
        # JTN-632: Disable the legacy "Style" collapsible. Its hardcoded
        # `backgroundOption` radios collide with the schema-driven Background
        # Fill radio group and cause two options to render as `checked`,
        # leaving the user's Background Fill selection indeterminate.
        template_params = super().generate_settings_template()
        template_params["style_settings"] = False
        return template_params

    def validate_settings(self, settings: dict) -> str | None:
        """Reject missing/unreadable/empty folder paths at save time.

        Without this, a bad ``folder_path`` persists in config and only
        surfaces later when ``generate_image`` runs — far from where the
        user can fix the typo. See JTN-355.
        """
        folder_path = (settings.get("folder_path") or "").strip()
        if not folder_path:
            return "Folder path is required."
        if not os.path.isdir(folder_path):
            return "Folder does not exist or is not readable."
        if not os.access(folder_path, os.R_OK):
            return "Folder is not readable."
        if not list_files_in_folder(folder_path):
            return "Folder contains no image files."
        return None

    def build_settings_schema(self):
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
                        "padImage",
                        "checkbox",
                        label="Scale to Fit",
                        hint="Keep the full image visible and pad the background instead of cropping to fill the screen.",
                        checked_value="false",
                        unchecked_value="true",
                        submit_unchecked=True,
                    ),
                    field(
                        "backgroundOption",
                        "radio_segment",
                        label="Background",
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

    def generate_image(self, settings, device_config):
        logger.info("=== Image Folder Plugin: Starting image generation ===")

        folder_path = settings.get("folder_path")
        if not folder_path:
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
        use_padding = settings.get("padImage") == "true"
        background_option = settings.get("backgroundOption", "blur")
        logger.debug(
            f"Settings: pad_image={use_padding}, background_option={background_option}"
        )

        try:
            # Use adaptive loader for memory-efficient processing
            # Load without auto-resize first to handle padding options
            # Note: Loader automatically handles EXIF orientation correction
            img = self.image_loader.from_file(image_url, dimensions, resize=False)

            if not img:
                raise RuntimeError("Failed to load image from file")

            if use_padding:
                logger.debug(f"Applying padding with {background_option} background")
                if background_option == "blur":
                    img = pad_image_blur(img, dimensions)
                else:
                    background_color = _resolve_background_color(
                        settings.get("backgroundColor"), img.mode
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
