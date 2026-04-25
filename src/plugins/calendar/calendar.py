import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Protocol
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
from PIL import Image, ImageColor

from plugins.base_plugin.base_plugin import BasePlugin, DeviceConfigLike
from plugins.base_plugin.settings_schema import (
    field,
    option,
    option_group,
    row,
    schema,
    section,
    widget,
)
from plugins.calendar.constants import FONT_SIZES, LOCALE_GROUPS, LOCALE_MAP
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)


class _CalendarEvent(Protocol):
    def decoded(self, key: str) -> object: ...

    def __contains__(self, key: str) -> bool: ...

    def get(self, key: str, default: object = None) -> object: ...


class Calendar(BasePlugin):
    def validate_settings(self, settings: Mapping[str, object]) -> str | None:
        """Reject non-URL ICS values at save time (JTN-357).

        Each submitted calendar URL must parse to an http(s) scheme with a
        non-empty host.  ``webcal://`` is also accepted because the runtime
        rewrites it to https before fetching.  Empty URLs and invalid values
        (e.g. ``not-a-url`` or ``javascript:alert(1)``) are rejected so the
        user cannot persist junk rows from the settings form.
        """
        calendar_urls = settings.get("calendarURLs[]")
        if not calendar_urls:
            return "At least one calendar URL is required."

        if not isinstance(calendar_urls, Sequence) or isinstance(calendar_urls, str):
            return "At least one calendar URL is required."

        allowed_schemes = {"http", "https", "webcal"}
        for raw in calendar_urls:
            url = raw.strip() if isinstance(raw, str) else ""
            if not url:
                return "Calendar URL is required."
            try:
                parsed = urlparse(url)
            except ValueError:
                return f"Calendar URL is not valid: {url!r}"
            if parsed.scheme.lower() not in allowed_schemes:
                return f"Calendar URL is not valid: {url!r}"
            if not parsed.netloc:
                return f"Calendar URL is not valid: {url!r}"
        return None

    def build_settings_schema(self) -> dict[str, object]:
        return schema(
            section(
                "Calendars",
                widget("calendar-repeater", template="widgets/calendar_repeater.html"),
            ),
            section(
                "Layout",
                row(
                    field(
                        "viewMode",
                        "radio_segment",
                        label="View",
                        default="dayGridMonth",
                        options=[
                            option("timeGridDay", "Day"),
                            option("timeGridWeek", "Week"),
                            option("dayGrid", "Multi-Week"),
                            option("dayGridMonth", "Month"),
                            option("listMonth", "List"),
                        ],
                    ),
                    field(
                        "language",
                        "select",
                        label="Language",
                        default="en",
                        options=[
                            option_group(
                                group_label,
                                *[option(code, name) for code, name in locales],
                            )
                            for group_label, locales in LOCALE_GROUPS
                        ],
                    ),
                    field(
                        "fontSize",
                        "select",
                        label="Font Size",
                        default="normal",
                        options=[
                            option(key, key.replace("-", " ").title())
                            for key in FONT_SIZES
                        ],
                    ),
                ),
            ),
            section(
                "Display",
                row(
                    field(
                        "displayTitle",
                        "checkbox",
                        label="Title",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                        default="true",
                    ),
                    field(
                        "displayWeekends",
                        "checkbox",
                        label="Weekends",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                        default="true",
                    ),
                    field(
                        "displayEventTime",
                        "checkbox",
                        label="Event Time",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                        default="true",
                    ),
                ),
                row(
                    field(
                        "displayNowIndicator",
                        "checkbox",
                        label="Now Indicator",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                        default="true",
                        visible_if={
                            "field": "viewMode",
                            "operator": "in",
                            "values": ["timeGridDay", "timeGridWeek"],
                        },
                    ),
                    field(
                        "nowIndicatorColor",
                        "color",
                        label="Now Indicator Color",
                        default="#007BFF",
                        visible_if={
                            "field": "viewMode",
                            "operator": "in",
                            "values": ["timeGridDay", "timeGridWeek"],
                        },
                    ),
                    field(
                        "displayPreviousDays",
                        "checkbox",
                        label="Include Previous Days",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                        default="true",
                        visible_if={"field": "viewMode", "equals": "timeGridWeek"},
                    ),
                ),
                row(
                    field(
                        "weekStartDay",
                        "select",
                        label="Week Starts On",
                        default="1",
                        options=[
                            option("0", "Sunday"),
                            option("1", "Monday"),
                            option("2", "Tuesday"),
                            option("3", "Wednesday"),
                            option("4", "Thursday"),
                            option("5", "Friday"),
                            option("6", "Saturday"),
                        ],
                        visible_if={
                            "field": "viewMode",
                            "operator": "in",
                            "values": ["timeGridWeek", "dayGrid", "dayGridMonth"],
                        },
                    ),
                    field(
                        "startTimeInterval",
                        "time",
                        label="Start Time",
                        visible_if={
                            "field": "viewMode",
                            "operator": "in",
                            "values": ["timeGridDay", "timeGridWeek"],
                        },
                    ),
                    field(
                        "endTimeInterval",
                        "time",
                        label="End Time",
                        visible_if={
                            "field": "viewMode",
                            "operator": "in",
                            "values": ["timeGridDay", "timeGridWeek"],
                        },
                    ),
                ),
                row(
                    field(
                        "displayWeeks",
                        "number",
                        label="Weeks to Show",
                        min=1,
                        max=8,
                        default="4",
                        visible_if={"field": "viewMode", "equals": "dayGrid"},
                    ),
                ),
            ),
        )

    def generate_settings_template(self) -> dict[str, object]:
        template_params = super().generate_settings_template()
        template_params["style_settings"] = True
        template_params["locale_map"] = LOCALE_MAP
        return template_params

    def generate_image(
        self, settings: Mapping[str, object], device_config: DeviceConfigLike
    ) -> Image.Image:
        calendar_urls = settings.get("calendarURLs[]")
        calendar_colors = settings.get("calendarColors[]")
        view = settings.get("viewMode")

        if not isinstance(view, str):
            raise RuntimeError("View is required")
        if view not in [
            "timeGridDay",
            "timeGridWeek",
            "dayGrid",
            "dayGridMonth",
            "listMonth",
        ]:
            raise RuntimeError("Invalid view")

        if not isinstance(calendar_urls, Sequence) or isinstance(calendar_urls, str):
            raise RuntimeError("At least one calendar URL is required")
        if not isinstance(calendar_colors, Sequence) or isinstance(
            calendar_colors, str
        ):
            raise RuntimeError("At least one calendar color is required")

        for raw_url in calendar_urls:
            if not isinstance(raw_url, str) or not raw_url.strip():
                raise RuntimeError("Invalid calendar URL")

        calendar_url_list: list[str] = [
            raw_url for raw_url in calendar_urls if isinstance(raw_url, str)
        ]

        calendar_color_list: list[str] = []
        for raw_color in calendar_colors:
            if not isinstance(raw_color, str):
                raise RuntimeError("Invalid calendar color")
            calendar_color_list.append(raw_color)

        dimensions = self.get_oriented_dimensions(device_config)

        timezone_config = device_config.get_config(
            "timezone", default="America/New_York"
        )
        timezone = (
            timezone_config if isinstance(timezone_config, str) else "America/New_York"
        )
        time_format = device_config.get_config("time_format", default="12h")
        tz = ZoneInfo(timezone)

        current_dt = datetime.now(tz)
        start, end = self.get_view_range(view, current_dt, settings)
        logger.debug(f"Fetching events for {start} --> [{current_dt}] --> {end}")
        events = self.fetch_ics_events(
            calendar_url_list,
            calendar_color_list,
            tz,
            start,
            end,
        )

        if not events:
            logger.warning("No events found for ics url")

        if view == "timeGridWeek" and settings.get("displayPreviousDays") != "true":
            view = "timeGrid"

        font_size_key = settings.get("fontSize", "normal")
        font_scale = FONT_SIZES.get(
            font_size_key if isinstance(font_size_key, str) else "normal", 1
        )

        template_params = {
            "view": view,
            "events": events,
            "current_dt": current_dt.replace(
                minute=0, second=0, microsecond=0
            ).isoformat(),
            "timezone": timezone,
            "plugin_settings": settings,
            "time_format": time_format,
            "font_scale": font_scale,
        }

        image = self.render_image(
            dimensions, "calendar.html", "calendar.css", template_params
        )

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image

    def fetch_ics_events(
        self,
        calendar_urls: Iterable[str],
        colors: Iterable[str],
        tz: ZoneInfo,
        start_range: datetime,
        end_range: datetime,
    ) -> list[dict[str, object]]:
        parsed_events: list[dict[str, object]] = []

        for calendar_url, color in zip(calendar_urls, colors, strict=False):
            cal = self.fetch_calendar(calendar_url)
            events = recurring_ical_events.of(cal).between(start_range, end_range)
            contrast_color = self.get_contrast_color(color)

            for event in events:
                start, end, all_day = self.parse_data_points(event, tz)
                parsed_event: dict[str, object] = {
                    "title": str(event.get("summary")),
                    "start": start,
                    "backgroundColor": color,
                    "textColor": contrast_color,
                    "allDay": all_day,
                }
                if end:
                    parsed_event["end"] = end
                parsed_events.append(parsed_event)

        return parsed_events

    def get_view_range(
        self, view: str, current_dt: datetime, settings: Mapping[str, object]
    ) -> tuple[datetime, datetime]:
        tz = current_dt.tzinfo
        start = datetime(current_dt.year, current_dt.month, current_dt.day, tzinfo=tz)
        end = start

        if view == "timeGridDay":
            end = start + timedelta(days=1)
        elif view == "timeGridWeek":
            if settings.get("displayPreviousDays") == "true":
                week_start_day = settings.get("weekStartDay", 1)
                if isinstance(week_start_day, (str, int, float)):
                    try:
                        week_start_day_int = int(week_start_day)
                    except (TypeError, ValueError):
                        week_start_day_int = 1
                else:
                    week_start_day_int = 1
                python_week_start = (week_start_day_int - 1) % 7
                offset = (current_dt.weekday() - python_week_start) % 7
                start = current_dt - timedelta(days=offset)
                start = datetime(start.year, start.month, start.day, tzinfo=tz)
            end = start + timedelta(days=7)
        elif view == "dayGrid":
            start = current_dt - timedelta(weeks=1)
            display_weeks = settings.get("displayWeeks")
            if isinstance(display_weeks, (str, int, float)):
                try:
                    display_weeks_value = int(display_weeks)
                except (TypeError, ValueError):
                    display_weeks_value = 4
            else:
                display_weeks_value = 4
            end = current_dt + timedelta(weeks=display_weeks_value)
        elif view == "dayGridMonth":
            start = datetime(
                current_dt.year, current_dt.month, 1, tzinfo=tz
            ) - timedelta(weeks=1)
            end = datetime(current_dt.year, current_dt.month, 1, tzinfo=tz) + timedelta(
                weeks=6
            )
        elif view == "listMonth":
            end = start + timedelta(weeks=5)

        return start, end

    def parse_data_points(
        self, event: _CalendarEvent, tz: ZoneInfo
    ) -> tuple[str, str | None, bool]:
        all_day = False
        dtstart = event.decoded("dtstart")
        dtend_or_duration: object

        if isinstance(dtstart, datetime):
            start = dtstart.astimezone(tz).isoformat()
            dtend_or_duration = dtstart
        elif isinstance(dtstart, date):
            start = dtstart.isoformat()
            all_day = True
            dtend_or_duration = dtstart
        else:
            start = str(dtstart)
            dtend_or_duration = dtstart
            all_day = True

        end = None
        if "dtend" in event:
            dtend = event.decoded("dtend")
            if isinstance(dtend, datetime):
                end = dtend.astimezone(tz).isoformat()
            elif isinstance(dtend, date):
                end = dtend.isoformat()
            else:
                end = str(dtend)
        elif "duration" in event:
            duration = event.decoded("duration")
            if isinstance(duration, timedelta) and isinstance(
                dtend_or_duration, datetime | date
            ):
                end = (dtend_or_duration + duration).isoformat()
        return start, end, all_day

    def fetch_calendar(self, calendar_url: str) -> icalendar.Calendar:
        # workaround for webcal urls
        if calendar_url.startswith("webcal://"):
            calendar_url = calendar_url.replace("webcal://", "https://")
        try:
            response = get_http_session().get(calendar_url, timeout=30)
            response.raise_for_status()
            return icalendar.Calendar.from_ical(response.text)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch iCalendar url: {str(e)}") from e

    def get_contrast_color(self, color: str) -> str:
        """
        Returns '#000000' (black) or '#ffffff' (white) depending on the contrast
        against the given color.
        """
        r, g, b = ImageColor.getrgb(color)
        # YIQ formula to estimate brightness
        yiq = (r * 299 + g * 587 + b * 114) / 1000

        return "#000000" if yiq >= 150 else "#ffffff"
