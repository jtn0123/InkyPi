# pyright: reportMissingImports=false
"""Error recovery tests for graceful failure handling."""

from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

_VALID_SETTINGS = {
    "deviceName": "Kitchen Frame",
    "unit": "minute",
    "interval": "5",
    "timeFormat": "24h",
    "timezoneName": "UTC",
}


def test_config_write_failure_returns_error(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed config write returns 500 and leaves the settings as they were."""
    import config as config_mod

    device_config = flask_app.config["DEVICE_CONFIG"]
    name_before = device_config.get_config("name")
    assert name_before != _VALID_SETTINGS["deviceName"]

    def bad_write(self: Any) -> None:
        raise OSError("Disk full")

    monkeypatch.setattr(config_mod.Config, "_write_config", bad_write)

    resp = client.post("/save_settings", data=_VALID_SETTINGS)
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["success"] is False
    assert body["code"] == "internal_error"
    assert "Disk full" not in resp.get_data(as_text=True)
    # The rollback in Config.update_atomic undoes the in-memory change, so
    # the page doesn't show settings that were never saved.
    assert device_config.get_config("name") == name_before


def test_plugin_generate_image_timeout(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plugin render raising TimeoutError returns a typed 504 (JTN-K4)."""
    from plugins.plugin_registry import get_plugin_instance

    plugin = get_plugin_instance({"id": "clock", "class": "Clock"})

    def slow_generate(*args: Any, **kwargs: Any) -> None:
        raise TimeoutError("Screenshot timed out")

    monkeypatch.setattr(plugin, "generate_image", slow_generate)

    resp = client.post("/update_now", data={"plugin_id": "clock"})
    assert resp.status_code == 504
    body = resp.get_json()
    assert body["success"] is False
    assert body["code"] == "manual_update_timeout"


def test_missing_plugin_update_now(client: FlaskClient) -> None:
    """update_now for a plugin that isn't installed returns 404."""
    resp = client.post("/update_now", data={"plugin_id": "nonexistent_plugin_xyz"})
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["success"] is False
    assert body["code"] == "plugin_not_found"


def test_invalid_json_body(client: FlaskClient) -> None:
    """A text/plain body has no form fields, so it fails the first required one."""
    resp = client.post(
        "/save_settings",
        data="not-form-data",
        content_type="text/plain",
    )
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["code"] == "validation_error"
    assert body["details"] == {"field": "deviceName"}
