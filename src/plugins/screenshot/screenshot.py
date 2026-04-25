import logging
from collections.abc import Mapping
from typing import Any, cast

from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import callout, field, schema, section
from utils.image_utils import take_screenshot
from utils.security_utils import URLValidationError, validate_url

logger = logging.getLogger(__name__)


class Screenshot(BasePlugin):  # type: ignore[misc, unused-ignore]
    def validate_settings(self, settings: Mapping[str, object]) -> str | None:
        """Reject non-http(s) URLs at save time to prevent unsafe values persisting."""
        raw_url = settings.get("url", "")
        url = raw_url.strip() if isinstance(raw_url, str) else ""
        if not url:
            return "URL is required."
        try:
            validate_url(url)
        except ValueError as e:
            return f"Invalid URL: {e}"
        return None

    def build_settings_schema(self) -> dict[str, object]:
        return cast(  # type: ignore[redundant-cast, unused-ignore]
            dict[str, object],
            schema(
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
            ),
        )

    def generate_image(
        self, settings: Mapping[str, object], device_config: Any
    ) -> Image.Image:

        url = settings.get("url")
        if not isinstance(url, str):
            url = ""
        if not url:
            raise RuntimeError("URL is required.")

        try:
            validate_url(url)
        except ValueError as e:
            # URLValidationError is a PermanentPluginError subclass, so the
            # refresh-task retry loop skips extra attempts (JTN-778) and the
            # plugin blueprint maps it to HTTP 422 validation_error (JTN-776).
            raise URLValidationError(f"Invalid URL: {e}") from e

        dimensions = self.get_oriented_dimensions(device_config)

        safe_url = url.replace("\n", "").replace("\r", "")
        logger.info("Taking screenshot of url: %s", safe_url)

        image = cast(Any, take_screenshot)(url, dimensions, timeout_ms=40000)

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")

        return image
