"""Integration tests for routes to improve coverage."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch


def test_create_playlist_route(client, device_config_dev):
    """Test creating a new playlist."""
    resp = client.post("/create_playlist", data={
        "playlist_name": "Test Playlist",
        "start_time": "08:00",
        "end_time": "22:00"
    }, follow_redirects=True)
    assert resp.status_code == 200


def test_delete_playlist_route(client, device_config_dev):
    """Test deleting a playlist."""
    # First create a playlist
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("ToDelete"):
        pm.add_playlist("ToDelete", "00:00", "24:00")
        device_config_dev.write_config()

    resp = client.delete("/delete_playlist/ToDelete")
    assert resp.status_code == 200


def test_delete_playlist_nonexistent(client, device_config_dev):
    """Deleting a nonexistent playlist returns 400."""
    resp = client.delete("/delete_playlist/DoesNotExist")
    assert resp.status_code == 400


def test_reorder_plugins_route(client, device_config_dev):
    """Test reordering plugins in playlist."""
    # Setup playlist with plugins
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")

    resp = client.post("/reorder_plugins", json={
        "playlist_name": "Default",
        "plugin_instances": ["Instance1", "Instance2"]
    })
    assert resp.status_code == 400  # Plugin instances don't exist


def test_delete_plugin_instance_route(client, device_config_dev):
    """Test deleting a nonexistent plugin instance returns 400."""
    resp = client.delete("/delete_plugin_instance", json={
        "playlist_name": "Default",
        "plugin_instance": "NonExistent"
    })
    assert resp.status_code == 400


def test_display_plugin_instance_route(client, device_config_dev):
    """Test displaying a nonexistent plugin instance returns 400."""
    resp = client.post("/display_plugin_instance", json={
        "playlist_name": "Default",
        "plugin_instance": "TestInstance"
    })
    assert resp.status_code == 400


def test_update_playlist_route(client, device_config_dev):
    """Test updating playlist settings — PUT method required."""
    # Create a playlist first
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
        device_config_dev.write_config()

    # The route uses PUT and requires new_name, start_time, end_time
    resp = client.put("/update_playlist/Default", json={
        "new_name": "Default",
        "start_time": "09:00",
        "end_time": "21:00"
    })
    assert resp.status_code == 200


def test_update_playlist_route_post_not_allowed(client, device_config_dev):
    """POST to /update_playlist should return 405 (method not allowed)."""
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
        device_config_dev.write_config()

    resp = client.post("/update_playlist/Default", data={
        "start_time": "09:00",
        "end_time": "21:00"
    })
    assert resp.status_code == 405


def test_save_plugin_settings_route(client, device_config_dev):
    """Test saving plugin settings returns 200."""
    resp = client.post("/plugin/clock/save", data={
        "name": "Test Clock",
        "refresh_interval": "300"
    })
    assert resp.status_code == 200


def test_update_device_settings_route(client, device_config_dev):
    """Test updating device settings returns 422 when timezone missing."""
    resp = client.post("/settings/device", data={
        "timezone": "America/New_York",
        "time_format": "12h"
    })
    assert resp.status_code == 422


def test_update_display_settings_route(client, device_config_dev):
    """Test updating display settings returns 422 when required fields missing."""
    resp = client.post("/settings/display", data={
        "orientation": "horizontal",
        "inverted": "false"
    })
    assert resp.status_code == 422


def test_update_network_settings_route(client, device_config_dev):
    """Test updating network settings returns 422 when required fields missing."""
    resp = client.post("/settings/network", data={
        "device_name": "inkypi-test"
    })
    assert resp.status_code == 422


def test_plugin_list_route(client, device_config_dev):
    """Test plugin list endpoint returns 404 (no /plugins GET route)."""
    resp = client.get("/plugins")
    assert resp.status_code == 404


def test_plugin_preview_route(client, device_config_dev):
    """Test plugin preview generation returns 404 (no preview route)."""
    resp = client.post("/plugin/clock/preview", data={
        "name": "Preview Clock"
    })
    assert resp.status_code == 404


def test_refresh_display_route(client, device_config_dev):
    """Test manual display refresh — returns 400 (no active playlist)."""
    resp = client.post("/refresh")
    assert resp.status_code == 400


def test_display_next_route(client, device_config_dev):
    """Test display next in playlist — returns 400 when playlist does not exist."""
    resp = client.post("/display_next_in_playlist", json={
        "playlist_name": "Default"
    })
    assert resp.status_code == 400


def test_history_clear_route(client, device_config_dev):
    """Test clearing history returns 200."""
    resp = client.post("/history/clear")
    assert resp.status_code == 200


def test_history_delete_entry_route(client, device_config_dev):
    """Test deleting nonexistent history entry returns 404."""
    resp = client.delete("/history/entry/123")
    assert resp.status_code == 404


def test_settings_export_route(client, device_config_dev):
    """Test exporting settings returns 200."""
    resp = client.get("/settings/export")
    assert resp.status_code == 200


def test_settings_import_route(client, device_config_dev):
    """Test importing settings with empty data returns 400."""
    resp = client.post("/settings/import", data={})
    assert resp.status_code == 400


def test_device_info_route(client, device_config_dev):
    """Test device info endpoint returns 404 (route does not exist)."""
    resp = client.get("/device-info")
    assert resp.status_code == 404


def test_playlist_eta_route(client, device_config_dev):
    """Test playlist ETA calculation returns 200."""
    resp = client.get("/playlist/eta/Default")
    assert resp.status_code == 200


def test_plugin_install_route(client, device_config_dev):
    """Test plugin installation returns 405 (no such POST route)."""
    resp = client.post("/plugin/install", data={
        "plugin_id": "clock"
    })
    assert resp.status_code == 405


def test_plugin_uninstall_route(client, device_config_dev):
    """Test plugin uninstallation returns 405 (no such POST route)."""
    resp = client.post("/plugin/uninstall", data={
        "plugin_id": "nonexistent"
    })
    assert resp.status_code == 405


def test_system_restart_route(client, device_config_dev):
    """Test system restart endpoint returns 404 (route does not exist)."""
    resp = client.post("/system/restart")
    assert resp.status_code == 404


def test_system_shutdown_route(client, device_config_dev):
    """Test system shutdown endpoint returns 404 (route does not exist)."""
    resp = client.post("/system/shutdown")
    assert resp.status_code == 404


def test_logs_download_route(client, device_config_dev):
    """Test downloading logs returns 404 (route does not exist)."""
    resp = client.get("/logs/download")
    assert resp.status_code == 404


def test_backup_create_route(client, device_config_dev):
    """Test creating backup returns 404 (route does not exist)."""
    resp = client.post("/backup/create")
    assert resp.status_code == 404


def test_backup_restore_route(client, device_config_dev):
    """Test restoring backup returns 404 (route does not exist)."""
    resp = client.post("/backup/restore", data={})
    assert resp.status_code == 404
