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
