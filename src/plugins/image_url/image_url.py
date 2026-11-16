import logging
from collections.abc import Mapping

from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin, DeviceConfigLike
from plugins.base_plugin.settings_schema import callout, field, schema, section
from utils.image_utils import fetch_and_resize_remote_image
from utils.safe_fetch import private_feeds_allowed, url_validation_error
from utils.security_utils import validate_url

logger = logging.getLogger(__name__)


def grab_image(
    image_url: str,
    dimensions: tuple[int, int],
    timeout_ms: int = 40000,
    *,
    allow_lan: bool = False,
) -> Image.Image | None:
    """Grab an image from a URL and resize it to the specified dimensions."""
    return fetch_and_resize_remote_image(
        image_url, dimensions, timeout_seconds=timeout_ms / 1000, allow_lan=allow_lan
    )


class ImageURL(BasePlugin):
    def validate_settings(self, settings: Mapping[str, object]) -> str | None:
        """Reject non-URL image URL values at save time."""
        raw = settings.get("url")
        url = (raw or "").strip() if isinstance(raw, str) else ""
        if not url:
            return "Image URL is required."
        try:
            # LAN and Tailscale hosts need the INKYPI_ALLOW_PRIVATE_FEEDS opt-in.
            validate_url(url, allow_lan=private_feeds_allowed())
        except ValueError as err:
            return url_validation_error(err).reason
        return None

    def build_settings_schema(self) -> dict[str, object]:
        return schema(
            section(
                "Source",
                field(
                    "url",
                    "url",
                    label="Image URL",
                    placeholder="https://example.com/image.jpg",
                    pattern="https?://.+",
                    required=True,
                    validation_id="url-error",
                ),
                callout(
                    "Use trusted image URLs only. Remote images can fail if the source is slow, blocked, or returns unsupported formats.",
                    tone="warning",
                ),
            )
        )

    def generate_image(
        self, settings: Mapping[str, object], device_config: DeviceConfigLike
    ) -> Image.Image:
        raw_url = settings.get("url")
        if not isinstance(raw_url, str) or not raw_url:
            raise RuntimeError("URL is required.")
        url = raw_url

        allow_lan = private_feeds_allowed()
        try:
            validate_url(url, allow_lan=allow_lan)
        except ValueError as e:
            # URLValidationError is a PermanentPluginError subclass, so the
            # refresh-task retry loop skips extra attempts (JTN-778) and the
            # plugin blueprint maps it to HTTP 422 validation_error (JTN-776).
            raise url_validation_error(e) from e

        dimensions = self.get_oriented_dimensions(device_config)

        logger.info(f"Grabbing image from: {url}")

        image = grab_image(url, dimensions, timeout_ms=40000, allow_lan=allow_lan)

        if not image:
            raise RuntimeError("Failed to load image, please check logs.")

        return image
