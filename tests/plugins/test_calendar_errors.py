# pyright: reportMissingImports=false
"""Error scenario tests for the Calendar plugin."""

from typing import Any

import pytest
import requests


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve example.* feed hosts to a public IP so the SSRF guard passes offline.

    Other names (e.g. the local renderer's ``localhost``) keep the real resolver.
    """
    import socket

    real_getaddrinfo = socket.getaddrinfo

    def _resolve(host: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(host, str) and ".example." in f".{host}.":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", _resolve)


def _make_calendar_plugin() -> Any:
    from plugins.calendar.calendar import Calendar

    return Calendar({"id": "calendar"})


def test_calendar_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """ICS URL unreachable raises RuntimeError."""
    p = _make_calendar_plugin()

    def raise_conn_error(url: Any, **kwargs: Any) -> None:
        raise requests.exceptions.ConnectionError("Network unreachable")

    mock_session = type("S", (), {"get": staticmethod(raise_conn_error)})()
    monkeypatch.setattr(
        "plugins.calendar.calendar.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="Failed to fetch iCalendar url"):
        p.fetch_calendar("http://unreachable.example.com/cal.ics")


def test_calendar_malformed_ics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid HTTP response but invalid ICS content."""
    p = _make_calendar_plugin()

    class FakeResp:
        body = b"THIS IS NOT ICS CONTENT AT ALL"
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def iter_content(self, chunk_size: int = 1) -> Any:
            return iter([self.body])

        def close(self) -> None:
            return None

    mock_session = type(
        "S", (), {"get": staticmethod(lambda url, **kwargs: FakeResp())}
    )()
    monkeypatch.setattr(
        "plugins.calendar.calendar.get_http_session", lambda: mock_session
    )

    import plugins.calendar.calendar as cal_mod

    def bad_parse(_text: Any) -> None:
        raise ValueError("not valid ical")

    monkeypatch.setattr(
        cal_mod.icalendar.Calendar,
        "from_ical",
        staticmethod(bad_parse),
        raising=True,
    )

    with pytest.raises(RuntimeError, match="Failed to fetch iCalendar url"):
        p.fetch_calendar("http://example.com/bad.ics")


def test_calendar_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """ICS URL request times out."""
    p = _make_calendar_plugin()

    def raise_timeout(url: Any, **kwargs: Any) -> None:
        raise requests.exceptions.Timeout("timed out")

    mock_session = type("S", (), {"get": staticmethod(raise_timeout)})()
    monkeypatch.setattr(
        "plugins.calendar.calendar.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="Failed to fetch iCalendar url"):
        p.fetch_calendar("http://slow.example.com/cal.ics")


def test_calendar_http_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """ICS URL returns 403 Forbidden."""
    p = _make_calendar_plugin()

    class ForbiddenResp:
        status_code = 403

        def raise_for_status(self) -> None:
            raise requests.exceptions.HTTPError("403 Forbidden")

        def close(self) -> None:
            return None

    mock_session = type(
        "S", (), {"get": staticmethod(lambda url, **kwargs: ForbiddenResp())}
    )()
    monkeypatch.setattr(
        "plugins.calendar.calendar.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="Failed to fetch iCalendar url"):
        p.fetch_calendar("http://private.example.com/cal.ics")
