# pyright: reportMissingImports=false


def test_save_settings_missing_fields(client):
    # missing unit, interval, timezone, timeFormat
    resp = client.post("/save_settings", data={})
    assert resp.status_code == 400


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
    assert resp.status_code == 400


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
    assert resp.status_code == 400

    # too large interval
    data["interval"] = "200000"  # minutes -> > 24h
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 400


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
    assert resp.status_code == 400

    # Bad time format
    data2 = dict(base)
    data2["timezoneName"] = "UTC"
    data2["timeFormat"] = "13h"
    resp = client.post("/save_settings", data=data2)
    assert resp.status_code == 400


def test_save_settings_success_triggers_config_change_signal(client, monkeypatch):
    # Spy refresh_task.signal_config_change
    from blueprints import settings as settings_mod

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
