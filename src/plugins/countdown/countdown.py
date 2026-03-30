import logging
from datetime import datetime

import pytz

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import field, row, schema, section

logger = logging.getLogger(__name__)


class Countdown(BasePlugin):
    def build_settings_schema(self):
        return schema(
            section(
                "Countdown",
                row(
                    field(
                        "title",
                        label="Title",
                        placeholder="Vacation",
                        required=True,
                    ),
                    field("date", "date", label="Target Date"),
                ),
            )
        )

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["style_settings"] = True
        return template_params

    def generate_image(self, settings, device_config):
        title = settings.get("title")
        countdown_date_str = settings.get("date")

        if not countdown_date_str:
            raise RuntimeError("Date is required.")

        dimensions = self.get_oriented_dimensions(device_config)

        tz_name = device_config.get_config("timezone", default="America/New_York")
        tz = pytz.timezone(tz_name)
        current_time = datetime.now(tz)

        countdown_date = datetime.strptime(countdown_date_str, "%Y-%m-%d")
        countdown_date = tz.localize(countdown_date)

        day_count = (countdown_date.date() - current_time.date()).days
        label = "Days Left" if day_count > 0 else "Days Passed"

        template_params = {
            "title": title,
            "date": countdown_date.strftime("%B %d, %Y"),
            "day_count": abs(day_count),
            "label": label,
            "plugin_settings": settings,
        }

        image = self.render_image(
            dimensions, "countdown.html", "countdown.css", template_params
        )
        return image
