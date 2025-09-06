import re
from io import BytesIO

import feedparser  # type: ignore[import-untyped]
import requests
from PIL import Image
from PIL.Image import Resampling

from plugins.base_plugin.base_plugin import BasePlugin
from utils.http_utils import http_get

LANCZOS = Resampling.LANCZOS

COMICS = [
    "XKCD",
    "Cyanide & Happiness",
    "Saturday Morning Breakfast Cereal",
    "The Perry Bible Fellowship",
    "Questionable Content",
    "Poorly Drawn Lines",
    "Dinosaur Comics",
]


class Comic(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["comics"] = COMICS
        return template_params

    def generate_image(self, settings, device_config):
        comic = settings.get("comic")
        if not comic or comic not in COMICS:
            raise RuntimeError("Invalid comic provided.")

        image_url = self.get_image_url(comic)
        if not image_url:
            raise RuntimeError("Failed to retrieve latest comic url.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]
        width, height = dimensions

        try:
            response = http_get(image_url, timeout=20, stream=True)
            response.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"Failed to download comic image: {str(e)}")

        with Image.open(BytesIO(response.content)) as img:
            img.thumbnail((width, height), LANCZOS)
            background = Image.new("RGB", (width, height), "white")
            background.paste(
                img, ((width - img.width) // 2, (height - img.height) // 2)
            )
            return background

    def get_image_url(self, comic) -> str:
        if comic == "XKCD":
            feed = feedparser.parse("https://xkcd.com/atom.xml")
            element = feed.entries[0].summary
        elif comic == "Saturday Morning Breakfast Cereal":
            feed = feedparser.parse("http://www.smbc-comics.com/comic/rss")
            element = feed.entries[0].description
        elif comic == "Questionable Content":
            feed = feedparser.parse("http://www.questionablecontent.net/QCRSS.xml")
            element = feed.entries[0].description
        elif comic == "The Perry Bible Fellowship":
            feed = feedparser.parse("https://pbfcomics.com/feed/")
            element = feed.entries[0].description
        elif comic == "Poorly Drawn Lines":
            feed = feedparser.parse("https://poorlydrawnlines.com/feed/")
            element = feed.entries[0].get("content", [{}])[0].get("value", "")
        elif comic == "Dinosaur Comics":
            feed = feedparser.parse("https://www.qwantz.com/rssfeed.php")
            element = feed.entries[0].summary
        elif comic == "Cyanide & Happiness":
            feed = feedparser.parse("https://explosm-1311.appspot.com/")
            element = feed.entries[0].summary
        match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', element)
        if match is None:
            raise RuntimeError("Could not find image URL in comic feed")
        src = match.group(1)
        return src
