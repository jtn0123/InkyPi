import logging
from datetime import datetime, timedelta

import icalendar
import pytz
import recurring_ical_events
import requests
from PIL import ImageColor

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.base_plugin.settings_schema import (
    field,
    option,
    row,
    schema,
    section,
    widget,
)
from plugins.calendar.constants import FONT_SIZES, LOCALE_MAP

logger = logging.getLogger(__name__)

class Calendar(BasePlugin):
    def build_settings_schema(self):
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
                        options=[option(code, name) for code, name in LOCALE_MAP.items()],
                    ),
                    field(
                        "fontSize",
                        "select",
                        label="Font Size",
                        default="normal",
                        options=[option(key, key.replace("-", " ").title()) for key in FONT_SIZES.keys()],
                    ),
                ),
            ),
            section(
                "Display",
                row(
                    field("displayTitle", "checkbox", label="Title", submit_unchecked=True, checked_value="true", unchecked_value="false", default="true"),
                    field("displayWeekends", "checkbox", label="Weekends", submit_unchecked=True, checked_value="true", unchecked_value="false", default="true"),
                    field("displayEventTime", "checkbox", label="Event Time", submit_unchecked=True, checked_value="true", unchecked_value="false", default="true"),
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
                        visible_if={"field": "viewMode", "operator": "in", "values": ["timeGridDay", "timeGridWeek"]},
                    ),
                    field(
                        "nowIndicatorColor",
                        "color",
                        label="Now Indicator Color",
                        default="#007BFF",
                        visible_if={"field": "viewMode", "operator": "in", "values": ["timeGridDay", "timeGridWeek"]},
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
                        visible_if={"field": "viewMode", "operator": "in", "values": ["timeGridWeek", "dayGrid", "dayGridMonth"]},
                    ),
                    field(
                        "startTimeInterval",
                        "time",
                        label="Start Time",
                        visible_if={"field": "viewMode", "operator": "in", "values": ["timeGridDay", "timeGridWeek"]},
                    ),
                    field(
                        "endTimeInterval",
                        "time",
                        label="End Time",
                        visible_if={"field": "viewMode", "operator": "in", "values": ["timeGridDay", "timeGridWeek"]},
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

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        template_params['locale_map'] = LOCALE_MAP
        return template_params

    def generate_image(self, settings, device_config):
        calendar_urls = settings.get('calendarURLs[]')
        calendar_colors = settings.get('calendarColors[]')
        view = settings.get("viewMode")

        if not view:
            raise RuntimeError("View is required")
        elif view not in ["timeGridDay", "timeGridWeek", "dayGrid", "dayGridMonth", "listMonth"]:
            raise RuntimeError("Invalid view")

        if not calendar_urls:
            raise RuntimeError("At least one calendar URL is required")
        for url in calendar_urls:
            if not url.strip():
                raise RuntimeError("Invalid calendar URL")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]
        
        timezone = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        tz = pytz.timezone(timezone)

        current_dt = datetime.now(tz)
        start, end = self.get_view_range(view, current_dt, settings)
        logger.debug(f"Fetching events for {start} --> [{current_dt}] --> {end}")
        events = self.fetch_ics_events(calendar_urls, calendar_colors, tz, start, end)
        if not events:
            logger.warning("No events found for ics url")

        if view == 'timeGridWeek' and settings.get("displayPreviousDays") != "true":
            view = 'timeGrid'

        template_params = {
            "view": view,
            "events": events,
            "current_dt": current_dt.replace(minute=0, second=0, microsecond=0).isoformat(),
            "timezone": timezone,
            "plugin_settings": settings,
            "time_format": time_format,
            "font_scale": FONT_SIZES.get(settings.get("fontSize", "normal"))
        }

        image = self.render_image(dimensions, "calendar.html", "calendar.css", template_params)

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image
    
    def fetch_ics_events(self, calendar_urls, colors, tz, start_range, end_range):
        parsed_events = []

        for calendar_url, color in zip(calendar_urls, colors):
            cal = self.fetch_calendar(calendar_url)
            events = recurring_ical_events.of(cal).between(start_range, end_range)
            contrast_color = self.get_contrast_color(color)

            for event in events:
                start, end, all_day = self.parse_data_points(event, tz)
                parsed_event = {
                    "title": str(event.get("summary")),
                    "start": start,
                    "backgroundColor": color,
                    "textColor": contrast_color,
                    "allDay": all_day
                }
                if end:
                    parsed_event['end'] = end

                parsed_events.append(parsed_event)

        return parsed_events
    
    def get_view_range(self, view, current_dt, settings):
        start = datetime(current_dt.year, current_dt.month, current_dt.day)
        if view == "timeGridDay":
            end = start + timedelta(days=1)
        elif view == "timeGridWeek":
            if settings.get("displayPreviousDays") == "true":
                week_start_day = int(settings.get("weekStartDay", 1))
                python_week_start = (week_start_day - 1) % 7
                offset = (current_dt.weekday() - python_week_start) % 7
                start = current_dt - timedelta(days=offset)
                start = datetime(start.year, start.month, start.day)
            end = start + timedelta(days=7)
        elif view == "dayGrid":
            start = current_dt - timedelta(weeks=1)
            end = current_dt + timedelta(weeks=int(settings.get("displayWeeks") or 4))
        elif view == "dayGridMonth":
            start = datetime(current_dt.year, current_dt.month, 1) - timedelta(weeks=1)
            end = datetime(current_dt.year, current_dt.month, 1) + timedelta(weeks=6)
        elif view == "listMonth":
            end = start + timedelta(weeks=5)
        return start, end
        
    def parse_data_points(self, event, tz):
        all_day = False
        dtstart = event.decoded("dtstart")
        if isinstance(dtstart, datetime):
            start = dtstart.astimezone(tz).isoformat()
        else:
            start = dtstart.isoformat()
            all_day = True

        end = None
        if "dtend" in event:
            dtend = event.decoded("dtend")
            if isinstance(dtend, datetime):
                end = dtend.astimezone(tz).isoformat()
            else:
                end = dtend.isoformat()
        elif "duration" in event:
            duration = event.decoded("duration")
            end = (dtstart + duration).isoformat()
        return start, end, all_day

    def fetch_calendar(self, calendar_url):
        # workaround for webcal urls
        if calendar_url.startswith("webcal://"):
            calendar_url = calendar_url.replace("webcal://", "https://")
        try:
            response = requests.get(calendar_url, timeout=30)
            response.raise_for_status()
            return icalendar.Calendar.from_ical(response.text)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch iCalendar url: {str(e)}")

    def get_contrast_color(self, color):
        """
        Returns '#000000' (black) or '#ffffff' (white) depending on the contrast
        against the given color.
        """
        r, g, b = ImageColor.getrgb(color)
        # YIQ formula to estimate brightness
        yiq = (r * 299 + g * 587 + b * 114) / 1000

        return '#000000' if yiq >= 150 else '#ffffff'
