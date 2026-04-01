# pyright: reportMissingImports=false
"""Tests for blueprints/main.py — additional coverage."""
import os
import time
from unittest.mock import MagicMock, patch

from PIL import Image


def _save_png(path, size=(800, 480), color="white"):
    Image.new("RGB", size, color).save(path)


# ---- /preview ----


def test_preview_image_processed_exists(client, device_config_dev):
    _save_png(device_config_dev.processed_image_file)
    resp = client.get("/preview")
    assert resp.status_code == 200


def test_preview_image_fallback_current(client, device_config_dev):
    # No processed image, but current image exists
    _save_png(device_config_dev.current_image_file)
    resp = client.get("/preview")
    assert resp.status_code == 200


def test_preview_image_404(client, device_config_dev):
    # Ensure neither image exists
    for p in (
        device_config_dev.processed_image_file,
        device_config_dev.current_image_file,
    ):
        if os.path.exists(p):
            os.remove(p)
    resp = client.get("/preview")
    assert resp.status_code == 404


# ---- /api/current_image ----


def test_current_image_not_found(client, device_config_dev):
    # Ensure image file doesn't exist
    if os.path.exists(device_config_dev.current_image_file):
        os.remove(device_config_dev.current_image_file)
    resp = client.get("/api/current_image")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "error" in data


def test_current_image_if_modified_since_fresh(client, device_config_dev):
    _save_png(device_config_dev.current_image_file)
    # Set If-Modified-Since far in the future
    resp = client.get(
        "/api/current_image",
        headers={"If-Modified-Since": "Sun, 01 Jan 2090 00:00:00 GMT"},
    )
    assert resp.status_code == 304


def test_current_image_if_modified_since_stale(client, device_config_dev):
    _save_png(device_config_dev.current_image_file)
    resp = client.get(
        "/api/current_image",
        headers={"If-Modified-Since": "Mon, 01 Jan 2001 00:00:00 GMT"},
    )
    assert resp.status_code == 200


def test_current_image_if_modified_since_malformed(client, device_config_dev):
    _save_png(device_config_dev.current_image_file)
    resp = client.get(
        "/api/current_image",
        headers={"If-Modified-Since": "not-a-valid-date"},
    )
    assert resp.status_code == 200


# ---- /display-next ----


def test_display_next_no_playlist(client, device_config_dev):
    resp = client.post("/display-next")
    assert resp.status_code == 400


def test_display_next_first_request_not_rate_limited(client, device_config_dev):
    """First POST to /display-next should not be rate-limited (returns 400 for no playlist, not 429)."""
    from blueprints.main import _reset_display_next_cooldown

    _reset_display_next_cooldown()
    resp = client.post("/display-next")
    assert resp.status_code == 400  # no active playlist, but NOT 429


def test_display_next_second_request_within_cooldown_returns_429(
    client, device_config_dev
):
    """Second immediate successful POST within cooldown returns 429."""
    from blueprints.main import _reset_display_next_cooldown

    _reset_display_next_cooldown()
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()

    resp = client.post("/display-next")
    assert resp.status_code == 200

    blocked = client.post("/display-next")
    assert blocked.status_code == 429
    body = blocked.get_json()
    assert body["success"] is False
    assert "wait" in body["error"].lower()


def test_display_next_failed_requests_do_not_arm_cooldown(client, device_config_dev):
    from blueprints.main import _reset_display_next_cooldown

    _reset_display_next_cooldown()
    first = client.post("/display-next")
    assert first.status_code == 400

    second = client.post("/display-next")
    assert second.status_code == 400


def test_display_next_after_successful_request_respects_cooldown(
    client, device_config_dev, monkeypatch
):
    """After the cooldown period elapses, the endpoint should accept successful requests again."""
    from blueprints.main import _reset_display_next_cooldown

    _reset_display_next_cooldown()

    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()

    fake_time = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])

    resp1 = client.post("/display-next")
    assert resp1.status_code == 200

    fake_time[0] = 1005.0
    resp2 = client.post("/display-next")
    assert resp2.status_code == 429

    fake_time[0] = 1011.0
    resp3 = client.post("/display-next")
    assert resp3.status_code == 200


def test_display_next_exception(client, flask_app, device_config_dev):
    """Plugin generation error returns 500."""
    mock_playlist = MagicMock()
    mock_plugin_inst = MagicMock()
    mock_plugin_inst.plugin_id = "test_plugin"
    mock_plugin_inst.name = "Test"
    mock_plugin_inst.settings = {}

    mock_pm = MagicMock()
    mock_pm.determine_active_playlist.return_value = mock_playlist
    mock_playlist.name = "Test Playlist"
    mock_playlist.get_next_eligible_plugin.return_value = mock_plugin_inst

    with patch.object(device_config_dev, "get_playlist_manager", return_value=mock_pm):
        refresh_task = flask_app.config["REFRESH_TASK"]
        refresh_task.running = True
        refresh_task.manual_update = MagicMock(
            side_effect=RuntimeError("generation failed")
        )

        resp = client.post("/display-next")
    assert resp.status_code == 500


# ---- /api/plugin_order ----


def test_plugin_order_invalid_json(client):
    resp = client.post(
        "/api/plugin_order",
        data="not json",
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_plugin_order_non_list(client):
    resp = client.post("/api/plugin_order", json={"order": "not-a-list"})
    assert resp.status_code == 400


def test_plugin_order_non_string_items(client):
    resp = client.post("/api/plugin_order", json={"order": [1, 2, 3]})
    assert resp.status_code == 400


def test_plugin_order_duplicate_items(client, device_config_dev):
    plugins = device_config_dev.get_plugins()
    plugin_id = plugins[0]["id"]
    resp = client.post("/api/plugin_order", json={"order": [plugin_id, plugin_id]})
    assert resp.status_code == 400
    assert "duplicate" in resp.get_json()["error"].lower()


def test_plugin_order_missing_items(client, device_config_dev):
    plugins = device_config_dev.get_plugins()
    resp = client.post("/api/plugin_order", json={"order": [plugins[0]["id"]]})
    assert resp.status_code == 400
    assert "include every plugin id exactly once" in resp.get_json()["error"].lower()
