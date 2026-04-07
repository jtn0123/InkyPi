import logging

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import callout, field, schema, section
from utils.image_utils import fetch_and_resize_remote_image
from utils.security_utils import validate_url

logger = logging.getLogger(__name__)


def grab_image(image_url, dimensions, timeout_ms=40000):
    """Grab an image from a URL and resize it to the specified dimensions."""
    return fetch_and_resize_remote_image(
        image_url, dimensions, timeout_seconds=timeout_ms / 1000
    )


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
        url = settings.get("url")
        if not url:
            raise RuntimeError("URL is required.")

        try:
            validate_url(url)
        except ValueError as e:
            raise RuntimeError(f"Invalid URL: {e}") from e

        dimensions = self.get_oriented_dimensions(device_config)

        logger.info(f"Grabbing image from: {url}")

        image = grab_image(url, dimensions, timeout_ms=40000)

        if not image:
            raise RuntimeError("Failed to load image, please check logs.")

        return image
