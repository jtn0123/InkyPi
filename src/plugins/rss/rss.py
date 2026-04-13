import html
import logging
import re
from urllib.parse import urlparse

import feedparser

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
    def validate_settings(self, settings: dict) -> str | None:
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

    def build_settings_schema(self):
        return schema(
            section(
                "Feed",
                row(
                    field(
                        "title", label="Title", placeholder="News Digest", required=True
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

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["style_settings"] = True
        return template_params

    def generate_image(self, settings, device_config):
        title = settings.get("title")
        feed_url = settings.get("feedUrl")
        if not feed_url:
            raise RuntimeError("RSS Feed Url is required.")

        items = self.parse_rss_feed(feed_url)

        dimensions = self.get_oriented_dimensions(device_config)

        template_params = {
            "title": title,
            "include_images": settings.get("includeImages") == "true",
            "items": items[:10],
            "font_scale": FONT_SIZES.get(settings.get("fontSize", "normal"), 1),
            "plugin_settings": settings,
        }

        return self.render_image(dimensions, "rss.html", "rss.css", template_params)

    @staticmethod
    def _sanitize_text(raw):
        """Strip HTML tags and decode entities to produce safe plain text.

        Defense-in-depth: Jinja2 auto-escaping is the primary XSS protection;
        this strips tags so rendered text looks clean.
        """
        text = re.sub(r"<[^>]+>", "", raw)
        return html.unescape(text).strip()

    def parse_rss_feed(self, url, timeout=10):
        resp = get_http_session().get(
            url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}
        )
        resp.raise_for_status()

        # Parse the feed content
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            raise RuntimeError(f"Failed to parse RSS feed: {feed.bozo_exception}")
        items = []

        for entry in feed.entries:
            item = {
                "title": self._sanitize_text(entry.get("title", "")),
                "description": self._sanitize_text(entry.get("description", "")),
                "published": entry.get("published", ""),
                "link": entry.get("link", ""),
                "image": None,
            }

            # Try to extract image from common RSS fields
            if "media_content" in entry and len(entry.media_content) > 0:
                item["image"] = entry.media_content[0].get("url")
            elif "media_thumbnail" in entry and len(entry.media_thumbnail) > 0:
                item["image"] = entry.media_thumbnail[0].get("url")
            elif "enclosures" in entry and len(entry.enclosures) > 0:
                item["image"] = entry.enclosures[0].get("url")

            items.append(item)

        return items
