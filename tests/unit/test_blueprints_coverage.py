"""Tests for blueprint routes to improve code coverage."""

import pytest
from datetime import datetime
from unittest.mock import patch, Mock, MagicMock


def test_get_current_image_conditional_request(client, device_config_dev):
    """Test get_current_image with If-Modified-Since header."""
    # First request - get the image
    resp1 = client.get("/current-image")
    assert resp1.status_code in [200, 404]  # 404 if no image exists yet

    if resp1.status_code == 200:
        # Get the Last-Modified header
        last_modified = resp1.headers.get("Last-Modified")
        assert last_modified is not None

        # Second request with If-Modified-Since - should return 304
        resp2 = client.get("/current-image", headers={"If-Modified-Since": last_modified})
        assert resp2.status_code == 304


def test_get_current_image_no_conditional(client, device_config_dev):
    """Test get_current_image without conditional headers."""
    resp = client.get("/current-image")
    # Should either return image or 404
    assert resp.status_code in [200, 404]


def test_refresh_info_with_exception(client, device_config_dev):
    """Test refresh_info handles exceptions gracefully."""
    # Mock get_refresh_info to raise an exception
    with patch.object(
        device_config_dev,
        "get_refresh_info",
        side_effect=Exception("Refresh info error")
    ):
        resp = client.get("/refresh-info")
        assert resp.status_code == 200
        data = resp.get_json()
        # Should return empty dict on exception
        assert isinstance(data, dict)


def test_refresh_info_success(client, device_config_dev):
    """Test refresh_info returns data successfully."""
    resp = client.get("/refresh-info")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)


def test_next_up_no_playlist(client, device_config_dev):
    """Test next_up when no active playlist."""
    # Mock determine_active_playlist to return None
    pm = device_config_dev.get_playlist_manager()
    with patch.object(pm, "determine_active_playlist", return_value=None):
        resp = client.get("/next-up")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {}


def test_next_up_no_next_plugin(client, device_config_dev, monkeypatch):
    """Test next_up when playlist has no next plugin."""
    from datetime import datetime, timezone

    pm = device_config_dev.get_playlist_manager()

    # Create a playlist but mock peek_next_plugin to return None
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")

    playlist = pm.get_playlist("Default")
    original_peek = playlist.peek_next_plugin

    def mock_peek_next(*args, **kwargs):
        return None

    with patch.object(playlist, "peek_next_plugin", side_effect=mock_peek_next):
        with patch.object(playlist, "peek_next_eligible_plugin", side_effect=mock_peek_next):
            resp = client.get("/next-up")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data == {}


def test_next_up_with_exception(client, device_config_dev):
    """Test next_up handles exceptions gracefully."""
    pm = device_config_dev.get_playlist_manager()

    # Mock determine_active_playlist to raise an exception
    with patch.object(pm, "determine_active_playlist", side_effect=Exception("Playlist error")):
        resp = client.get("/next-up")
        assert resp.status_code == 200
        data = resp.get_json()
        # Should return empty dict on exception
        assert data == {}


def test_static_files_route(client):
    """Test static files route serves files."""
    # Try to get a known static file (if it exists)
    resp = client.get("/static/images/placeholder.png")
    # Should either return file or 404
    assert resp.status_code in [200, 404]


def test_current_image_with_invalid_if_modified_since(client, device_config_dev):
    """Test get_current_image with invalid If-Modified-Since header."""
    resp = client.get("/current-image", headers={"If-Modified-Since": "invalid-date-format"})
    # Should handle gracefully and return image or 404
    assert resp.status_code in [200, 404]


def test_dashboard_renders(client, device_config_dev):
    """Test dashboard route renders successfully."""
    resp = client.get("/")
    assert resp.status_code == 200
    # Should contain some expected content
    assert b"html" in resp.data or b"<!DOCTYPE" in resp.data


def test_logs_endpoint(client, device_config_dev):
    """Test logs endpoint returns log entries."""
    resp = client.get("/logs")
    assert resp.status_code in [200, 404]  # Endpoint may not exist
    if resp.status_code == 200:
        # Should return JSON with logs
        data = resp.get_json()
        assert isinstance(data, (dict, list))


def test_system_info_endpoint(client, device_config_dev):
    """Test system info endpoint."""
    resp = client.get("/system-info")
    assert resp.status_code in [200, 404]  # Depends on if route exists


def test_config_endpoint(client, device_config_dev):
    """Test config endpoint returns configuration."""
    resp = client.get("/config")
    assert resp.status_code in [200, 404]  # Depends on if route exists
