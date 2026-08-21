import pytest
from flask.testing import FlaskClient

# pyright: reportMissingImports=false


def test_save_settings_missing_fields(client: FlaskClient) -> None:
    # missing unit, interval, timezone, timeFormat
    resp = client.post("/save_settings", data={})
    assert resp.status_code == 422


def test_save_settings_invalid_unit(client: FlaskClient) -> None:
    data = {
        "deviceName": "D",
        "orientation": "horizontal",
        "invertImage": "",
        "logSystemStats": "",
        "timezoneName": "UTC",
        "timeFormat": "24h",
        "interval": "1",
        "unit": "dayz",
        "saturation": "1.0",
        "brightness": "1.0",
        "sharpness": "1.0",
        "contrast": "1.0",
    }
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422


def test_save_settings_invalid_interval_and_bounds(client: FlaskClient) -> None:
    # non-numeric interval
    data = {
        "deviceName": "D",
        "orientation": "horizontal",
        "invertImage": "",
        "logSystemStats": "",
        "timezoneName": "UTC",
        "timeFormat": "24h",
        "interval": "x",
        "unit": "minute",
        "saturation": "1.0",
        "brightness": "1.0",
        "sharpness": "1.0",
        "contrast": "1.0",
    }
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422

    # too large interval
    data["interval"] = "200000"  # minutes -> > 24h
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422


def test_save_settings_missing_timezone_and_bad_time_format(
    client: FlaskClient,
) -> None:
    base = {
        "deviceName": "D",
        "orientation": "horizontal",
        "invertImage": "",
        "logSystemStats": "",
        "interval": "10",
        "unit": "minute",
        "saturation": "1.0",
        "brightness": "1.0",
        "sharpness": "1.0",
        "contrast": "1.0",
    }
    # Missing timezone
    resp = client.post("/save_settings", data=base)
    assert resp.status_code == 422

    # Bad time format
    data2 = dict(base)
    data2["timezoneName"] = "UTC"
    data2["timeFormat"] = "13h"
    resp = client.post("/save_settings", data=data2)
    assert resp.status_code == 422


_VALID_BASE = {
    "deviceName": "D",
    "orientation": "horizontal",
    "invertImage": "",
    "logSystemStats": "",
    "timezoneName": "UTC",
    "timeFormat": "24h",
    "unit": "minute",
    "saturation": "1.0",
    "brightness": "1.0",
    "sharpness": "1.0",
    "contrast": "1.0",
}


def test_save_settings_interval_missing_returns_required(client: FlaskClient) -> None:
    """Missing interval field returns 'is required' message."""
    data = dict(_VALID_BASE)
    # interval key is absent
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "Refresh interval is required" in resp.get_json()["error"]


def test_save_settings_interval_empty_returns_required(client: FlaskClient) -> None:
    """Empty string interval returns 'is required' message."""
    data = dict(_VALID_BASE, interval="")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "Refresh interval is required" in resp.get_json()["error"]


def test_save_settings_interval_non_numeric_returns_must_be_number(
    client: FlaskClient,
) -> None:
    """Non-numeric interval returns 'must be a number' message."""
    data = dict(_VALID_BASE, interval="abc")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "Refresh interval must be a number" in resp.get_json()["error"]


def test_save_settings_interval_float_returns_must_be_number(
    client: FlaskClient,
) -> None:
    """Decimal interval returns 'must be a number' (int expected)."""
    data = dict(_VALID_BASE, interval="2.5")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "Refresh interval must be a number" in resp.get_json()["error"]


def test_save_settings_interval_negative_returns_at_least_1(
    client: FlaskClient,
) -> None:
    """Negative interval returns 'must be at least 1', not 'is required'."""
    data = dict(_VALID_BASE, interval="-5")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    body = resp.get_json()
    assert "must be at least 1" in body["error"]
    assert "required" not in body["error"].lower()


def test_save_settings_interval_zero_returns_at_least_1(client: FlaskClient) -> None:
    """Zero interval returns 'must be at least 1'."""
    data = dict(_VALID_BASE, interval="0")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "must be at least 1" in resp.get_json()["error"]


def test_save_settings_interval_exceeds_24h(client: FlaskClient) -> None:
    """Interval exceeding 24 hours returns appropriate error."""
    data = dict(_VALID_BASE, interval="1500", unit="minute")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "24 hours" in resp.get_json()["error"]


def test_save_settings_success_triggers_config_change_signal(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spy refresh_task.signal_config_change

    called = {"signal": 0}

    def fake_signal() -> None:
        called["signal"] += 1

    app = client.application
    rt = app.config["REFRESH_TASK"]
    monkeypatch.setattr(rt, "signal_config_change", fake_signal, raising=True)

    data = {
        "deviceName": "D",
        "orientation": "horizontal",
        "invertImage": "",
        "logSystemStats": "",
        "timezoneName": "UTC",
        "timeFormat": "24h",
        "interval": "15",
        "unit": "minute",
        "saturation": "1.0",
        "brightness": "1.0",
        "sharpness": "1.0",
        "contrast": "1.0",
    }
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 200
    # Signal should be invoked at least once
    assert called["signal"] >= 1


def test_save_settings_rejects_invalid_timezone(client: FlaskClient) -> None:
    """JTN-650: Unknown timezone strings must be rejected, not silently persisted."""
    data = dict(_VALID_BASE)
    data["interval"] = "10"
    data["timezoneName"] = "NotATimezone"
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["code"] == "validation_error"
    assert body["details"]["field"] == "timezoneName"
    assert "IANA" in body["error"] or "valid" in body["error"].lower()


def test_save_settings_accepts_valid_iana_timezone(client: FlaskClient) -> None:
    """JTN-650: A known IANA zone (America/New_York) must still save successfully."""
    data = dict(_VALID_BASE)
    data["interval"] = "10"
    data["timezoneName"] = "America/New_York"
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 200
