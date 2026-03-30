# pyright: reportMissingImports=false
"""Error scenario tests for the Calendar plugin."""

import pytest
import requests


def _make_calendar_plugin():
    from plugins.calendar.calendar import Calendar

    return Calendar({"id": "calendar"})


def test_calendar_network_error(monkeypatch):
    """ICS URL unreachable raises RuntimeError."""
    p = _make_calendar_plugin()

    def raise_conn_error(url, **kwargs):
        raise requests.exceptions.ConnectionError("Network unreachable")

    mock_session = type("S", (), {"get": staticmethod(raise_conn_error)})()
    monkeypatch.setattr(
        "plugins.calendar.calendar.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="Failed to fetch iCalendar url"):
        p.fetch_calendar("http://unreachable.example.com/cal.ics")


def test_calendar_malformed_ics(monkeypatch):
    """Valid HTTP response but invalid ICS content."""
    p = _make_calendar_plugin()

    class FakeResp:
        text = "THIS IS NOT ICS CONTENT AT ALL"
        status_code = 200

        def raise_for_status(self):
            pass

    mock_session = type(
        "S", (), {"get": staticmethod(lambda url, **kwargs: FakeResp())}
    )()
    monkeypatch.setattr(
        "plugins.calendar.calendar.get_http_session", lambda: mock_session
    )

    import plugins.calendar.calendar as cal_mod

    def bad_parse(_text):
        raise ValueError("not valid ical")

    monkeypatch.setattr(
        cal_mod.icalendar.Calendar,
        "from_ical",
        staticmethod(bad_parse),
        raising=True,
    )

    with pytest.raises(RuntimeError, match="Failed to fetch iCalendar url"):
        p.fetch_calendar("http://example.com/bad.ics")


def test_calendar_timeout(monkeypatch):
    """ICS URL request times out."""
    p = _make_calendar_plugin()

    def raise_timeout(url, **kwargs):
        raise requests.exceptions.Timeout("timed out")

    mock_session = type("S", (), {"get": staticmethod(raise_timeout)})()
    monkeypatch.setattr(
        "plugins.calendar.calendar.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="Failed to fetch iCalendar url"):
        p.fetch_calendar("http://slow.example.com/cal.ics")


def test_calendar_http_403(monkeypatch):
    """ICS URL returns 403 Forbidden."""
    p = _make_calendar_plugin()

    class ForbiddenResp:
        status_code = 403

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("403 Forbidden")

    mock_session = type(
        "S", (), {"get": staticmethod(lambda url, **kwargs: ForbiddenResp())}
    )()
    monkeypatch.setattr(
        "plugins.calendar.calendar.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="Failed to fetch iCalendar url"):
        p.fetch_calendar("http://private.example.com/cal.ics")
