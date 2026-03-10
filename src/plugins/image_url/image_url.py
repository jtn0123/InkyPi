import logging
from io import BytesIO

import requests
from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import callout, field, schema, section

logger = logging.getLogger(__name__)

def grab_image(image_url, dimensions, timeout_ms=40000):
    """Grab an image from a URL and resize it to the specified dimensions."""
    try:
        response = requests.get(image_url, timeout=timeout_ms / 1000)
        response.raise_for_status()
        with Image.open(BytesIO(response.content)) as img:
            resized = img.resize(dimensions, Image.LANCZOS)
            return resized.copy()
    except Exception as e:
        logger.error(f"Error grabbing image from {image_url}: {e}")
        return None


class ImageURL(BasePlugin):
    def build_settings_schema(self):
        return schema(
            section(
                "Source",
                field(
                    "url",
                    label="Image URL",
                    placeholder="https://example.com/image.jpg",
                    required=True,
                ),
                callout(
                    "Use trusted image URLs only. Remote images can fail if the source is slow, blocked, or returns unsupported formats.",
                    tone="warning",
                ),
            )
        )

    def generate_image(self, settings, device_config):
        url = settings.get('url')
        if not url:
            raise RuntimeError("URL is required.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        logger.info(f"Grabbing image from: {url}")

        image = grab_image(url, dimensions, timeout_ms=40000)

        if not image:
            raise RuntimeError("Failed to load image, please check logs.")

        return image
