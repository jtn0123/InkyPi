"""
Wpotd Plugin for InkyPi
This plugin fetches the Wikipedia Picture of the Day (Wpotd) from Wikipedia's API
and displays it on the InkyPi device.

It supports optional manual date selection or random dates and can resize the image to fit the device's dimensions.

Wikipedia API Documentation: https://www.mediawiki.org/wiki/API:Main_page
Picture of the Day example: https://www.mediawiki.org/wiki/API:Picture_of_the_day_viewer
Github Repository: https://github.com/wikimedia/mediawiki-api-demos/tree/master/apps/picture-of-the-day-viewer
Wikimedia requires a User Agent header for API requests, which is set in the SESSION headers:
https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy

Flow:

1. Fetch the date to use for the Picture of the Day (POTD) based on settings. (_determine_date)
2. Make an API request to fetch the POTD data for that date. (_fetch_potd)
3. Extract the image filename from the response. (_fetch_potd)
4. Make another API request to get the image URL. (_fetch_image_src)
5. Download the image from the URL. (_download_image)
6. Optionally resize the image to fit the device dimensions. (_shrink_to_fit))
"""

import logging
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from random import randint
from typing import Any, cast

from PIL import Image
from PIL.Image import Image as ImageType

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import callout, field, schema, section
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

# Wikipedia's ``Template:POTD/YYYY-MM-DD`` series on en.wikipedia runs
# continuously from 2007-01-01. Earlier years have gaps, and requesting a
# future date returns no template. We reject values outside this window at
# save time rather than letting the bad config persist until
# ``generate_image`` runs and fails against the upstream API (JTN-651).
_WPOTD_MIN_DATE = date(2007, 1, 1)


class Wpotd(BasePlugin):
    HEADERS = {"User-Agent": "InkyPi/0.0 (https://github.com/fatihak/InkyPi/)"}
    API_URL = os.getenv(
        "INKYPI_WIKIPEDIA_API_URL", "https://en.wikipedia.org/w/api.php"
    )

    def validate_settings(self, settings: Mapping[str, object]) -> str | None:
        """Reject out-of-range custom dates at save time (JTN-651).

        The frontend ``<input type="date">`` enforces ``min``/``max``, but a
        direct POST can still bypass it. Without server-side validation a bad
        date persists with a success toast and only fails later when the
        plugin tries to fetch a non-existent ``Template:POTD/<date>`` from
        Wikipedia.
        """
        if settings.get("randomizeWpotd") == "true":
            # Random mode picks its own date — ignore customDate.
            return None
        raw_custom_date = settings.get("customDate")
        custom_date_str = (
            raw_custom_date.strip() if isinstance(raw_custom_date, str) else ""
        )
        if not custom_date_str:
            # No custom date set — ``generate_image`` falls back to today.
            return None
        try:
            parsed = date.fromisoformat(custom_date_str)
        except ValueError:
            return f"Invalid date format: {custom_date_str!r} (expected YYYY-MM-DD)"
        today = datetime.now(tz=UTC).date()
        if parsed < _WPOTD_MIN_DATE:
            return (
                f"Date must be on or after {_WPOTD_MIN_DATE.isoformat()} "
                "(Wikipedia POTD archive start)."
            )
        if parsed > today:
            return f"Date must be on or before today ({today.isoformat()})."
        return None

    def build_settings_schema(self) -> dict[str, object]:
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        schema_payload: dict[str, object] = schema(
            section(
                "Source",
                callout(
                    "If the date field is blank, the plugin uses today’s picture. That makes it safe to add to playlists without constant edits.",
                ),
                field(
                    "randomizeWpotd",
                    "checkbox",
                    label="Randomize Date",
                    submit_unchecked=True,
                    checked_value="true",
                    unchecked_value="false",
                ),
                field(
                    "customDate",
                    "date",
                    label="Date",
                    default=today,
                    min=_WPOTD_MIN_DATE.isoformat(),
                    max=today,
                    hint=(
                        f"Wikipedia POTD archive runs from {_WPOTD_MIN_DATE.isoformat()} "
                        "to today."
                    ),
                    visible_if={"field": "randomizeWpotd", "equals": "false"},
                ),
                field(
                    "shrinkToFitWpotd",
                    "checkbox",
                    label="Shrink Image To Fit",
                    submit_unchecked=True,
                    checked_value="true",
                    unchecked_value="false",
                    default="true",
                ),
            )
        )
        return schema_payload

    def generate_settings_template(self) -> dict[str, object]:
        template_params = super().generate_settings_template()
        settings_template: dict[str, object] = template_params
        template_params["style_settings"] = False
        return settings_template

    def generate_image(
        self, settings: Mapping[str, object], device_config: Any
    ) -> ImageType:
        logger.info(f"WPOTD plugin settings: {settings}")
        datetofetch = self._determine_date(settings)
        logger.info(f"WPOTD plugin datetofetch: {datetofetch}")

        data = self._fetch_potd(datetofetch)
        picurl = data.get("image_src")
        if not isinstance(picurl, str):
            raise RuntimeError("Failed to resolve WPOTD image URL.")
        logger.info(f"WPOTD plugin Picture URL: {picurl}")

        image = self._download_image(picurl)
        if image is None:
            logger.error("Failed to download WPOTD image.")
            raise RuntimeError("Failed to download WPOTD image.")
        if settings.get("shrinkToFitWpotd") == "true":
            dimensions = self.get_oriented_dimensions(device_config)
            max_width, max_height = dimensions
            image = self._shrink_to_fit(image, max_width, max_height)
            logger.info(
                f"Image resized to fit device dimensions: {max_width},{max_height}"
            )

        return image

    def _determine_date(self, settings: Mapping[str, object]) -> date:
        if settings.get("randomizeWpotd") == "true":
            start = datetime(2015, 1, 1, tzinfo=UTC)
            delta_days = (datetime.now(tz=UTC) - start).days
            return (start + timedelta(days=randint(0, delta_days))).date()
        custom_date = settings.get("customDate")
        if isinstance(custom_date, str):
            try:
                # YYYY-MM-DD date input; the parsed date is returned as-is.
                return date.fromisoformat(custom_date)
            except ValueError:
                logger.warning(
                    "Invalid customDate %r for WPOTD, defaulting to today",
                    custom_date,
                )
                return datetime.now(tz=UTC).date()
        else:
            return datetime.now(tz=UTC).date()

    def _download_image(self, url: str) -> ImageType:
        if url.lower().endswith(".svg"):
            logger.warning(
                "SVG format is not supported by Pillow. Skipping image download."
            )
            raise RuntimeError("Failed to load WPOTD image.")
        dimensions = (4096, 4096)
        image_loader = cast(Any, self.image_loader)
        image = image_loader.from_url(
            url,
            dimensions=dimensions,
            timeout_ms=10000,
            resize=False,
            headers=self.HEADERS,
        )
        if image is None:
            logger.error("Failed to load WPOTD image from %s", url)
            raise RuntimeError("Failed to load WPOTD image.")
        return image

    def _fetch_potd(self, cur_date: date) -> dict[str, object]:
        title = f"Template:POTD/{cur_date.isoformat()}"
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "images",
            "titles": title,
        }

        data = self._make_request(params)
        try:
            query = data.get("query")
            if not isinstance(query, Mapping):
                raise KeyError("query")
            pages = query.get("pages")
            if not isinstance(pages, Sequence) or len(pages) == 0:
                raise KeyError("pages")
            first_page = pages[0]
            if not isinstance(first_page, Mapping):
                raise KeyError("pages[0]")
            images = first_page.get("images")
            if not isinstance(images, Sequence) or len(images) == 0:
                raise KeyError("images")
            image = images[0]
            if not isinstance(image, Mapping):
                raise KeyError("images[0]")
            filename = image.get("title")
            if not isinstance(filename, str):
                raise KeyError("images[0].title")
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to retrieve POTD filename for {cur_date}: {e}")
            raise RuntimeError("Failed to retrieve POTD filename.") from e

        image_src = self._fetch_image_src(filename)

        return {
            "filename": filename,
            "image_src": image_src,
            "image_page_url": f"https://en.wikipedia.org/wiki/{title}",
            "date": cur_date,
        }

    def _fetch_image_src(self, filename: str) -> str:
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "iiprop": "url",
            "titles": filename,
        }
        data = self._make_request(params)
        try:
            query = data.get("query")
            if not isinstance(query, Mapping):
                raise KeyError("query")
            pages = query.get("pages")
            if not isinstance(pages, Mapping):
                raise KeyError("pages")
            first_page = next(iter(pages.values()), None)
            if not isinstance(first_page, Mapping):
                raise KeyError("pages.values()[0]")
            image_info = first_page.get("imageinfo")
            if not isinstance(image_info, Sequence) or len(image_info) == 0:
                raise KeyError("imageinfo")
            first_image = image_info[0]
            if not isinstance(first_image, Mapping):
                raise KeyError("imageinfo[0]")
            url = first_image.get("url")
            if not isinstance(url, str):
                raise KeyError("imageinfo[0].url")
            return url
        except (KeyError, IndexError, StopIteration) as e:
            logger.error(f"Failed to retrieve image URL for {filename}: {e}")
            raise RuntimeError("Failed to retrieve image URL.") from e

    def _make_request(self, params: Mapping[str, object]) -> dict[str, Any]:
        try:
            response = get_http_session().get(
                self.API_URL,
                params=cast(Any, dict(params)),
                headers=self.HEADERS,
                timeout=10,
            )
            response.raise_for_status()
            json_payload: dict[str, Any] = response.json()
            return json_payload
        except Exception as e:
            logger.error(f"Wikipedia API request failed with params {params}: {str(e)}")
            raise RuntimeError("Wikipedia API request failed.") from e

    def _shrink_to_fit(
        self, image: ImageType, max_width: int, max_height: int
    ) -> ImageType:
        """
        Resize the image to fit within max_width and max_height while maintaining aspect ratio.
        Uses high-quality resampling.
        """
        orig_width, orig_height = image.size

        if orig_width > max_width or orig_height > max_height:
            # Determine whether to constrain by width or height
            if orig_width >= orig_height:
                # Landscape or square -> constrain by max_width
                if orig_width > max_width:
                    new_width = max_width
                    new_height = int(orig_height * max_width / orig_width)
                else:
                    new_width, new_height = orig_width, orig_height
            else:
                # Portrait -> constrain by max_height
                if orig_height > max_height:
                    new_height = max_height
                    new_width = int(orig_width * max_height / orig_height)
                else:
                    new_width, new_height = orig_width, orig_height
            # Resize using high-quality resampling
            image = image.resize((new_width, new_height), Image.LANCZOS)
            # Create a new image with white background and paste the resized image in the center
            new_image = Image.new("RGB", (max_width, max_height), (255, 255, 255))
            new_image.paste(
                image, ((max_width - new_width) // 2, (max_height - new_height) // 2)
            )
            return new_image
        # If the image is already within bounds, return it as is
        return image
