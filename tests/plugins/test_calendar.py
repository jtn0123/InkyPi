# pyright: reportMissingImports=false
import pytest
from datetime import datetime, date, timedelta
import pytz


def _make_calendar_settings(
    view="timeGridDay",
    urls=None,
    colors=None,
    extra=None,
):
    settings = {
        "viewMode": view,
        "calendarURLs[]": urls if urls is not None else ["http://example.com/a.ics"],
        "calendarColors[]": colors if colors is not None else ["#969696"],
    }
    if extra:
        settings.update(extra)
    return settings


def test_generate_image_missing_view_raises(device_config_dev):
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    with pytest.raises(RuntimeError):
        p.generate_image({"calendarURLs[]": ["http://x"], "calendarColors[]": ["#000"]}, device_config_dev)


def test_generate_image_invalid_view_raises(device_config_dev):
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    with pytest.raises(RuntimeError):
        p.generate_image(_make_calendar_settings(view="invalid"), device_config_dev)


def test_generate_image_missing_urls_raises(device_config_dev):
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    with pytest.raises(RuntimeError):
        p.generate_image({"viewMode": "timeGridDay"}, device_config_dev)


def test_generate_image_blank_url_raises(device_config_dev):
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    with pytest.raises(RuntimeError):
        p.generate_image(_make_calendar_settings(urls=[" "]), device_config_dev)


def test_get_view_range_timeGridDay():
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    now = datetime(2025, 1, 15, 10, 30)
    start, end = p.get_view_range("timeGridDay", now, {})
    assert start == datetime(2025, 1, 15, 0, 0)
    assert end == start + timedelta(days=1)


def test_get_view_range_timeGridWeek_default():
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    now = datetime(2025, 1, 15, 10, 30)  # Wednesday
    start, end = p.get_view_range("timeGridWeek", now, {})
    assert start == datetime(2025, 1, 15, 0, 0)
    assert end == start + timedelta(days=7)


def test_get_view_range_timeGridWeek_display_previous_days():
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    now = datetime(2025, 1, 15, 10, 30)  # Wednesday (weekday() == 2)
    start, end = p.get_view_range("timeGridWeek", now, {"displayPreviousDays": "true"})
    assert start == datetime(2025, 1, 13, 0, 0)  # Monday of that week
    assert end == start + timedelta(days=7)


def test_get_view_range_dayGridMonth():
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    now = datetime(2025, 1, 15, 10, 30)
    start, end = p.get_view_range("dayGridMonth", now, {})
    assert start == datetime(2024, 12, 25, 0, 0)  # 2025-01-01 minus 7 days
    assert end == datetime(2025, 2, 12, 0, 0)     # 2025-01-01 plus 6 weeks


def test_get_view_range_listMonth():
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    now = datetime(2025, 1, 15, 10, 30)
    start, end = p.get_view_range("listMonth", now, {})
    assert start == datetime(2025, 1, 15, 0, 0)
    assert end == start + timedelta(weeks=5)


class FakeEvent:
    def __init__(self, mapping):
        self._mapping = dict(mapping)

    def decoded(self, key):
        return self._mapping[key]

    def __contains__(self, key):
        return key in self._mapping

    def get(self, key, default=None):
        return self._mapping.get(key, default)


def test_parse_data_points_datetime_with_dtend():
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    tz = pytz.timezone("US/Eastern")

    dt_start = datetime(2025, 1, 1, 12, 0, tzinfo=pytz.UTC)
    dt_end = datetime(2025, 1, 1, 13, 0, tzinfo=pytz.UTC)
    event = FakeEvent({
        "dtstart": dt_start,
        "dtend": dt_end,
    })
    start, end, all_day = p.parse_data_points(event, tz)
    assert start.endswith("-05:00") or start.endswith("-04:00")  # timezone adjusted
    assert end.endswith("-05:00") or end.endswith("-04:00")
    assert all_day is False


def test_parse_data_points_date_all_day_and_duration():
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    tz = pytz.UTC

    d = date(2025, 1, 1)
    event = FakeEvent({
        "dtstart": d,
        "duration": timedelta(days=1),
    })
    start, end, all_day = p.parse_data_points(event, tz)
    assert start == d.isoformat()
    assert end == (d + timedelta(days=1)).isoformat()
    assert all_day is True


def test_fetch_calendar_timeout_raises(monkeypatch):
    from plugins.calendar.calendar import Calendar
    import requests

    def raise_timeout(url, **kwargs):
        raise requests.exceptions.Timeout("timeout")

    monkeypatch.setattr("plugins.calendar.calendar.requests.get", raise_timeout, raising=True)

    p = Calendar({"id": "calendar"})
    with pytest.raises(RuntimeError):
        p.fetch_calendar("http://example.com/a.ics")


def test_fetch_calendar_http_error_raises(monkeypatch):
    from plugins.calendar.calendar import Calendar
    import requests

    class Resp:
        def raise_for_status(self):
            raise requests.HTTPError("bad status")

    monkeypatch.setattr("plugins.calendar.calendar.requests.get", lambda url, **kwargs: Resp(), raising=True)

    p = Calendar({"id": "calendar"})
    with pytest.raises(RuntimeError):
        p.fetch_calendar("http://example.com/a.ics")


def test_fetch_calendar_bad_ical_raises(monkeypatch):
    from plugins.calendar.calendar import Calendar

    class Resp:
        text = "not an ical"
        def raise_for_status(self):
            return None

    # Return a 200 OK but break ical parsing
    monkeypatch.setattr("plugins.calendar.calendar.requests.get", lambda url, **kwargs: Resp(), raising=True)

    class FakeCal:
        @staticmethod
        def from_ical(_text):
            raise ValueError("parse error")

    import plugins.calendar.calendar as cal_mod
    monkeypatch.setattr(cal_mod.icalendar.Calendar, "from_ical", staticmethod(FakeCal.from_ical), raising=True)

    p = Calendar({"id": "calendar"})
    with pytest.raises(RuntimeError):
        p.fetch_calendar("http://example.com/a.ics")


def test_get_contrast_color_threshold():
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    # yiq == 150 -> black
    assert p.get_contrast_color("#969696") == "#000000"
    # yiq == 149 -> white
    assert p.get_contrast_color("#959595") == "#ffffff"


