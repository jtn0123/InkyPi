import html
import logging
import re

import feedparser
import requests

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import (
    callout,
    field,
    option,
    row,
    schema,
    section,
)

logger = logging.getLogger(__name__)

FONT_SIZES = {"x-small": 0.7, "small": 0.9, "normal": 1, "large": 1.1, "x-large": 1.3}


class Rss(BasePlugin):
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
                    label="RSS Feed URL",
                    placeholder="https://example.com/feed.xml",
                    required=True,
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

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

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
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
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
