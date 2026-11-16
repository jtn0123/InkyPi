"""
APOD Plugin for InkyPi
This plugin fetches the Astronomy Picture of the Day (APOD) from NASA's API
and displays it on the InkyPi device. It supports optional manual date selection or random dates.
For the API key, set `NASA_SECRET={API_KEY}` in your .env file.

When the API has no usable picture (an error, or the NASA-logo placeholder it
has returned for every date since the APOD site moved to science.nasa.gov),
the picture is read from the APOD website instead: the dated page's
``og:image``, or for today the newest entry of the APOD feed.

A picture is kept on disk once found, keyed by its date, so later turns for
the same date make no request at all. Random mode always fetches.
"""

import contextlib
import json
import logging
import os
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from random import randint
from typing import cast
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin, DeviceConfigLike
from plugins.base_plugin.settings_schema import callout, field, schema, section
from utils.http_client import get_http_session
from utils.image_utils import (
    FAST_PNG_COMPRESS_LEVEL,
    save_image_atomic,
    write_bytes_atomic,
)
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

# Pictures already found, under the plugin image folder (ADR-0002: a plugin
# that needs a cache keeps it on disk, keyed on what it fetches). One entry
# is a date and picture size; the least recently used go first.
_CACHE_DIR_NAME = "apod_cache"
_CACHE_MAX_ENTRIES = 8

# APOD dates its pictures in US Eastern time, so "today" changes at
# midnight there, not at midnight UTC.
_APOD_TZ = ZoneInfo("America/New_York")


def _apod_today() -> date:
    return datetime.now(tz=_APOD_TZ).date()


class _PictureCache:
    """Resolved pictures and their metadata, one pair of files per entry.

    Nothing here fails a render: a cache that can't be read is a miss, and
    one that can't be written is skipped.
    """

    def __init__(self, directory: str) -> None:
        self.directory = directory

    def _paths(self, day: date, dimensions: tuple[int, int]) -> tuple[str, str]:
        width, height = dimensions
        stem = os.path.join(self.directory, f"{day.isoformat()}_{width}x{height}")
        return f"{stem}.json", f"{stem}.png"

    def load(
        self, day: date, dimensions: tuple[int, int]
    ) -> tuple[Image.Image, dict[str, object]] | None:
        meta_path, png_path = self._paths(day, dimensions)
        try:
            with open(meta_path, encoding="utf-8") as fh:
                metadata = json.load(fh)
            with Image.open(png_path) as cached:
                image = cached.copy()
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning("APOD cache entry for %s is unreadable: %s", day, exc)
            return None
        if not isinstance(metadata, dict):
            return None
        # Marks the entry as recently used, so eviction keeps it.
        with contextlib.suppress(OSError):
            os.utime(meta_path)
        return image, metadata

    def store(
        self,
        day: date,
        dimensions: tuple[int, int],
        image: Image.Image,
        metadata: Mapping[str, object],
    ) -> None:
        meta_path, png_path = self._paths(day, dimensions)
        try:
            os.makedirs(self.directory, exist_ok=True)
            save_image_atomic(
                image, png_path, format="PNG", compress_level=FAST_PNG_COMPRESS_LEVEL
            )
            # The metadata goes last: an entry counts once both files exist.
            write_bytes_atomic(json.dumps(dict(metadata)).encode("utf-8"), meta_path)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not cache the APOD for %s: %s", day, exc)
            return
        self._evict()

    def _evict(self) -> None:
        """Keep the newest ``_CACHE_MAX_ENTRIES`` entries; drop strays."""
        try:
            names = os.listdir(self.directory)
            entries = sorted(
                (os.path.getmtime(os.path.join(self.directory, name)), name[:-5])
                for name in names
                if name.endswith(".json")
            )
        except OSError:
            return
        keep = {stem for _mtime, stem in entries[-_CACHE_MAX_ENTRIES:]}
        for name in names:
            stem, ext = os.path.splitext(name)
            if ext in (".json", ".png") and stem not in keep:
                with contextlib.suppress(OSError):
                    os.remove(os.path.join(self.directory, name))


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

        # The key travels in the X-Api-Key header that api.data.gov accepts,
        # never in the query string, where request URLs reach urllib3 retry
        # logs, exception messages and proxy logs.
        params: dict[str, str] = {}
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

        dimensions = self.get_oriented_dimensions(device_config)
        cache = self._picture_cache(device_config)
        cache_day = self._cache_day(settings, request_date)
        if cache is not None and cache_day is not None:
            hit = cache.load(cache_day, dimensions)
            if hit is not None:
                cached_image, cached_metadata = hit
                logger.info("APOD for %s reused from the cache", cache_day)
                self.set_latest_metadata(cached_metadata)
                return cached_image

        apod_url = os.getenv("INKYPI_NASA_API_URL", "https://api.nasa.gov")
        logger.info(
            "APOD request: date=%s randomized=%s base_url=%s timeout_s=%.1f",
            request_date,
            settings.get("randomizeApod") == "true",
            apod_url,
            self._request_timeout(),
        )
        data = self._fetch_from_api(apod_url, params, api_key)
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

        metadata: dict[str, object] = {
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
        self.set_latest_metadata(metadata)

        # Today's picture is kept only once NASA has published it: before
        # that the newest one is yesterday's, and caching it as today's
        # would hide the new picture until tomorrow.
        if (
            cache is not None
            and cache_day is not None
            and (request_date != "today" or data.get("date") == cache_day.isoformat())
        ):
            cache.store(cache_day, dimensions, image, metadata)

        return image

    @staticmethod
    def _picture_cache(device_config: DeviceConfigLike) -> _PictureCache | None:
        directory = getattr(device_config, "plugin_image_dir", None)
        if not isinstance(directory, str) or not directory:
            return None
        return _PictureCache(os.path.join(directory, _CACHE_DIR_NAME))

    @staticmethod
    def _cache_day(settings: Mapping[str, object], request_date: str) -> date | None:
        """The date whose picture this render shows, or None to skip the cache.

        Random mode picks a new date every turn, so it is never cached.
        """
        if settings.get("randomizeApod") == "true":
            return None
        if request_date == "today":
            return _apod_today()
        try:
            return date.fromisoformat(request_date)
        except ValueError:
            return None

    def _fetch_from_api(
        self, apod_url: str, params: dict[str, str], api_key: str
    ) -> dict[str, object] | None:
        """Return the API's answer, or None when it has no usable picture."""
        try:
            # No redirects: requests would replay the X-Api-Key header to
            # whatever host a redirect names. The API answers directly; a
            # redirect is treated like any other non-200 and falls back to
            # the APOD website.
            response = get_http_session().get(
                f"{apod_url}/planetary/apod",
                params=params,
                headers={"X-Api-Key": api_key},
                timeout=self._request_timeout(),
                allow_redirects=False,
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
