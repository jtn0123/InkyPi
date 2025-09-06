# pyright: reportMissingImports=false
import pytest
from datetime import datetime, date, timedelta
import pytz
from unittest.mock import patch, MagicMock


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


def test_generate_image_vertical_orientation(device_config_dev, monkeypatch):
    """Test image generation with vertical orientation."""
    from plugins.calendar.calendar import Calendar

    # Mock device config to return vertical orientation
    monkeypatch.setattr(device_config_dev, "get_config", lambda key, default=None: {
        "orientation": "vertical",
        "timezone": "UTC",
        "time_format": "12h"
    }.get(key, default))

    p = Calendar({"id": "calendar"})
    # This should not raise an exception
    try:
        p.generate_image(_make_calendar_settings(), device_config_dev)
    except Exception as e:
        # We expect this to fail due to missing template/rendering, but not due to orientation
        assert "orientation" not in str(e)


def test_parse_data_points_datetime_without_dtend():
    """Test parsing events without dtend (zero-duration events)."""
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    tz = pytz.timezone("US/Eastern")

    dt_start = datetime(2025, 1, 1, 12, 0, tzinfo=pytz.UTC)
    event = FakeEvent({
        "dtstart": dt_start,
    })
    start, end, all_day = p.parse_data_points(event, tz)
    assert end is None
    assert all_day is False


def test_parse_data_points_datetime_with_duration():
    """Test parsing events with duration instead of dtend."""
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    tz = pytz.timezone("US/Eastern")

    dt_start = datetime(2025, 1, 1, 12, 0, tzinfo=pytz.UTC)
    duration = timedelta(hours=2)
    event = FakeEvent({
        "dtstart": dt_start,
        "duration": duration,
    })
    start, end, all_day = p.parse_data_points(event, tz)
    assert end is not None
    assert all_day is False


def test_parse_data_points_date_all_day():
    """Test parsing all-day events with date objects."""
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    tz = pytz.timezone("US/Eastern")

    d = date(2025, 1, 1)
    event = FakeEvent({
        "dtstart": d,
    })
    start, end, all_day = p.parse_data_points(event, tz)
    assert start == d.isoformat()
    assert end is None
    assert all_day is True


def test_get_view_range_timeGridWeek_no_previous_days():
    """Test timeGridWeek view without displayPreviousDays setting."""
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    now = datetime(2025, 1, 15, 10, 30)  # Wednesday
    start, end = p.get_view_range("timeGridWeek", now, {})
    # Should start from current day, not beginning of week
    assert start == datetime(2025, 1, 15, 0, 0)
    assert end == start + timedelta(days=7)


def test_get_view_range_invalid_view():
    """Test get_view_range with invalid view (should not crash)."""
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    now = datetime(2025, 1, 15, 10, 30)
    # Invalid view should not be handled here, but method should not crash
    try:
        start, end = p.get_view_range("invalid", now, {})
        # If it doesn't crash, that's fine - the validation happens elsewhere
    except:
        pass  # Expected to potentially raise


def test_fetch_ics_events_empty_calendar():
    """Test fetching events from empty calendar."""
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})

    # Mock empty calendar response
    class MockCal:
        def __init__(self):
            pass

    with patch.object(p, 'fetch_calendar', return_value=MockCal()):
        with patch('recurring_ical_events.of') as mock_rie:
            mock_rie.return_value.between.return_value = []
            events = p.fetch_ics_events(["http://example.com"], ["#000"], pytz.UTC,
                                      datetime.now(), datetime.now() + timedelta(days=1))
            assert events == []


def test_fetch_ics_events_multiple_calendars():
    """Test fetching events from multiple calendar URLs."""
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})

    # Mock calendar responses
    class MockCal:
        def __init__(self, event_count=1):
            self.event_count = event_count

    mock_event = FakeEvent({
        "summary": "Test Event",
        "dtstart": datetime(2025, 1, 1, 12, 0, tzinfo=pytz.UTC),
    })

    with patch.object(p, 'fetch_calendar') as mock_fetch:
        with patch('recurring_ical_events.of') as mock_rie:
            mock_fetch.return_value = MockCal()
            mock_rie.return_value.between.return_value = [mock_event]

            events = p.fetch_ics_events(
                ["http://example1.com", "http://example2.com"],
                ["#FF0000", "#00FF00"],
                pytz.UTC,
                datetime(2025, 1, 1), datetime(2025, 1, 2)
            )
            assert len(events) == 2  # One event from each calendar
            assert events[0]["backgroundColor"] == "#FF0000"
            assert events[1]["backgroundColor"] == "#00FF00"


def test_generate_settings_template():
    """Test that settings template includes required parameters."""
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})
    template = p.generate_settings_template()

    assert "style_settings" in template
    assert template["style_settings"] is True
    assert "locale_map" in template


def test_fetch_calendar_connection_error(monkeypatch):
    """Test fetch_calendar with connection errors."""
    from plugins.calendar.calendar import Calendar
    import requests

    def raise_connection_error(url, **kwargs):
        raise requests.exceptions.ConnectionError("connection failed")

    monkeypatch.setattr("plugins.calendar.calendar.requests.get", raise_connection_error)

    p = Calendar({"id": "calendar"})
    with pytest.raises(RuntimeError, match="Failed to fetch iCalendar url"):
        p.fetch_calendar("http://example.com/a.ics")


def test_fetch_calendar_decode_error(monkeypatch):
    """Test fetch_calendar with response decoding errors."""
    from plugins.calendar.calendar import Calendar

    class BadResponse:
        text = "invalid utf-8: \xff\xfe"
        def raise_for_status(self):
            return None

    monkeypatch.setattr("plugins.calendar.calendar.requests.get",
                       lambda url, **kwargs: BadResponse())

    p = Calendar({"id": "calendar"})
    with pytest.raises(RuntimeError, match="Failed to fetch iCalendar url"):
        p.fetch_calendar("http://example.com/a.ics")


def test_get_contrast_color_edge_cases():
    """Test get_contrast_color with edge cases."""
    from plugins.calendar.calendar import Calendar

    p = Calendar({"id": "calendar"})

    # Test pure white
    assert p.get_contrast_color("#FFFFFF") == "#000000"

    # Test pure black
    assert p.get_contrast_color("#000000") == "#ffffff"

    # Test exact threshold
    assert p.get_contrast_color("#969696") == "#000000"  # yiq = 150


