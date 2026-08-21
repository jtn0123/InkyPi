# pyright: reportMissingImports=false
"""JTN-357: Calendar plugin URL validation.

The ICS URL field must reject non-URL values at save time (backend
``validate_settings``) and the rendered settings template must use a
``type="url"`` input so the browser enforces basic URL constraints client-side.
"""

from typing import Any

from flask.testing import FlaskClient


def _plugin() -> Any:
    from plugins.calendar.calendar import Calendar

    return Calendar({"id": "calendar"})


def test_validate_settings_accepts_http_ics_url() -> None:
    error = _plugin().validate_settings(
        {
            "calendarURLs[]": ["http://example.com/cal.ics"],
            "calendarColors[]": ["#007BFF"],
        }
    )
    assert error is None


def test_validate_settings_accepts_https_ics_url() -> None:
    error = _plugin().validate_settings(
        {
            "calendarURLs[]": [
                "https://calendar.google.com/calendar/ical/abc/public/basic.ics"
            ],
            "calendarColors[]": ["#007BFF"],
        }
    )
    assert error is None


def test_validate_settings_accepts_webcal_url() -> None:
    # The runtime rewrites webcal:// to https:// before fetching, so webcal
    # should also be considered a valid persisted value.
    error = _plugin().validate_settings(
        {
            "calendarURLs[]": ["webcal://example.com/cal.ics"],
            "calendarColors[]": ["#007BFF"],
        }
    )
    assert error is None


def test_validate_settings_accepts_url_without_ics_extension() -> None:
    # Some providers serve calendar files without an .ics extension.
    error = _plugin().validate_settings(
        {
            "calendarURLs[]": ["https://example.com/calendar"],
            "calendarColors[]": ["#007BFF"],
        }
    )
    assert error is None


def test_validate_settings_rejects_non_url_string() -> None:
    error = _plugin().validate_settings(
        {
            "calendarURLs[]": ["not-a-url"],
            "calendarColors[]": ["#007BFF"],
        }
    )
    assert error is not None
    assert "not valid" in error.lower()
    assert "not-a-url" in error


def test_validate_settings_rejects_javascript_scheme() -> None:
    error = _plugin().validate_settings(
        {
            "calendarURLs[]": ["javascript:alert(1)"],
            "calendarColors[]": ["#007BFF"],
        }
    )
    assert error is not None
    assert "not valid" in error.lower()


def test_validate_settings_rejects_file_scheme() -> None:
    error = _plugin().validate_settings(
        {
            "calendarURLs[]": ["file:///etc/passwd"],
            "calendarColors[]": ["#007BFF"],
        }
    )
    assert error is not None
    assert "not valid" in error.lower()


def test_validate_settings_rejects_empty_url() -> None:
    error = _plugin().validate_settings(
        {
            "calendarURLs[]": [""],
            "calendarColors[]": ["#007BFF"],
        }
    )
    assert error is not None


def test_validate_settings_rejects_whitespace_url() -> None:
    error = _plugin().validate_settings(
        {
            "calendarURLs[]": ["   "],
            "calendarColors[]": ["#007BFF"],
        }
    )
    assert error is not None


def test_validate_settings_rejects_missing_urls_key() -> None:
    error = _plugin().validate_settings({"calendarColors[]": ["#007BFF"]})
    assert error is not None
    assert "required" in error.lower()


def test_validate_settings_rejects_when_any_row_invalid() -> None:
    error = _plugin().validate_settings(
        {
            "calendarURLs[]": [
                "https://example.com/cal.ics",
                "bogus",
            ],
            "calendarColors[]": ["#007BFF", "#FF0000"],
        }
    )
    assert error is not None
    assert "bogus" in error


def test_calendar_url_input_is_type_url_and_required(client: FlaskClient) -> None:
    """The calendar settings form renders a type=url input with required (JTN-357)."""
    resp = client.get("/plugin/calendar")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="calendarURLs[]"' in html
    assert 'type="url"' in html
    # The input must be required so the browser blocks empty submissions.
    # We check for the attribute on the calendarURLs[] input specifically by
    # looking for a window containing both the name and the required attr.
    import re

    input_tag = re.search(r"<input[^>]*name=\"calendarURLs\[\]\"[^>]*>", html)
    assert input_tag is not None, "calendarURLs[] input not found in rendered page"
    tag = input_tag.group(0)
    assert 'type="url"' in tag
    assert "required" in tag
