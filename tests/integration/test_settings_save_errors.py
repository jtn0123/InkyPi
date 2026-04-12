# pyright: reportMissingImports=false


def test_save_settings_missing_fields(client):
    # missing unit, interval, timezone, timeFormat
    resp = client.post("/save_settings", data={})
    assert resp.status_code == 422


def test_save_settings_invalid_unit(client):
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


def test_save_settings_invalid_interval_and_bounds(client):
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


def test_save_settings_missing_timezone_and_bad_time_format(client):
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


def test_save_settings_interval_missing_returns_required(client):
    """Missing interval field returns 'is required' message."""
    data = dict(_VALID_BASE)
    # interval key is absent
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "Refresh interval is required" in resp.get_json()["error"]


def test_save_settings_interval_empty_returns_required(client):
    """Empty string interval returns 'is required' message."""
    data = dict(_VALID_BASE, interval="")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "Refresh interval is required" in resp.get_json()["error"]


def test_save_settings_interval_non_numeric_returns_must_be_number(client):
    """Non-numeric interval returns 'must be a number' message."""
    data = dict(_VALID_BASE, interval="abc")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "Refresh interval must be a number" in resp.get_json()["error"]


def test_save_settings_interval_float_returns_must_be_number(client):
    """Decimal interval returns 'must be a number' (int expected)."""
    data = dict(_VALID_BASE, interval="2.5")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "Refresh interval must be a number" in resp.get_json()["error"]


def test_save_settings_interval_negative_returns_at_least_1(client):
    """Negative interval returns 'must be at least 1', not 'is required'."""
    data = dict(_VALID_BASE, interval="-5")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    body = resp.get_json()
    assert "must be at least 1" in body["error"]
    assert "required" not in body["error"].lower()


def test_save_settings_interval_zero_returns_at_least_1(client):
    """Zero interval returns 'must be at least 1'."""
    data = dict(_VALID_BASE, interval="0")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "must be at least 1" in resp.get_json()["error"]


def test_save_settings_interval_exceeds_24h(client):
    """Interval exceeding 24 hours returns appropriate error."""
    data = dict(_VALID_BASE, interval="1500", unit="minute")
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 422
    assert "24 hours" in resp.get_json()["error"]


def test_save_settings_success_triggers_config_change_signal(client, monkeypatch):
    # Spy refresh_task.signal_config_change

    called = {"signal": 0}

    def fake_signal():
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
