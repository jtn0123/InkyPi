# pyright: reportMissingImports=false


def test_get_settings_page(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    # Basic UI markers
    assert b"Settings" in resp.data or b"Time Zone" in resp.data


def test_save_settings_validation_errors(client):
    # Missing required fields
    resp = client.post("/save_settings", data={})
    assert resp.status_code == 400


def test_save_settings_success_triggers_interval_update(client, flask_app, monkeypatch):
    called = {"signaled": False}

    def fake_signal():
        called["signaled"] = True

    refresh_task = flask_app.config["REFRESH_TASK"]
    monkeypatch.setattr(refresh_task, "signal_config_change", fake_signal)

    # Post valid form
    data = {
        "deviceName": "Test Device",
        "orientation": "horizontal",
        "invertImage": "",
        "logSystemStats": "",
        "timezoneName": "UTC",
        "timeFormat": "24h",
        "interval": "1",
        "unit": "hour",
        "saturation": "1.0",
        "brightness": "1.0",
        "sharpness": "1.0",
        "contrast": "1.0",
    }
    resp = client.post("/save_settings", data=data)
    assert resp.status_code == 200
    # Changing from default 300s to 3600s should signal
    assert called["signaled"] is True
