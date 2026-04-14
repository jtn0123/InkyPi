# pyright: reportMissingImports=false
"""JTN-379: validate_settings + min/max date constraints for the APOD plugin.

Prior behavior silently accepted any ``customDate`` (e.g. ``1900-01-01`` or
``2099-12-31``), surfacing the failure later when the plugin tried to fetch a
non-existent APOD from NASA's API. The archive begins on 1995-06-16 and
obviously cannot return future dates, so we now reject out-of-range values at
save time and constrain the date input client-side via ``min``/``max``.
"""

from datetime import UTC, date, datetime, timedelta


def _today_utc() -> date:
    """Return today's date in UTC.

    The APOD plugin resolves "today" via ``datetime.now(tz=UTC).date()`` so
    tests must reference the same UTC-anchored date. Using the local
    ``date.today()`` causes intermittent failures around UTC midnight when
    the host timezone is not UTC (JTN-663: date-boundary flakes).
    """
    return datetime.now(tz=UTC).date()


def _make_plugin():
    from plugins.apod.apod import Apod

    return Apod({"id": "apod"})


def test_validate_settings_empty_custom_date_returns_none():
    plugin = _make_plugin()
    assert plugin.validate_settings({}) is None
    assert plugin.validate_settings({"customDate": ""}) is None
    assert plugin.validate_settings({"customDate": "   "}) is None


def test_validate_settings_randomize_ignores_custom_date():
    plugin = _make_plugin()
    # Random mode supplies its own date — bad customDate must not block save.
    assert (
        plugin.validate_settings({"randomizeApod": "true", "customDate": "1900-01-01"})
        is None
    )


def test_validate_settings_pre_archive_returns_error():
    plugin = _make_plugin()
    err = plugin.validate_settings({"customDate": "1994-12-31"})
    assert err is not None
    assert "1995-06-16" in err


def test_validate_settings_far_future_returns_error():
    plugin = _make_plugin()
    err = plugin.validate_settings({"customDate": "2099-12-31"})
    assert err is not None
    today = _today_utc().isoformat()
    assert today in err


def test_validate_settings_tomorrow_returns_error():
    plugin = _make_plugin()
    tomorrow = (_today_utc() + timedelta(days=1)).isoformat()
    err = plugin.validate_settings({"customDate": tomorrow})
    assert err is not None
    assert _today_utc().isoformat() in err


def test_validate_settings_archive_start_boundary_returns_none():
    plugin = _make_plugin()
    assert plugin.validate_settings({"customDate": "1995-06-16"}) is None


def test_validate_settings_today_boundary_returns_none():
    plugin = _make_plugin()
    today = _today_utc().isoformat()
    assert plugin.validate_settings({"customDate": today}) is None


def test_validate_settings_invalid_format_returns_error():
    plugin = _make_plugin()
    err = plugin.validate_settings({"customDate": "not-a-date"})
    assert err is not None
    assert "format" in err.lower() or "invalid" in err.lower()


def test_validate_settings_partial_date_returns_error():
    plugin = _make_plugin()
    err = plugin.validate_settings({"customDate": "2024-13-40"})
    assert err is not None


def test_settings_schema_advertises_min_and_max():
    """Ensure the schema sets min=1995-06-16 and max=today on the date field."""
    plugin = _make_plugin()
    s = plugin.build_settings_schema()
    custom_date_field = None
    for section in s["sections"]:
        for item in section["items"]:
            if item.get("kind") == "field" and item.get("name") == "customDate":
                custom_date_field = item
                break
    assert custom_date_field is not None
    assert custom_date_field.get("type") == "date"
    assert custom_date_field.get("min") == "1995-06-16"
    assert custom_date_field.get("max") == _today_utc().isoformat()


def test_settings_template_renders_min_and_max(client):
    """The rendered settings page must include min/max attributes (JTN-379)."""
    resp = client.get("/plugin/apod")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'min="1995-06-16"' in body
    assert f'max="{_today_utc().isoformat()}"' in body


def test_save_plugin_settings_rejects_pre_archive_date(client):
    """JTN-379: POST /save_plugin_settings with pre-1995 date returns 400."""
    data = {
        "plugin_id": "apod",
        "randomizeApod": "false",
        "customDate": "1900-01-01",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 400
    body = resp.get_json() or {}
    assert body.get("success") is False
    msg = body.get("error") or body.get("message") or ""
    assert "1995-06-16" in msg


def test_save_plugin_settings_rejects_future_date(client):
    """JTN-379: POST /save_plugin_settings with a far-future date returns 400."""
    data = {
        "plugin_id": "apod",
        "randomizeApod": "false",
        "customDate": "2099-12-31",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 400
    body = resp.get_json() or {}
    assert body.get("success") is False
    msg = body.get("error") or body.get("message") or ""
    assert _today_utc().isoformat() in msg


def test_save_plugin_settings_accepts_valid_date(client):
    """JTN-379: a date inside the [1995-06-16, today] window saves successfully."""
    data = {
        "plugin_id": "apod",
        "randomizeApod": "false",
        "customDate": "2020-07-20",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 200
    body = resp.get_json() or {}
    assert body.get("success") is True
