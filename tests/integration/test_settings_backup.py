import io
import json
from typing import Any

import pytest
from flask.testing import FlaskClient


def test_export_excludes_api_keys_by_default(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug 1: Export should NOT include API keys unless explicitly requested."""
    device_config_dev.set_env_key("OPEN_AI_SECRET", "sk-test")
    resp = client.get("/settings/export")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    payload = data["data"]
    assert "env_keys" not in payload or not payload.get("env_keys")


def test_export_includes_api_keys_when_opted_in(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A PIN is set (the login guard itself is covered by the auth tests).
    monkeypatch.setitem(client.application.config, "AUTH_ENABLED", True)
    device_config_dev.set_env_key("OPEN_AI_SECRET", "sk-test")
    device_config_dev.set_env_key("OPEN_WEATHER_MAP_SECRET", "owm")

    # Act
    resp = client.post("/settings/export", json={"include_keys": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    payload = data["data"]
    assert isinstance(payload.get("config"), dict)
    env_keys = payload.get("env_keys")
    assert env_keys and env_keys.get("OPEN_AI_SECRET") == "sk-test"
    assert env_keys.get("OPEN_WEATHER_MAP_SECRET") == "owm"


def test_export_refuses_api_keys_without_a_pin(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """With no PIN every page is open to the network, so keys stay home."""
    device_config_dev.set_env_key("OPEN_AI_SECRET", "sk-do-not-leak")

    resp = client.post("/settings/export", json={"include_keys": True})

    assert resp.status_code == 403
    body = resp.get_json()
    assert body["success"] is False
    assert "PIN" in body["error"]
    assert "sk-do-not-leak" not in resp.get_data(as_text=True)


def test_a_keyed_backup_round_trips_every_plugin_key(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every key a plugin reads goes out in the backup and comes back in."""
    monkeypatch.setitem(client.application.config, "AUTH_ENABLED", True)
    device_config_dev.set_env_key("IMMICH_KEY", "immich-1")

    exported = client.post("/settings/export", json={"include_keys": True})
    env_keys = exported.get_json()["data"]["env_keys"]
    assert env_keys == {"IMMICH_KEY": "immich-1"}

    device_config_dev.unset_env_key("IMMICH_KEY")
    resp = client.post("/settings/import", json={"env_keys": env_keys})
    assert resp.status_code == 200
    assert device_config_dev.load_env_key("IMMICH_KEY") == "immich-1"


@pytest.mark.parametrize("pin_enabled", [True, False])
def test_the_include_keys_switch_needs_a_pin(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, pin_enabled: bool
) -> None:
    monkeypatch.setitem(client.application.config, "AUTH_ENABLED", pin_enabled)
    html = client.get("/settings").get_data(as_text=True)
    start = html.index('id="includeKeys"')
    switch = html[start : html.index(">", start)]
    assert ("disabled" in switch) is not pin_enabled
    assert ("Needs a PIN" in html) is not pin_enabled


def test_export_excludes_api_keys_when_opted_out(client: FlaskClient) -> None:
    resp = client.get("/settings/export?include_keys=0")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    payload = data["data"]
    assert "env_keys" not in payload or not payload["env_keys"]


def test_export_get_ignores_include_keys_query(
    client: FlaskClient, device_config_dev: Any
) -> None:
    device_config_dev.set_env_key("OPEN_AI_SECRET", "sk-test")
    resp = client.get("/settings/export?include_keys=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    payload = data["data"]
    assert "env_keys" not in payload or not payload["env_keys"]


def test_import_round_trip_updates_config_and_keys(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_import_ignores_unknown_config_and_env_keys(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


SECRET_PIN = "pin-do-not-leak-4821"
SECRET_WEBHOOK = "https://hooks.example.com/services/T000/B000/token-do-not-leak"


def _set_secrets(device_config: Any, pin: str, webhook: str) -> None:
    device_config.update_value("auth", {"pin": pin}, write=True)
    device_config.update_value("webhook_urls", [webhook], write=True)


def test_export_without_keys_leaves_out_the_pin_and_webhooks(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _set_secrets(device_config_dev, SECRET_PIN, SECRET_WEBHOOK)

    resp = client.get("/settings/export")

    assert resp.status_code == 200
    config = resp.get_json()["data"]["config"]
    assert "auth" not in config
    assert "webhook_urls" not in config
    assert config["name"] == device_config_dev.get_config("name")
    body = resp.get_data(as_text=True)
    assert SECRET_PIN not in body
    assert "token-do-not-leak" not in body
    # Exporting must not drop them from the device itself.
    assert device_config_dev.get_config("auth") == {"pin": SECRET_PIN}
    assert device_config_dev.get_config("webhook_urls") == [SECRET_WEBHOOK]


def test_export_with_keys_includes_the_pin_and_webhooks(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(client.application.config, "AUTH_ENABLED", True)
    _set_secrets(device_config_dev, SECRET_PIN, SECRET_WEBHOOK)

    resp = client.post("/settings/export", json={"include_keys": True})

    assert resp.status_code == 200
    config = resp.get_json()["data"]["config"]
    assert config["auth"] == {"pin": SECRET_PIN}
    assert config["webhook_urls"] == [SECRET_WEBHOOK]


def test_restoring_a_backup_without_keys_keeps_the_pin_and_webhooks(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _set_secrets(device_config_dev, SECRET_PIN, SECRET_WEBHOOK)
    backup = client.get("/settings/export").get_json()["data"]
    backup["config"]["name"] = "Restored"

    resp = client.post("/settings/import", json=backup)

    assert resp.status_code == 200
    assert "PIN" not in resp.get_json()["message"]
    assert device_config_dev.get_config("name") == "Restored"
    assert device_config_dev.get_config("auth") == {"pin": SECRET_PIN}
    assert device_config_dev.get_config("webhook_urls") == [SECRET_WEBHOOK]


def test_restoring_a_keyed_backup_puts_back_the_pin_and_webhooks(
    client: FlaskClient, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(client.application.config, "AUTH_ENABLED", True)
    _set_secrets(device_config_dev, SECRET_PIN, SECRET_WEBHOOK)
    backup = client.post("/settings/export", json={"include_keys": True}).get_json()[
        "data"
    ]
    _set_secrets(device_config_dev, "another-pin", "https://example.com/other")

    resp = client.post("/settings/import", json=backup)

    assert resp.status_code == 200
    assert "Restart InkyPi to use the PIN" in resp.get_json()["message"]
    assert device_config_dev.get_config("auth") == {"pin": SECRET_PIN}
    assert device_config_dev.get_config("webhook_urls") == [SECRET_WEBHOOK]


def test_restoring_the_same_pin_does_not_ask_for_a_restart(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _set_secrets(device_config_dev, SECRET_PIN, SECRET_WEBHOOK)
    resp = client.post(
        "/settings/import",
        json={"config": {"auth": {"pin": SECRET_PIN}, "webhook_urls": []}},
    )
    assert resp.status_code == 200
    assert "PIN" not in resp.get_json()["message"]
    # A keyed backup with an empty list means "no webhooks".
    assert device_config_dev.get_config("webhook_urls") == []


@pytest.mark.parametrize(
    "bad",
    [
        {"auth": "1234"},
        {"auth": {"pin": 1234}},
        {"webhook_urls": "https://example.com/hook"},
        {"webhook_urls": ["ftp://example.com/hook"]},
        {"webhook_urls": [None]},
    ],
)
def test_a_malformed_pin_or_webhook_entry_fails_the_whole_import(
    client: FlaskClient, device_config_dev: Any, bad: dict[str, Any]
) -> None:
    _set_secrets(device_config_dev, SECRET_PIN, SECRET_WEBHOOK)
    before = device_config_dev.get_config("name")

    resp = client.post("/settings/import", json={"config": {"name": "New", **bad}})

    assert resp.status_code == 400
    assert device_config_dev.get_config("name") == before
    assert device_config_dev.get_config("auth") == {"pin": SECRET_PIN}
    assert device_config_dev.get_config("webhook_urls") == [SECRET_WEBHOOK]
