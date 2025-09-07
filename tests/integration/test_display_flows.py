# pyright: reportMissingImports=false
from datetime import datetime, timezone

import pytest
from PIL import Image

from model import RefreshInfo


def _fixed_now(_device_config):
    return datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)


def _prepare_playlist(device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    # Two instances so we can see rotation and ensure one is "Displayed Now"
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "Weather B",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time="2025-01-01T07:55:00+00:00",
        image_hash=0,
        playlist="Default",
        plugin_instance="Clock A",
    )
    device_config_dev.write_config()


def test_display_plugin_instance_endpoint_success(client, device_config_dev, monkeypatch):
    _prepare_playlist(device_config_dev)

    resp = client.post(
        "/display_plugin_instance",
        json={
            "playlist_name": "Default",
            "plugin_id": "clock",
            "plugin_instance": "Clock A",
        },
    )
    assert resp.status_code == 200
    assert resp.json.get("success") is True


def test_display_next_in_playlist_success(client, device_config_dev, monkeypatch):
    _prepare_playlist(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    resp = client.post("/display_next_in_playlist", json={"playlist_name": "Default"})
    # Even if background task is not running, endpoint should respond cleanly
    assert resp.status_code == 200
    assert resp.json.get("success") is True


def test_main_display_next_happy_path(client, device_config_dev, monkeypatch, flask_app):
    # Force direct path by marking refresh_task.running = False
    rt = flask_app.config["REFRESH_TASK"]
    rt.running = False

    _prepare_playlist(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    # Stub plugin generation and display to avoid heavy work/network
    from plugins import plugin_registry

    class _StubPlugin:
        def generate_image(self, settings, device_config):
            return Image.new("RGB", (800, 480), "white")

    monkeypatch.setattr(
        plugin_registry, "get_plugin_instance", lambda cfg: _StubPlugin(), raising=True
    )
    called = {"displayed": False}

    def _display_image(image, image_settings=None, history_meta=None):
        called["displayed"] = True

    flask_app.config["DISPLAY_MANAGER"].display_image = _display_image

    resp = client.post("/display-next")
    assert resp.status_code == 200
    assert resp.json.get("success") is True
    assert called["displayed"] is True


