"""
APOD Plugin for InkyPi
This plugin fetches the Astronomy Picture of the Day (APOD) from NASA's API
and displays it on the InkyPi device. It supports optional manual date selection or random dates.
For the API key, set `NASA_SECRET={API_KEY}` in your .env file.
"""

import logging
import os
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from random import randint
from typing import Any, cast

from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin, DeviceConfigLike
from plugins.base_plugin.settings_schema import callout, field, schema, section
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

# NASA's Astronomy Picture of the Day archive begins on 1995-06-16. Requesting
# any date earlier than this — or any future date — returns a 404 from the
# upstream API, so we reject such values at save time rather than letting the
# bad config persist until ``generate_image`` runs.
_APOD_MIN_DATE = date(1995, 6, 16)


class Apod(BasePlugin):
    def _candidate_image_urls(self, data: dict[str, object]) -> list[str]:
        """Return APOD image URLs ordered by device-appropriate preference.

        On low-resource devices like a Pi Zero 2 W, prefer NASA's standard
        ``url`` asset before ``hdurl`` to reduce download/decode pressure.
        """
        standard_url = data.get("url")
        hd_url = data.get("hdurl")
        if not isinstance(standard_url, str):
            standard_url = None
        if not isinstance(hd_url, str):
            hd_url = None
        ordered = (
            [standard_url, hd_url]
            if self.image_loader.is_low_resource
            else [hd_url, standard_url]
        )
        deduped: list[str] = []
        for url in ordered:
            if url and url not in deduped:
                deduped.append(url)
        return deduped

    def validate_settings(self, settings: Mapping[str, object]) -> str | None:
        """Reject out-of-range custom dates at save time (JTN-379).

        The frontend ``<input type="date">`` enforces ``min``/``max``, but a
        direct POST can still bypass it. Without server-side validation a bad
        date persists with a success toast and only fails later when the
        plugin tries to fetch a non-existent APOD from NASA.
        """
        if settings.get("randomizeApod") == "true":
            # Random mode picks its own date — ignore customDate.
            return None
        raw_custom_date = settings.get("customDate")
        if isinstance(raw_custom_date, str):
            custom_date_str = raw_custom_date.strip()
        else:
            custom_date_str = ""
        if not custom_date_str:
            # No custom date set — ``generate_image`` falls back to today.
            return None
        try:
            parsed = date.fromisoformat(custom_date_str)
        except ValueError:
            return f"Invalid date format: {custom_date_str!r} (expected YYYY-MM-DD)"
        today = datetime.now(tz=UTC).date()
        if parsed < _APOD_MIN_DATE:
            return (
                f"Date must be on or after {_APOD_MIN_DATE.isoformat()} "
                "(NASA APOD archive start)."
            )
        if parsed > today:
            return f"Date must be on or before today ({today.isoformat()})."
        return None

    def build_settings_schema(self) -> dict[str, object]:
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        return schema(
            section(
                "Source",
                callout(
                    "Pick a specific APOD date or enable randomization to explore past entries from NASA's archive.",
                    title="NASA APOD",
                ),
                field(
                    "randomizeApod",
                    "checkbox",
                    label="Randomize Date",
                    hint="When enabled, InkyPi chooses a random APOD date instead of using the date field below.",
                    submit_unchecked=True,
                    checked_value="true",
                    unchecked_value="false",
                ),
                field(
                    "customDate",
                    "date",
                    label="Date",
                    default=today,
                    min=_APOD_MIN_DATE.isoformat(),
                    max=today,
                    hint=(
                        f"NASA APOD archive runs from {_APOD_MIN_DATE.isoformat()} "
                        "to today."
                    ),
                    visible_if={"field": "randomizeApod", "equals": "false"},
                ),
            )
        )

    def _request_timeout(self) -> float:
        try:
            return float(os.getenv("INKYPI_HTTP_TIMEOUT_DEFAULT_S", "20"))
        except (ValueError, TypeError):
            return 20.0

    def generate_settings_template(self) -> dict[str, object]:
        template_params = super().generate_settings_template()
        template_params["api_key"] = {
            "required": True,
            "service": "NASA",
            "expected_key": "NASA_SECRET",
        }
        template_params["style_settings"] = False
        return template_params

    def generate_image(
        self, settings: Mapping[str, object], device_config: DeviceConfigLike
    ) -> Image.Image:
        logger.info(f"APOD plugin settings: {settings}")

        api_key = device_config.load_env_key("NASA_SECRET")
        if not api_key:
            logger.error("NASA API Key not configured")
            raise RuntimeError("NASA API Key not configured.")

        params = {"api_key": api_key}

        if settings.get("randomizeApod") == "true":
            start = datetime(2015, 1, 1, tzinfo=UTC)
            end = datetime.now(tz=UTC)
            delta_days = (end - start).days
            random_date = start + timedelta(days=randint(0, delta_days))
            params["date"] = random_date.strftime("%Y-%m-%d")
        elif isinstance(settings.get("customDate"), str):
            params["date"] = cast(str, settings["customDate"])

        apod_url = os.getenv("INKYPI_NASA_API_URL", "https://api.nasa.gov")
        response = get_http_session().get(
            f"{apod_url}/planetary/apod",
            params=params,
            timeout=self._request_timeout(),
        )

        if response.status_code != 200:
            logger.error(f"NASA API error: {response.text}")
            raise RuntimeError("Failed to retrieve NASA APOD.")

        data = cast(dict[str, object], response.json())

        if data.get("media_type") != "image":
            raise RuntimeError("APOD is not an image today.")

        image: Image.Image | None = None
        selected_image_url = None
        timeout_ms = int(self._request_timeout() * 1000)
        dimensions = self.get_oriented_dimensions(device_config)
        candidate_urls = self._candidate_image_urls(data)
        if not candidate_urls:
            raise RuntimeError("Failed to load APOD image.")

        for idx, image_url in enumerate(candidate_urls):
            image = cast(Any, self.image_loader).from_url(
                image_url,
                dimensions=dimensions,
                timeout_ms=timeout_ms,
                resize=False,
            )
            if image is not None:
                selected_image_url = image_url
                break
            logger.warning(
                "APOD image load failed for %s (attempt %s/%s)",
                image_url,
                idx + 1,
                len(candidate_urls),
            )

        if image is None:
            raise RuntimeError("Failed to load APOD image.")

        self.set_latest_metadata(
            {
                "date": data.get("date"),
                "title": data.get("title"),
                "caption": data.get("copyright"),
                "explanation": data.get("explanation"),
                "page_url": selected_image_url or data.get("hdurl") or data.get("url"),
                "description_url": data.get("url"),
            }
        )

        return image
