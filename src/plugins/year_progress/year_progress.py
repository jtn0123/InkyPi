import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from PIL.Image import Image as ImageType

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class YearProgress(BasePlugin):
    def generate_settings_template(self) -> dict[str, object]:
        template_params: dict[str, object] = super().generate_settings_template()
        template_params["style_settings"] = True
        return template_params

    def generate_image(
        self, settings: Mapping[str, object], device_config: Any
    ) -> ImageType:
        dimensions = self.get_oriented_dimensions(device_config)

        tz_name = device_config.get_config("timezone", default="America/New_York")
        tz = ZoneInfo(tz_name)
        current_time = datetime.now(tz)

        start_of_year = datetime(current_time.year, 1, 1, tzinfo=tz)
        start_of_next_year = datetime(current_time.year + 1, 1, 1, tzinfo=tz)

        total_days = (start_of_next_year - start_of_year).days
        days_left = (start_of_next_year - current_time).total_seconds() / (24 * 3600)
        elapsed_days = (current_time - start_of_year).total_seconds() / (24 * 3600)

        template_params = {
            "year": current_time.year,
            "year_percent": round((elapsed_days / total_days) * 100),
            "days_left": round(days_left),
            "plugin_settings": settings,
        }

        return self.render_image(
            dimensions, "year_progress.html", "year_progress.css", template_params
        )
