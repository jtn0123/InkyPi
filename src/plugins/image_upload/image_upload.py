import logging
import random

from PIL import Image, ImageColor, ImageOps
from PIL.Image import Resampling

from plugins.base_plugin.base_plugin import BasePlugin
from utils.image_utils import load_image_from_path

LANCZOS = Resampling.LANCZOS

logger = logging.getLogger(__name__)


class ImageUpload(BasePlugin):
    def open_image(self, img_index: int, image_locations: list[str]) -> Image.Image:
        if not image_locations:
            raise RuntimeError("No images provided.")
        # Open the image using Pillow
        try:
            # Use standardized helper to release file handle
            image = load_image_from_path(image_locations[img_index])
            if image is None:
                raise RuntimeError("Failed to read image file")
        except Exception as e:
            logger.error(f"Failed to read image file: {str(e)}")
            raise RuntimeError("Failed to read image file.")
        # mypy may infer Any from Image.open; assert Image.Image for clarity
        if not isinstance(image, Image.Image):
            raise RuntimeError("Invalid image type loaded.")
        return image

    def generate_image(self, settings, device_config) -> Image.Image:

        # Get the current index from the device json
        img_index = settings.get("image_index", 0)
        image_locations = settings.get("imageFiles[]") or []

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

        ###
        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        if settings.get("padImage") == "true":
            frame_ratio = dimensions[0] / dimensions[1]
            img_width, img_height = image.size
            padded_img_size = (
                int(img_height * frame_ratio) if img_width >= img_height else img_width,
                img_height if img_width >= img_height else int(img_width / frame_ratio),
            )
            background_color = ImageColor.getcolor(
                settings.get("backgroundColor") or (255, 255, 255), "RGB"
            )
            return ImageOps.pad(
                image, padded_img_size, color=background_color, method=LANCZOS
            )
        else:
            # Contain within target dimensions without padding
            contained = ImageOps.contain(image, dimensions, LANCZOS)
            return contained if contained is not None else image
