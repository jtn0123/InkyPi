import io
import json


def test_export_excludes_api_keys_by_default(client, device_config_dev, monkeypatch):
    """Bug 1: Export should NOT include API keys unless explicitly requested."""
    device_config_dev.set_env_key("OPEN_AI_SECRET", "sk-test")
    resp = client.get("/settings/export")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    payload = data["data"]
    assert "env_keys" not in payload or not payload.get("env_keys")


def test_export_includes_api_keys_when_opted_in(client, device_config_dev, monkeypatch):
    # Arrange env keys
    device_config_dev.set_env_key("OPEN_AI_SECRET", "sk-test")
    device_config_dev.set_env_key("OPEN_WEATHER_MAP_SECRET", "owm")

    # Act
    resp = client.get("/settings/export?include_keys=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    payload = data["data"]
    assert isinstance(payload.get("config"), dict)
    env_keys = payload.get("env_keys")
    assert env_keys and env_keys.get("OPEN_AI_SECRET") == "sk-test"
    assert env_keys.get("OPEN_WEATHER_MAP_SECRET") == "owm"


def test_export_excludes_api_keys_when_opted_out(client):
    resp = client.get("/settings/export?include_keys=0")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    payload = data["data"]
    assert "env_keys" not in payload or not payload["env_keys"]


def test_import_round_trip_updates_config_and_keys(client, device_config_dev):
    # Build an export-like payload
    cfg = device_config_dev.get_config().copy()
    cfg["name"] = "RoundTrip"
    payload = {
        "config": cfg,
        "env_keys": {"NASA_SECRET": "nasa", "UNSPLASH_ACCESS_KEY": "u"},
    }

    resp = client.post(
        "/settings/import",
        data={"file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "backup.json")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    # Verify config changed
    assert device_config_dev.get_config("name") == "RoundTrip"
    # Verify keys set
    assert device_config_dev.load_env_key("NASA_SECRET") == "nasa"
    assert device_config_dev.load_env_key("UNSPLASH_ACCESS_KEY") == "u"


def test_import_ignores_unknown_config_and_env_keys(client, device_config_dev):
    """Bug 6: import_settings should filter unknown config and env keys."""
    payload = {
        "config": {
            "name": "Allowed",
            "time_format": "24h",
            "plugin_cycle_interval_seconds": 1800,
            "secret_backdoor": "should_be_ignored",
            "__class__": "should_be_ignored",
        },
        "env_keys": {
            "OPEN_AI_SECRET": "sk-ok",
            "EVIL_KEY": "should_be_ignored",
        },
    }

    resp = client.post(
        "/settings/import",
        data={"file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "backup.json")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert device_config_dev.get_config("name") == "Allowed"
    # Legitimate config keys should be imported
    assert device_config_dev.get_config("time_format") == "24h"
    assert device_config_dev.get_config("plugin_cycle_interval_seconds") == 1800
    # Unknown config keys should not be set
    assert device_config_dev.get_config("secret_backdoor") is None
    assert device_config_dev.get_config("__class__") is None
    # Unknown env keys should not be set
    assert device_config_dev.load_env_key("EVIL_KEY") is None
    # Allowed env key should be set
    assert device_config_dev.load_env_key("OPEN_AI_SECRET") == "sk-ok"
