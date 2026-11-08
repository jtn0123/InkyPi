import base64
import html
import logging
import re
from collections.abc import Mapping
from io import BytesIO
from time import monotonic
from typing import Any
from urllib.parse import urlparse

import feedparser
from PIL import Image
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
from utils.http_utils import (
    fetch_feed_bytes,
    private_feeds_allowed,
    safe_fetch_bytes,
)

logger = logging.getLogger(__name__)

#: Upper bound on a downloaded feed document.  Real feeds are tens to
#: hundreds of KB; the cap stops a hostile or broken server from exhausting
#: memory on a Pi Zero.
MAX_FEED_BYTES = 5 * 1024 * 1024

#: Item images are fetched server-side through the SSRF guard and inlined as
#: ``data:`` URIs, so the render Chromium never makes a network request
#: (grade report E2). These caps bound what one feed can make the Pi download.
MAX_RENDERED_ITEMS = 10
MAX_ITEM_IMAGE_BYTES = 2 * 1024 * 1024
MAX_ITEM_IMAGE_PIXELS = 25_000_000
ITEM_IMAGE_TIMEOUT = (3.0, 5.0)
ITEM_IMAGE_BUDGET_SECONDS = 20.0
#: Re-encoded thumbnail bound; the template shows images at a few hundred px.
ITEM_IMAGE_MAX_SIDE = 400

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

        items = self.parse_rss_feed(feed_url)[:MAX_RENDERED_ITEMS]
        include_images = settings.get("includeImages") == "true"
        if include_images:
            self._inline_item_images(items)
        else:
            for item in items:
                item["image"] = None

        dimensions = self.get_oriented_dimensions(device_config)

        template_params = {
            "title": title,
            "include_images": include_images,
            "items": items,
            "font_scale": font_scale,
            "plugin_settings": settings,
        }

        return self.render_image(dimensions, "rss.html", "rss.css", template_params)

    @staticmethod
    def _inline_item_images(items: list[dict[str, str | None]]) -> None:
        """Replace each item's feed-supplied image URL with a ``data:`` URI.

        Only the items about to be rendered are passed in. Every fetch goes
        through :func:`utils.http_utils.safe_fetch_bytes` (scheme check,
        private/loopback/link-local rejection with per-hop DNS pinning, size
        cap). Images that fail the guard, time out, exceed a cap or do not
        decode are dropped. Once the overall time budget is spent the
        remaining images are dropped too.
        """
        deadline = monotonic() + ITEM_IMAGE_BUDGET_SECONDS
        for item in items:
            url = item.get("image")
            item["image"] = None
            if not url or monotonic() >= deadline:
                continue
            item["image"] = Rss._fetch_item_image(url)

    @staticmethod
    def _fetch_item_image(url: str) -> str | None:
        """Fetch *url* through the SSRF guard and return a re-encoded data URI."""
        try:
            content = safe_fetch_bytes(
                url,
                max_bytes=MAX_ITEM_IMAGE_BYTES,
                timeout=ITEM_IMAGE_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
                allow_lan=private_feeds_allowed(),
                session=get_http_session(),
            )
        except Exception as exc:
            logger.info("RSS item image dropped | reason=%s", type(exc).__name__)
            return None
        try:
            return Rss._to_data_uri(content)
        except Exception as exc:
            logger.info("RSS item image undecodable | reason=%s", type(exc).__name__)
            return None

    @staticmethod
    def _to_data_uri(content: bytes) -> str | None:
        """Decode *content* with Pillow and re-encode a bounded JPEG data URI.

        Re-encoding means Chromium only ever decodes bytes Pillow produced,
        never attacker-supplied image data.
        """
        with Image.open(BytesIO(content)) as img:
            width, height = img.size
            if width * height > MAX_ITEM_IMAGE_PIXELS:
                return None
            img.draft("RGB", (ITEM_IMAGE_MAX_SIDE, ITEM_IMAGE_MAX_SIDE))
            img.thumbnail((ITEM_IMAGE_MAX_SIDE, ITEM_IMAGE_MAX_SIDE))
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
            else:
                flat = img.convert("RGB")
        out = BytesIO()
        flat.save(out, format="JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode(
            "ascii"
        )

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
        # SSRF-guarded (every redirect hop is validated; LAN hosts need the
        # INKYPI_ALLOW_PRIVATE_FEEDS opt-in) and size-capped.
        content = fetch_feed_bytes(
            url,
            max_bytes=MAX_FEED_BYTES,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
            session=get_http_session(),
        )

        # Parse the feed content
        feed = feedparser.parse(content)
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
