import logging
from datetime import datetime, timedelta

from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.newspaper.constants import NEWSPAPERS
from utils.image_utils import get_image

logger = logging.getLogger(__name__)

# Canonical template for building Freedom Forum front page image URLs.
# Note: Historically the CDN layout has varied across months and sizes.
# We will construct candidates from these components and try fallbacks.
FREEDOM_FORUM_URL = "https://cdn.freedomforum.org/dfp/{}/{}/{}.jpg"


class Newspaper(BasePlugin):
    def generate_image(self, settings, device_config):
        newspaper_slug = settings.get("newspaperSlug")

        if not newspaper_slug:
            raise RuntimeError("Newspaper input not provided.")
        # Use slug as-provided by settings (UI provides canonical value from constants).
        # We'll try multiple case variants as fallbacks below to be robust.
        provided_slug = str(newspaper_slug)

        # Get today's date
        today = datetime.today()

        # Check the next day, then today, then prior two days (covers early postings and delays)
        days = [today + timedelta(days=diff) for diff in [1, 0, -1, -2]]

        image = None
        image_url = None
        pulled_date = None

        # Build ordered candidate lists to try
        def build_month_dir_variants(month_number: int) -> list[str]:
            # Some months may be stored as jpg9 and others as jpg09; try both
            return [f"jpg{month_number}", f"jpg{month_number:02d}"]

        size_folder_variants = ["lg", "md", "sm"]
        # Try provided (likely lowercase from constants) first, then uppercase, then lowercase explicitly
        def build_slug_variants(slug: str) -> list[str]:
            variants = []
            for v in [slug, slug.upper(), slug.lower()]:
                if v not in variants:
                    variants.append(v)
            return variants

        for date in days:
            for month_dir in build_month_dir_variants(date.month):
                for size_folder in size_folder_variants:
                    for slug_variant in build_slug_variants(provided_slug):
                        candidate_url = FREEDOM_FORUM_URL.format(
                            month_dir, size_folder, slug_variant
                        )
                        candidate_img = get_image(candidate_url)
                        if candidate_img:
                            image = candidate_img
                            image_url = candidate_url
                            pulled_date = date
                            try:
                                logger.info(
                                    "Found %s front cover for %s using %s",
                                    slug_variant,
                                    date.strftime("%Y-%m-%d"),
                                    candidate_url,
                                )
                            except Exception:
                                pass
                            break
                    if image:
                        break
                if image:
                    break
            if image:
                break

        if image:
            # expand height if newspaper is wider than resolution
            img_width, img_height = image.size
            desired_width, desired_height = device_config.get_resolution()

            img_ratio = img_width / img_height
            desired_ratio = desired_width / desired_height

            if img_ratio < desired_ratio:
                new_height = int((img_width * desired_width) / desired_height)
                new_image = Image.new("RGB", (img_width, new_height), (255, 255, 255))
                new_image.paste(image, (0, 0))
                image = new_image
        else:
            raise RuntimeError("Newspaper front cover not found.")

        # Provide minimal metadata for UI (which paper and date detected)
        try:
            plugin_meta = {
                "date": pulled_date.strftime("%Y-%m-%d") if pulled_date else None,
                "title": f"{provided_slug} front page",
                "image_url": image_url if image else None,
            }
            self.set_latest_metadata(plugin_meta)
        except Exception:
            pass

        return image

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["newspapers"] = sorted(NEWSPAPERS, key=lambda n: n["name"])
        return template_params
