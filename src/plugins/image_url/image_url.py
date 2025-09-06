import logging
from io import BytesIO

import requests
from PIL import Image
from PIL.Image import Resampling

from plugins.base_plugin.base_plugin import BasePlugin

LANCZOS = Resampling.LANCZOS

logger = logging.getLogger(__name__)

def grab_image(image_url, dimensions, timeout_ms=40000):
    """Grab an image from a URL and resize it to the specified dimensions."""
    try:
        response = requests.get(image_url, timeout=timeout_ms / 1000)
        response.raise_for_status()
        with Image.open(BytesIO(response.content)) as _img:
            img = _img.resize(dimensions, LANCZOS)
            return img
    except Exception as e:
        logger.error(f"Error grabbing image from {image_url}: {e}")
        return None

class ImageURL(BasePlugin):
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