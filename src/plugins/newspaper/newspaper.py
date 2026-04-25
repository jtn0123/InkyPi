import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import callout, schema, section, widget
from plugins.newspaper.constants import NEWSPAPERS
from utils.image_utils import get_image

logger = logging.getLogger(__name__)

FREEDOM_FORUM_URL = "https://cdn.freedomforum.org/dfp/jpg{}/lg/{}.jpg"
VALID_NEWSPAPER_SLUGS = {
    entry["slug"].upper() for entry in NEWSPAPERS if entry.get("slug")
}


class Newspaper(BasePlugin):  # type: ignore[misc, unused-ignore]
    def build_settings_schema(self) -> dict[str, object]:
        return cast(  # type: ignore[redundant-cast, unused-ignore]
            dict[str, object],
            schema(
                section(
                    "Source",
                    callout(
                        "Search by newspaper title or narrow by location. The linked inputs keep the selected edition and its slug in sync.",
                    ),
                    widget(
                        "newspaper-search", template="widgets/newspaper_search.html"
                    ),
                )
            ),
        )

    def generate_image(
        self, settings: Mapping[str, object], device_config: Any
    ) -> Image.Image:
        newspaper_slug = settings.get("newspaperSlug")
        if newspaper_slug and str(newspaper_slug).strip():
            newspaper_slug = str(newspaper_slug).strip().upper()
            if newspaper_slug not in VALID_NEWSPAPER_SLUGS:
                raise RuntimeError("Invalid newspaper selection.")
        else:
            newspaper_slug = "NY_NYT"

        # Get today's date
        today = datetime.now(tz=UTC)

        # check the next day, then today, then prior day
        days = [today + timedelta(days=diff) for diff in [1, 0, -1, -2]]

        image = None
        for date in days:
            image_url = FREEDOM_FORUM_URL.format(date.day, newspaper_slug)
            image = cast(Any, get_image)(image_url)
            if image:
                logger.info(
                    f"Found {newspaper_slug} front cover for {date.strftime('%Y-%m-%d')}"
                )
                break

        if image:
            # expand height if newspaper is wider than resolution
            img_width, img_height = image.size

            dimensions = self.get_oriented_dimensions(device_config)

            desired_width, desired_height = dimensions

            img_ratio = img_width / img_height
            desired_ratio = desired_width / desired_height

            if img_ratio < desired_ratio:
                new_height = int(img_width / desired_ratio)
                new_image = Image.new("RGB", (img_width, new_height), (255, 255, 255))
                new_image.paste(image, (0, 0))
                image = new_image
        else:
            raise RuntimeError("Newspaper front cover not found.")

        return image

    def generate_settings_template(self) -> dict[str, object]:
        template_params = super().generate_settings_template()
        template_params["newspapers"] = sorted(NEWSPAPERS, key=lambda n: n["name"])
        return cast(dict[str, object], template_params)  # type: ignore[redundant-cast, unused-ignore]
