import logging

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import callout, field, schema, section
from utils.image_utils import take_screenshot
from utils.plugin_errors import PermanentPluginError
from utils.security_utils import validate_url

logger = logging.getLogger(__name__)


class Screenshot(BasePlugin):
    def validate_settings(self, settings: dict) -> str | None:
        """Reject non-http(s) URLs at save time to prevent unsafe values persisting."""
        url = settings.get("url", "").strip()
        if not url:
            return "URL is required."
        try:
            validate_url(url)
        except ValueError as e:
            return f"Invalid URL: {e}"
        return None

    def build_settings_schema(self):
        return schema(
            section(
                "Capture",
                field(
                    "url",
                    "url",
                    label="URL",
                    placeholder="https://example.com",
                    pattern="https?://.*",
                    required=True,
                ),
                callout(
                    "Only use trusted URLs. Slow or heavily scripted sites may fail to render before the screenshot timeout.",
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
            # Permanent: bad scheme, SSRF-blocked address, or malformed URL.
            # Tell refresh_task not to retry — the URL will fail identically
            # on every subsequent attempt (JTN-778).
            raise PermanentPluginError(f"Invalid URL: {e}") from e

        dimensions = self.get_oriented_dimensions(device_config)

        safe_url = url.replace("\n", "").replace("\r", "")
        logger.info("Taking screenshot of url: %s", safe_url)

        image = take_screenshot(url, dimensions, timeout_ms=40000)

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")

        return image
