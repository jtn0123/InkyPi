import logging
from datetime import UTC, date, datetime, timedelta

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import field, row, schema, section
from utils.time_utils import get_timezone

logger = logging.getLogger(__name__)


class Countdown(BasePlugin):
    def validate_settings(self, settings: dict) -> str | None:
        """Reject invalid countdown dates at save time."""
        date_str = (settings.get("date") or "").strip()
        if not date_str:
            return "Date is required."
        try:
            date.fromisoformat(date_str)
        except ValueError:
            return f"Invalid date format: {date_str!r} (expected YYYY-MM-DD)"
        return None

    def build_settings_schema(self):
        tomorrow = (datetime.now(tz=UTC) + timedelta(days=1)).strftime("%Y-%m-%d")
        return schema(
            section(
                "Countdown",
                row(
                    field(
                        "title",
                        label="Title",
                        placeholder="Required title, e.g. Vacation",
                        required=True,
                    ),
                    field("date", "date", label="Target Date", default=tomorrow),
                ),
            )
        )

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["style_settings"] = True
        return template_params

    def generate_image(self, settings, device_config):
        dimensions = self.get_oriented_dimensions(device_config)

        tz_name = device_config.get_config("timezone", default="America/New_York")
        tz = get_timezone(tz_name)
        current_time = datetime.now(tz)

        title = settings.get("title") or "Countdown"
        countdown_date_str = settings.get("date")
        try:
            countdown_date = datetime.strptime(  # noqa: DTZ007
                countdown_date_str or "", "%Y-%m-%d"
            ).replace(tzinfo=tz)
        except ValueError:
            # Fall back to 30 days out so the plugin renders something useful
            # even when called with no configured date (e.g. first-run preview).
            countdown_date = (current_time + timedelta(days=30)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        day_count = (countdown_date.date() - current_time.date()).days
        label = "Days Left" if day_count > 0 else "Days Passed"

        template_params = {
            "title": title,
            "date": countdown_date.strftime("%B %d, %Y"),
            "day_count": abs(day_count),
            "label": label,
            "plugin_settings": settings,
        }

        return self.render_image(
            dimensions, "countdown.html", "countdown.css", template_params
        )
