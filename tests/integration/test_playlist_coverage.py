"""Additional tests for playlist.py blueprint coverage."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


# --- update_device_cycle endpoint tests ---


def test_update_device_cycle_success(client, flask_app):
    """Successfully update device cycle interval."""
    resp = client.put("/update_device_cycle", json={"minutes": 30})
    assert resp.status_code == 200
    assert resp.get_json().get("success") is True

    # Verify the config was updated
    device_config = flask_app.config["DEVICE_CONFIG"]
    assert device_config.get_config("plugin_cycle_interval_seconds") == 30 * 60


def test_update_device_cycle_min_boundary(client):
    """Minimum valid value is 1 minute."""
    resp = client.put("/update_device_cycle", json={"minutes": 1})
    assert resp.status_code == 200

    # Below minimum should fail
    resp2 = client.put("/update_device_cycle", json={"minutes": 0})
    assert resp2.status_code == 400
    assert "between 1 and 1440" in resp2.get_json().get("error", "")


def test_update_device_cycle_max_boundary(client):
    """Maximum valid value is 1440 minutes (24 hours)."""
    resp = client.put("/update_device_cycle", json={"minutes": 1440})
    assert resp.status_code == 200

    # Above maximum should fail
    resp2 = client.put("/update_device_cycle", json={"minutes": 1441})
    assert resp2.status_code == 400


def test_update_device_cycle_invalid_minutes(client):
    """Invalid minutes value."""
    resp = client.put("/update_device_cycle", json={"minutes": "abc"})
    assert resp.status_code == 400
    assert "Invalid minutes" in resp.get_json().get("error", "")


def test_update_device_cycle_missing_minutes(client):
    """Missing minutes defaults to 0 which is invalid."""
    resp = client.put("/update_device_cycle", json={})
    assert resp.status_code == 400


def test_update_device_cycle_signals_refresh_task(client, flask_app, monkeypatch):
    """Signals refresh task on successful update."""
    mock_signal = MagicMock()
    flask_app.config["REFRESH_TASK"].signal_config_change = mock_signal

    resp = client.put("/update_device_cycle", json={"minutes": 60})
    assert resp.status_code == 200
    mock_signal.assert_called_once()


def test_update_device_cycle_handles_signal_exception(client, flask_app, monkeypatch):
    """Handles exception from signal_config_change gracefully."""
    def raise_error():
        raise RuntimeError("signal failed")

    flask_app.config["REFRESH_TASK"].signal_config_change = raise_error

    # Should still succeed even if signal fails
    resp = client.put("/update_device_cycle", json={"minutes": 60})
    assert resp.status_code == 200


# --- create_playlist overlapping times tests ---


def test_create_playlist_overlapping_times(client):
    """Reject playlist with overlapping time window."""
    # Create first playlist
    resp1 = client.post(
        "/create_playlist",
        json={"playlist_name": "Morning", "start_time": "06:00", "end_time": "09:00"},
    )
    assert resp1.status_code == 200

    # Try to create overlapping playlist
    resp2 = client.post(
        "/create_playlist",
        json={"playlist_name": "Overlap", "start_time": "08:00", "end_time": "10:00"},
    )
    assert resp2.status_code == 400
    assert "overlaps" in resp2.get_json().get("error", "").lower()


def test_create_playlist_non_overlapping(client):
    """Allow non-overlapping playlist."""
    # Create first playlist
    client.post(
        "/create_playlist",
        json={"playlist_name": "Morning", "start_time": "06:00", "end_time": "09:00"},
    )

    # Create non-overlapping playlist
    resp = client.post(
        "/create_playlist",
        json={"playlist_name": "Afternoon", "start_time": "12:00", "end_time": "15:00"},
    )
    assert resp.status_code == 200


def test_create_playlist_24hour_end_time(client):
    """Playlist with 24:00 end time (midnight next day)."""
    resp = client.post(
        "/create_playlist",
        json={"playlist_name": "Night", "start_time": "22:00", "end_time": "24:00"},
    )
    assert resp.status_code == 200


# --- update_playlist overlapping times tests ---


def test_update_playlist_overlapping_excluded_self(client):
    """Update should not consider current playlist as overlap."""
    # Create two playlists
    client.post(
        "/create_playlist",
        json={"playlist_name": "First", "start_time": "06:00", "end_time": "09:00"},
    )
    client.post(
        "/create_playlist",
        json={"playlist_name": "Second", "start_time": "12:00", "end_time": "15:00"},
    )

    # Update First to same time range - should work (no overlap with self)
    resp = client.put(
        "/update_playlist/First",
        json={"new_name": "First", "start_time": "06:00", "end_time": "09:00"},
    )
    assert resp.status_code == 200


def test_update_playlist_overlapping_with_other(client):
    """Update that would overlap with another playlist should fail."""
    # Create two playlists
    client.post(
        "/create_playlist",
        json={"playlist_name": "First", "start_time": "06:00", "end_time": "09:00"},
    )
    client.post(
        "/create_playlist",
        json={"playlist_name": "Second", "start_time": "12:00", "end_time": "15:00"},
    )

    # Try to update First to overlap with Second
    resp = client.put(
        "/update_playlist/First",
        json={"new_name": "First", "start_time": "11:00", "end_time": "13:00"},
    )
    assert resp.status_code == 400
    assert "overlaps" in resp.get_json().get("error", "").lower()


def test_update_playlist_cycle_minutes_override(client, flask_app):
    """Cycle minutes override is applied."""
    # Create playlist
    client.post(
        "/create_playlist",
        json={"playlist_name": "Test", "start_time": "06:00", "end_time": "09:00"},
    )

    # Update with cycle override
    resp = client.put(
        "/update_playlist/Test",
        json={
            "new_name": "Test",
            "start_time": "06:00",
            "end_time": "09:00",
            "cycle_minutes": 15,
        },
    )
    assert resp.status_code == 200

    # Verify cycle was set
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    pl = pm.get_playlist("Test")
    assert pl.cycle_interval_seconds == 15 * 60


# --- display_next_in_playlist tests ---


def test_display_next_in_playlist_missing_name(client):
    """Missing playlist_name returns error."""
    resp = client.post("/display_next_in_playlist", json={})
    assert resp.status_code == 400
    assert "required" in resp.get_json().get("error", "").lower()


def test_display_next_in_playlist_not_found(client):
    """Non-existent playlist returns error."""
    resp = client.post("/display_next_in_playlist", json={"playlist_name": "NoSuch"})
    assert resp.status_code == 400
    assert "not found" in resp.get_json().get("error", "").lower()


def test_display_next_in_playlist_no_eligible(client, flask_app):
    """Playlist with no eligible plugins returns error."""
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    pm.add_playlist("Empty", "00:00", "24:00")
    flask_app.config["DEVICE_CONFIG"].write_config()

    resp = client.post("/display_next_in_playlist", json={"playlist_name": "Empty"})
    assert resp.status_code == 400
    assert "no eligible" in resp.get_json().get("error", "").lower()


def test_display_next_in_playlist_success(client, flask_app, monkeypatch):
    """Successfully triggers manual update for next eligible plugin."""
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    pm.add_playlist("Test", "00:00", "24:00")
    pl = pm.get_playlist("Test")
    pl.add_plugin({
        "plugin_id": "clock",
        "name": "TestClock",
        "plugin_settings": {},
        "refresh": {"interval": 60},
    })
    flask_app.config["DEVICE_CONFIG"].write_config()

    # Mock manual_update to verify it's called
    mock_update = MagicMock()
    flask_app.config["REFRESH_TASK"].manual_update = mock_update

    resp = client.post("/display_next_in_playlist", json={"playlist_name": "Test"})
    assert resp.status_code == 200
    assert resp.get_json().get("success") is True
    mock_update.assert_called_once()


# --- add_plugin scheduled type tests ---


def test_add_plugin_scheduled_type_success(client, device_config_dev):
    """Successfully add plugin with scheduled refresh type."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    device_config_dev.write_config()

    payload = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps({
            "playlist": "Default",
            "instance_name": "ScheduledClock",
            "refreshType": "scheduled",
            "refreshTime": "08:00",
        }),
    }
    resp = client.post("/add_plugin", data=payload)
    assert resp.status_code == 200
    assert resp.get_json().get("success") is True


# --- reorder_plugins edge cases ---


def test_reorder_plugins_playlist_not_found(client):
    """Reorder on non-existent playlist returns error."""
    payload = {
        "playlist_name": "NoSuch",
        "ordered": [{"plugin_id": "clock", "name": "A"}],
    }
    resp = client.post("/reorder_plugins", json=payload)
    assert resp.status_code == 400
    assert "not found" in resp.get_json().get("error", "").lower()


def test_reorder_plugins_invalid_order(client, flask_app):
    """Invalid order payload returns error."""
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    pm.add_playlist("Test", "00:00", "24:00")
    pl = pm.get_playlist("Test")
    pl.add_plugin({
        "plugin_id": "clock",
        "name": "A",
        "plugin_settings": {},
        "refresh": {"interval": 60},
    })
    flask_app.config["DEVICE_CONFIG"].write_config()

    # Wrong plugin in order
    payload = {
        "playlist_name": "Test",
        "ordered": [{"plugin_id": "weather", "name": "B"}],  # doesn't exist
    }
    resp = client.post("/reorder_plugins", json=payload)
    assert resp.status_code == 400


def test_reorder_plugins_missing_fields(client):
    """Missing required fields returns error."""
    resp = client.post("/reorder_plugins", json={"playlist_name": "Test"})
    assert resp.status_code == 400


# --- playlist_eta edge cases ---


def test_playlist_eta_empty_playlist(client, flask_app):
    """ETA for empty playlist returns empty map."""
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    pm.add_playlist("Empty", "00:00", "24:00")
    flask_app.config["DEVICE_CONFIG"].write_config()

    resp = client.get("/playlist/eta/Empty")
    assert resp.status_code == 200
    j = resp.get_json()
    assert j.get("eta") == {}


def test_playlist_eta_caching(client, flask_app):
    """ETA is cached per minute."""
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    pm.add_playlist("Cached", "00:00", "24:00")
    pl = pm.get_playlist("Cached")
    pl.add_plugin({
        "plugin_id": "clock",
        "name": "A",
        "plugin_settings": {},
        "refresh": {"interval": 60},
    })
    flask_app.config["DEVICE_CONFIG"].write_config()

    # First call
    resp1 = client.get("/playlist/eta/Cached")
    assert resp1.status_code == 200

    # Second call should use cache (within same minute)
    resp2 = client.get("/playlist/eta/Cached")
    assert resp2.status_code == 200
    assert resp1.get_json()["eta"] == resp2.get_json()["eta"]


# --- format_relative_time edge cases ---


def test_format_relative_time_no_timezone_raises():
    """Naive datetime without timezone raises ValueError."""
    from blueprints.playlist import format_relative_time

    naive_dt = datetime.now().isoformat()  # no tzinfo
    # This should work since datetime.now() on modern Python includes local TZ
    # But explicitly test with a naive ISO string
    try:
        format_relative_time("2024-01-15T10:00:00")  # naive - no TZ
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "timezone" in str(e).lower()


def test_format_relative_time_edge_boundaries():
    """Test boundary conditions for relative time formatting."""
    from blueprints.playlist import format_relative_time

    now = datetime.now().astimezone()

    # Just under 2 minutes (119 seconds) should be "just now"
    under_two_min = (now - timedelta(seconds=119)).isoformat()
    result = format_relative_time(under_two_min)
    assert result == "just now"

    # At exactly 2 minutes (120 seconds), should be "minutes ago" (>= 120)
    two_min = (now - timedelta(seconds=120)).isoformat()
    result2 = format_relative_time(two_min)
    assert "minutes ago" in result2
