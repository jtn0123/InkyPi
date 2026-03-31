import logging
import os
import random

from PIL import Image, ImageColor, ImageOps

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import (
    field,
    option,
    row,
    schema,
    section,
    widget,
)
from utils.image_utils import pad_image_blur

logger = logging.getLogger(__name__)


class ImageUpload(BasePlugin):
    def build_settings_schema(self):
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
                            option("color", "Solid Color"),
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

    def open_image(self, img_index: int, image_locations: list) -> Image:
        if not image_locations:
            raise RuntimeError("No images provided.")
        # Open the image using Pillow
        try:
            with Image.open(image_locations[img_index]) as img:
                image = img.copy()
        except Exception as e:
            logger.error(f"Failed to read image file: {str(e)}")
            raise RuntimeError("Failed to read image file.") from e
        return image

    def generate_image(self, settings, device_config) -> Image:
        # Get the current index from the device json
        img_index = settings.get("image_index", 0)
        image_locations = settings.get("imageFiles[]")

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

        # Write the new index back ot the device json
        settings["image_index"] = img_index
        if settings.get("padImage") == "true":
            dimensions = self.get_oriented_dimensions(device_config)

            if settings.get("backgroundOption") == "blur":
                return pad_image_blur(image, dimensions)
            else:
                background_color = ImageColor.getcolor(
                    settings.get("backgroundColor") or "#ffffff", "RGB"
                )
                return ImageOps.pad(
                    image,
                    dimensions,
                    color=background_color,
                    method=Image.Resampling.LANCZOS,
                )
        return image

    def cleanup(self, settings):
        """Delete all uploaded image files associated with this plugin instance."""
        image_locations = settings.get("imageFiles[]", [])
        if not image_locations:
            return

        for image_path in image_locations:
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                    logger.info(f"Deleted uploaded image: {image_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete uploaded image {image_path}: {e}")
