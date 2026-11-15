"""
APOD Plugin for InkyPi
This plugin fetches the Astronomy Picture of the Day (APOD) from NASA's API
and displays it on the InkyPi device. It supports optional manual date selection or random dates.
For the API key, set `NASA_SECRET={API_KEY}` in your .env file.

When the API has no usable picture (an error, or the NASA-logo placeholder it
has returned for every date since the APOD site moved to science.nasa.gov),
the picture is read from the APOD website instead: the dated page's
``og:image``, or for today the newest entry of the APOD feed.
"""

import logging
import os
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from random import randint
from typing import cast
from urllib.parse import urlparse

import requests
from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin, DeviceConfigLike
from plugins.base_plugin.settings_schema import callout, field, schema, section
from utils.http_client import get_http_session
from utils.safe_fetch import safe_fetch_bytes

logger = logging.getLogger(__name__)

# NASA's Astronomy Picture of the Day archive begins on 1995-06-16. Requesting
# any date earlier than this — or any future date — returns a 404 from the
# upstream API, so we reject such values at save time rather than letting the
# bad config persist until ``generate_image`` runs.
_APOD_MIN_DATE = date(1995, 6, 16)

# The APOD website: dated pages are ``ap{yymmdd}.html`` and redirect to the
# matching science.nasa.gov article. The feed lists the newest entries first.
_APOD_SITE_URL = "https://apod.nasa.gov/apod"
_APOD_FEED_URL = "https://science.nasa.gov/feed/apod-basic/"
_PAGE_MAX_BYTES = 4 * 1024 * 1024

# Path fragment of the stand-in image the API returns when it has no picture.
_PLACEHOLDER_PATH_MARKER = "/nasa-logo"

# The APOD landing page; a dated page that lands here has no entry of its own.
_LANDING_PATH = "/apod/"

# "APOD: 2026 November 14 – Apollo 12 and Surveyor 3 - NASA Science"
_TITLE_PREFIX = re.compile(r"^APOD:\s*\d{4}\s+\w+\s+\d{1,2}\s*[-\u2013\u2014]\s*")
_TITLE_SUFFIX = " - NASA Science"


class _MetaTags(HTMLParser):
    """Collect ``<meta property|name=... content=...>`` values (first wins)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        attributes = dict(attrs)
        key = attributes.get("property") or attributes.get("name")
        content = attributes.get("content")
        if key and content and key not in self.values:
            self.values[key] = content


def _meta_tags(html: bytes) -> dict[str, str]:
    parser = _MetaTags()
    parser.feed(html.decode("utf-8", errors="replace"))
    parser.close()
    return parser.values


def _is_placeholder(url: object) -> bool:
    return isinstance(url, str) and _PLACEHOLDER_PATH_MARKER in urlparse(url).path


def _clean_title(raw: str | None) -> str | None:
    if not raw:
        return None
    title = _TITLE_PREFIX.sub("", raw.strip())
    if title.endswith(_TITLE_SUFFIX):
        title = title[: -len(_TITLE_SUFFIX)]
    return title.strip() or None


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
        request_date = "today"

        if settings.get("randomizeApod") == "true":
            start = datetime(2015, 1, 1, tzinfo=UTC)
            end = datetime.now(tz=UTC)
            delta_days = (end - start).days
            random_date = start + timedelta(days=randint(0, delta_days))
            request_date = random_date.strftime("%Y-%m-%d")
            params["date"] = request_date
        elif (
            isinstance(settings.get("customDate"), str)
            and cast(str, settings["customDate"]).strip()
        ):
            # A blank date means today (see validate_settings).
            request_date = cast(str, settings["customDate"]).strip()
            params["date"] = request_date

        apod_url = os.getenv("INKYPI_NASA_API_URL", "https://api.nasa.gov")
        logger.info(
            "APOD request: date=%s randomized=%s base_url=%s timeout_s=%.1f",
            request_date,
            settings.get("randomizeApod") == "true",
            apod_url,
            self._request_timeout(),
        )
        data = self._fetch_from_api(apod_url, params)
        if data is None:
            logger.warning(
                "NASA APOD API had no usable picture for %s; reading the APOD website",
                request_date,
            )
            data = self._fetch_from_site(
                None if request_date == "today" else request_date
            )

        if data.get("media_type") != "image":
            raise RuntimeError("APOD is not an image today.")

        image: Image.Image | None = None
        selected_image_url = None
        timeout_ms = int(self._request_timeout() * 1000)
        dimensions = self.get_oriented_dimensions(device_config)
        candidate_urls = self._candidate_image_urls(data)
        logger.info(
            "APOD image candidates: count=%d low_resource=%s target=%dx%d",
            len(candidate_urls),
            self.image_loader.is_low_resource,
            dimensions[0],
            dimensions[1],
        )
        if not candidate_urls:
            raise RuntimeError("Failed to load APOD image.")

        for idx, image_url in enumerate(candidate_urls):
            image = self.image_loader.from_url(
                image_url,
                dimensions=dimensions,
                timeout_ms=timeout_ms,
                resize=True,
            )
            if image is not None:
                selected_image_url = image_url
                logger.info(
                    "APOD image loaded: attempt=%d/%d size=%dx%d",
                    idx + 1,
                    len(candidate_urls),
                    image.size[0],
                    image.size[1],
                )
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
                "page_url": data.get("page_url")
                or selected_image_url
                or data.get("hdurl")
                or data.get("url"),
                "description_url": data.get("url"),
            }
        )

        return image

    def _fetch_from_api(
        self, apod_url: str, params: dict[str, str]
    ) -> dict[str, object] | None:
        """Return the API's answer, or None when it has no usable picture."""
        try:
            response = get_http_session().get(
                f"{apod_url}/planetary/apod",
                params=params,
                timeout=self._request_timeout(),
            )
        except requests.RequestException as exc:
            logger.warning("NASA API request failed: %s", type(exc).__name__)
            return None
        if response.status_code != 200:
            logger.error(
                "NASA API error: HTTP %s %s",
                response.status_code,
                str(response.text)[:200],
            )
            return None
        try:
            data = cast(dict[str, object], response.json())
        except ValueError:
            logger.error("NASA API returned a body that is not JSON")
            return None
        logger.info(
            "APOD response: date=%s media_type=%s title=%s",
            data.get("date"),
            data.get("media_type"),
            data.get("title"),
        )
        if _is_placeholder(data.get("url")) or _is_placeholder(data.get("hdurl")):
            logger.warning(
                "NASA API returned its placeholder image instead of the APOD"
            )
            return None
        return data

    def _fetch_from_site(self, request_date: str | None) -> dict[str, object]:
        """Read the APOD for *request_date* (None = newest) from the website."""
        timeout = self._request_timeout()
        site = os.getenv("INKYPI_APOD_SITE_URL", _APOD_SITE_URL).rstrip("/")
        try:
            if request_date is None:
                page_url, title, entry_date = self._newest_feed_entry(timeout)
            else:
                day = date.fromisoformat(request_date)
                page_url = f"{site}/ap{day:%y%m%d}.html"
                title, entry_date = None, request_date
            meta = _meta_tags(
                safe_fetch_bytes(page_url, max_bytes=_PAGE_MAX_BYTES, timeout=timeout)
            )
        except (requests.RequestException, ValueError) as exc:
            logger.error("APOD website request failed: %s", exc)
            raise RuntimeError("Failed to retrieve NASA APOD.") from exc

        image_url = meta.get("og:image") or meta.get("twitter:image")
        landed_on = urlparse(meta.get("og:url", "")).path
        if not image_url or _is_placeholder(image_url) or landed_on == _LANDING_PATH:
            logger.error("APOD website has no picture for %s", request_date or "today")
            raise RuntimeError("Failed to retrieve NASA APOD.")
        logger.info("APOD website picture: %s", image_url)
        return {
            "date": entry_date,
            "title": title or _clean_title(meta.get("og:title")),
            "media_type": "image",
            "url": image_url,
            "page_url": meta.get("og:url") or page_url,
        }

    def _newest_feed_entry(self, timeout: float) -> tuple[str, str | None, str | None]:
        """Return (article URL, title, YYYY-MM-DD) of the newest APOD."""
        import feedparser

        feed = feedparser.parse(
            safe_fetch_bytes(
                os.getenv("INKYPI_APOD_FEED_URL", _APOD_FEED_URL),
                max_bytes=_PAGE_MAX_BYTES,
                timeout=timeout,
            )
        )
        entries = feed.get("entries") or []
        link = entries[0].get("link") if entries else None
        if not isinstance(link, str) or urlparse(link).scheme != "https":
            raise ValueError("APOD feed has no entries")
        entry = entries[0]
        published = entry.get("published_parsed")
        entry_date = (
            f"{published.tm_year:04d}-{published.tm_mon:02d}-{published.tm_mday:02d}"
            if published
            else None
        )
        title = entry.get("title")
        return link, title if isinstance(title, str) else None, entry_date
