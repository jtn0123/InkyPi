import html
import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import feedparser
from PIL.Image import Image as ImageType

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import (
    callout,
    field,
    option,
    row,
    schema,
    section,
)
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

FONT_SIZES = {"x-small": 0.7, "small": 0.9, "normal": 1, "large": 1.1, "x-large": 1.3}


class Rss(BasePlugin):
    def validate_settings(self, settings: Mapping[str, object]) -> str | None:
        """Reject non-URL feed values at save time (JTN-380).

        The submitted ``feedUrl`` must parse to an http(s) URL with a
        non-empty host.  Empty URLs and invalid values (e.g. ``not-a-feed``
        or ``javascript:alert(1)``) are rejected so junk values cannot be
        persisted even if the client-side ``type="url"`` guard is bypassed.
        """
        raw = settings.get("feedUrl")
        url = (raw or "").strip() if isinstance(raw, str) else ""
        if not url:
            return "RSS Feed URL is required."
        try:
            parsed = urlparse(url)
        except ValueError:
            return f"RSS Feed URL is not valid: {url!r}"
        if parsed.scheme.lower() not in {"http", "https"}:
            return f"RSS Feed URL is not valid: {url!r}"
        if not parsed.netloc:
            return f"RSS Feed URL is not valid: {url!r}"
        return None

    def build_settings_schema(self) -> dict[str, object]:
        schema_payload: dict[str, object] = schema(
            section(
                "Feed",
                row(
                    field(
                        "title",
                        label="Title",
                        placeholder="News Digest",
                        required=True,
                    ),
                    field(
                        "includeImages",
                        "checkbox",
                        label="Include Images",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                    ),
                    field(
                        "fontSize",
                        "select",
                        label="Font Size",
                        default="normal",
                        options=[
                            option("x-small", "Extra Small"),
                            option("small", "Small"),
                            option("normal", "Normal"),
                            option("large", "Large"),
                            option("x-large", "Extra Large"),
                        ],
                    ),
                ),
                field(
                    "feedUrl",
                    "url",
                    label="RSS Feed URL",
                    placeholder="https://example.com/feed.xml",
                    required=True,
                    pattern="https?://.+",
                ),
                callout(
                    "Only use trusted RSS feeds. Untrusted URLs can introduce security and reliability risks.",
                    tone="warning",
                ),
            )
        )
        return schema_payload

    def generate_settings_template(self) -> dict[str, object]:
        template_params = super().generate_settings_template()
        settings_template: dict[str, object] = template_params
        template_params["style_settings"] = True
        return settings_template

    def generate_image(
        self, settings: Mapping[str, object], device_config: Any
    ) -> ImageType:
        title = settings.get("title")
        if not isinstance(title, str):
            title = "Top Stories"
        feed_url = settings.get("feedUrl")
        if not isinstance(feed_url, str):
            feed_url = "https://feeds.bbci.co.uk/news/rss.xml"
        font_size = settings.get("fontSize", "normal")
        font_scale = FONT_SIZES.get(font_size, 1) if isinstance(font_size, str) else 1

        items = self.parse_rss_feed(feed_url)

        dimensions = self.get_oriented_dimensions(device_config)

        template_params = {
            "title": title,
            "include_images": settings.get("includeImages") == "true",
            "items": items[:10],
            "font_scale": font_scale,
            "plugin_settings": settings,
        }

        return self.render_image(dimensions, "rss.html", "rss.css", template_params)

    @staticmethod
    def _sanitize_text(raw: str) -> str:
        """Strip HTML tags and decode entities to produce safe plain text.

        Defense-in-depth: Jinja2 auto-escaping is the primary XSS protection;
        this strips tags so rendered text looks clean.
        """
        text = re.sub(r"<[^>]+>", "", raw)
        return html.unescape(text).strip()

    @staticmethod
    def _entry_value(entry: Any, key: str) -> Any:
        getter = getattr(entry, "get", None)
        if callable(getter):
            return getter(key, "")
        if isinstance(entry, Mapping):
            return entry.get(key, "")
        return getattr(entry, key, "")

    def parse_rss_feed(
        self, url: str, timeout: int = 10
    ) -> list[dict[str, str | None]]:
        resp = get_http_session().get(
            url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}
        )
        resp.raise_for_status()

        # Parse the feed content
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            raise RuntimeError(f"Failed to parse RSS feed: {feed.bozo_exception}")
        items: list[dict[str, str | None]] = []

        for entry in feed.entries:

            title = Rss._sanitize_text(Rss._entry_value(entry, "title"))
            description = Rss._sanitize_text(Rss._entry_value(entry, "description"))
            published = Rss._entry_value(entry, "published")
            if not isinstance(published, str):
                published = ""
            link = Rss._entry_value(entry, "link")
            if not isinstance(link, str):
                link = ""

            item = {
                "title": title,
                "description": description,
                "published": published,
                "link": link,
                "image": None,
            }

            # Try to extract image from common RSS fields
            media_content = Rss._entry_value(entry, "media_content")
            if isinstance(media_content, list) and media_content:
                candidate = media_content[0]
                if isinstance(candidate, Mapping):
                    media_url = candidate.get("url")
                    if isinstance(media_url, str):
                        item["image"] = media_url
                        items.append(item)
                        continue

            media_thumbnail = Rss._entry_value(entry, "media_thumbnail")
            if isinstance(media_thumbnail, list) and media_thumbnail:
                candidate = media_thumbnail[0]
                if isinstance(candidate, Mapping):
                    media_url = candidate.get("url")
                    if isinstance(media_url, str):
                        item["image"] = media_url
                        items.append(item)
                        continue

            enclosures = Rss._entry_value(entry, "enclosures")
            if isinstance(enclosures, list) and enclosures:
                candidate = enclosures[0]
                if isinstance(candidate, Mapping):
                    media_url = candidate.get("url")
                    if isinstance(media_url, str):
                        item["image"] = media_url

            items.append(item)

        return items
