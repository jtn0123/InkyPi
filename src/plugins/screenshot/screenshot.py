import logging

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import callout, field, schema, section
from utils.image_utils import take_screenshot

logger = logging.getLogger(__name__)

class Screenshot(BasePlugin):
    def build_settings_schema(self):
        return schema(
            section(
                "Capture",
                field(
                    "url",
                    label="URL",
                    placeholder="https://example.com",
                    required=True,
                ),
                callout(
                    "Only use trusted URLs. Slow or heavily scripted sites may fail to render before the screenshot timeout.",
                    tone="warning",
                ),
            )
        )

    def generate_image(self, settings, device_config):

        url = settings.get('url')
        if not url:
            raise RuntimeError("URL is required.")

        dimensions = self.get_oriented_dimensions(device_config)

        logger.info(f"Taking screenshot of url: {url}")

        image = take_screenshot(url, dimensions, timeout_ms=40000)

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")

        return image
