# pyright: reportMissingImports=false
import json
import os


def test_get_settings_page(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    # Basic UI markers
    assert b"Settings" in resp.data or b"Time Zone" in resp.data
    assert b'data-page-shell="management"' in resp.data
    assert b'data-settings-tab="device"' in resp.data


def test_save_settings_validation_errors(client):
    # Missing required fields
    resp = client.post("/save_settings", data={})
    assert resp.status_code == 422


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


def test_start_update_endpoint(client, monkeypatch):
    # Ensure start_update returns JSON and doesn't crash in dev
    resp = client.post("/settings/update")
    assert resp.status_code in (200, 409)
    data = resp.get_json()
    assert isinstance(data, dict)
    assert "running" in data


def test_update_status_endpoint(client):
    resp = client.get("/settings/update_status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "running" in data


def test_settings_page_timezone_defaults_to_utc_when_missing(
    tmp_path, monkeypatch, flask_app
):
    """Settings page renders value='UTC' when config has no timezone key (JTN-216)."""
    import config as config_mod

    # Build a config file without a timezone key
    cfg = {
        "name": "InkyPi Test",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
        "output_dir": str(tmp_path / "mock_output"),
        "time_format": "24h",
        "plugin_cycle_interval_seconds": 300,
        "image_settings": {
            "saturation": 1.0,
            "brightness": 1.0,
            "sharpness": 1.0,
            "contrast": 1.0,
        },
        "playlist_config": {"playlists": [], "active_playlist": ""},
        "refresh_info": {
            "refresh_time": None,
            "image_hash": None,
            "refresh_type": "Manual Update",
            "plugin_id": "",
        },
    }
    config_file = tmp_path / "device_no_tz.json"
    config_file.write_text(json.dumps(cfg))
    (tmp_path / ".env").write_text("", encoding="utf-8")
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(config_mod.Config, "config_file", str(config_file))
    monkeypatch.setattr(
        config_mod.Config, "current_image_file", str(tmp_path / "current_image.png")
    )
    monkeypatch.setattr(
        config_mod.Config, "processed_image_file", str(tmp_path / "processed_image.png")
    )
    monkeypatch.setattr(
        config_mod.Config, "plugin_image_dir", str(tmp_path / "plugins")
    )
    monkeypatch.setattr(
        config_mod.Config, "history_image_dir", str(tmp_path / "history")
    )
    os.makedirs(str(tmp_path / "plugins"), exist_ok=True)
    os.makedirs(str(tmp_path / "history"), exist_ok=True)

    device_config = config_mod.Config()
    flask_app.config["DEVICE_CONFIG"] = device_config

    client = flask_app.test_client()
    resp = client.get("/settings")
    assert resp.status_code == 200
    # The timezone input should default to UTC when key is absent
    assert b'value="UTC"' in resp.data


def test_settings_page_timezone_renders_configured_value(client):
    """Settings page renders the configured timezone value (JTN-216)."""
    # The default fixture sets timezone="UTC"; verify it appears in the rendered HTML
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert b'value="UTC"' in resp.data
