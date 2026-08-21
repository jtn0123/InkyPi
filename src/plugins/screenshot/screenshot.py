import logging
from collections.abc import Mapping
from typing import Any, cast

from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import callout, field, schema, section
from utils.image_utils import take_screenshot
from utils.security_utils import URLValidationError, validate_url

logger = logging.getLogger(__name__)

#: Upper bound on the virtual-time budget handed to chromium. Virtual time is
#: cheap, but an unbounded budget still lets a page with a runaway timer hold
#: the subprocess open until the screenshot timeout kills it.
_MAX_RENDER_WAIT_MS = 30_000


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
                    field(
                        "renderWaitMs",
                        "number",
                        label="Render wait (ms)",
                        hint=(
                            "Extra time for JavaScript-driven pages to finish "
                            "painting before capture. Leave empty to capture as "
                            "soon as the page loads."
                        ),
                        placeholder="2000",
                    ),
                    field(
                        "skipIfBlank",
                        "checkbox",
                        label="Skip if the capture is blank",
                        hint=(
                            "If the screenshot comes back a single flat colour, "
                            "leave the display on its previous content instead of "
                            "pushing an empty frame."
                        ),
                        checked_value="true",
                        unchecked_value="false",
                        submit_unchecked=True,
                    ),
                    callout(
                        "Only use trusted URLs. Slow or heavily scripted sites may fail to render before the screenshot timeout.",
                        tone="warning",
                    ),
                )
            ),
        )

    @staticmethod
    def _render_wait_ms(settings: Mapping[str, object]) -> int | None:
        """Parse the optional render wait, ignoring junk rather than failing."""
        raw = settings.get("renderWaitMs")
        if raw is None or raw == "":
            return None
        try:
            # OverflowError covers "1e999"/"inf", which int(float(...)) raises
            # rather than rejecting — a junk setting must not fail the render.
            value = int(float(str(raw)))
        except (TypeError, ValueError, OverflowError):
            logger.warning("Ignoring invalid renderWaitMs value %r", raw)
            return None
        if value <= 0:
            return None
        # Chromium spends virtual time, not wall clock, but an unbounded budget
        # still lets a page with a runaway timer hold the subprocess open until
        # the screenshot timeout kills it.
        return min(value, _MAX_RENDER_WAIT_MS)

    @staticmethod
    def _is_blank(image: Image.Image) -> bool:
        """Whether the capture is a single flat colour.

        ``getbbox`` is no use here — it only finds the non-zero region, so a
        page that rendered as solid white reports a full-size box. Counting
        distinct colours is the direct question, and it is cheap because
        ``getcolors`` bails out once it passes the cap.
        """
        try:
            colors = image.convert("RGB").getcolors(maxcolors=2)
        except Exception:
            logger.debug("Could not inspect screenshot for blankness", exc_info=True)
            return False
        # None means "more colours than the cap" — i.e. definitely not blank.
        return colors is not None and len(colors) <= 1

    def generate_image(
        self, settings: Mapping[str, object], device_config: Any
    ) -> Image.Image | None:

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

        # The `cast(Any, ...)` this replaces erased an already-correct
        # Optional return, which is what the None check below relies on.
        image = take_screenshot(
            url,
            dimensions,
            timeout_ms=40000,
            render_wait_ms=self._render_wait_ms(settings),
        )

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")

        skip_if_blank = str(settings.get("skipIfBlank", "false")).lower() == "true"
        if skip_if_blank and self._is_blank(image):
            # Blankness is only knowable after capture, so this cannot be a
            # skip_display_condition (which runs before the render). The
            # no-image return reaches the same place — the display keeps its
            # previous content — without capturing the page twice.
            logger.info(
                "Screenshot of %s came back blank; leaving the display unchanged",
                url.replace("\n", "").replace("\r", ""),
            )
            self.set_latest_metadata({"skipped": True, "reason": "Capture was blank"})
            return None

        return image
