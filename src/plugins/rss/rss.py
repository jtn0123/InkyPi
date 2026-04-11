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

# Only http(s) feeds are supported; anything else (file://, javascript:, ftp://,
# bare strings like "not-a-feed") is rejected at save time so the user sees the
# problem immediately instead of discovering it later when generate_image runs.
_ALLOWED_FEED_SCHEMES = frozenset({"http", "https"})


class Rss(BasePlugin):
    def validate_settings(self, settings: dict) -> str | None:
        """Reject non-URL RSS feed values at save time (JTN-380).

        The frontend ``<input type="url">`` enforces a URL-shaped value, but a
        direct POST can still bypass it. Without server-side validation a bad
        feed URL (e.g. ``definitely-not-a-feed-url``) persists with a success
        toast and only fails later when the plugin tries to fetch the feed.
        """
        feed_url = (settings.get("feedUrl") or "").strip()
        if not feed_url:
            # ``required=True`` + validate_plugin_required_fields already
            # rejects missing values with its own error message.
            return None
        try:
            parsed = urlparse(feed_url)
        except ValueError:
            return f"Invalid RSS Feed URL: {feed_url!r}"
        scheme = (parsed.scheme or "").lower()
        if scheme not in _ALLOWED_FEED_SCHEMES:
            return (
                "RSS Feed URL must start with http:// or https:// "
                f"(got {feed_url!r})."
            )
        if not parsed.netloc:
            return f"RSS Feed URL is missing a host: {feed_url!r}"
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
                    hint="Must start with http:// or https://",
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

        image = self.render_image(dimensions, "rss.html", "rss.css", template_params)
        return image

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
