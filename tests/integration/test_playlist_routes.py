# pyright: reportMissingImports=false


def test_playlist_page_renders(client):
    resp = client.get("/playlist")
    assert resp.status_code == 200
    assert b'data-page-shell="dashboard"' in resp.data
    assert b'id="newPlaylistBtn"' in resp.data
    assert b'data-collapsed-label="Open"' in resp.data


def test_create_update_delete_playlist_flow(client):
    # Create
    payload = {"playlist_name": "Morning", "start_time": "06:00", "end_time": "09:00"}
    resp = client.post("/create_playlist", json=payload)
    assert resp.status_code == 200

    # Update (also set cycle override to 5 min)
    upd = {
        "new_name": "EarlyMorning",
        "start_time": "05:00",
        "end_time": "08:00",
        "cycle_minutes": 5,
    }
    resp = client.put("/update_playlist/Morning", json=upd)
    assert resp.status_code == 200

    # Delete
    resp = client.delete("/delete_playlist/EarlyMorning")
    assert resp.status_code == 200


def test_add_plugin_to_playlist_validation(client):
    # Missing fields
    resp = client.post("/add_plugin", data={})
    assert resp.status_code == 500 or resp.status_code == 400


def test_reorder_plugins_endpoint(client, device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "A",
            "plugin_settings": {},
            "refresh": {"interval": 60},
        }
    )
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "B",
            "plugin_settings": {},
            "refresh": {"interval": 60},
        }
    )
    device_config_dev.write_config()

    payload = {
        "playlist_name": "Default",
        "ordered": [
            {"plugin_id": "clock", "name": "B"},
            {"plugin_id": "weather", "name": "A"},
        ],
    }
    resp = client.post("/reorder_plugins", json=payload)
    assert resp.status_code == 200
    j = resp.get_json()
    assert j.get("success") is True

    # Verify order updated in memory
    pl2 = pm.get_playlist("Default")
    assert len(pl2.plugins) == 2
    assert pl2.plugins[0].plugin_id == "clock"
    assert pl2.plugins[0].name == "B"


def test_cycle_override_zero_enforces_minimum_60_seconds(client, device_config_dev):
    """JTN-232: cycle_minutes=0 must not produce cycle_interval_seconds of 0 (infinite loop)."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("CycleTest", "10:00", "11:00")
    device_config_dev.write_config()

    upd = {
        "new_name": "CycleTest",
        "start_time": "10:00",
        "end_time": "11:00",
        "cycle_minutes": 0,
    }
    resp = client.put("/update_playlist/CycleTest", json=upd)
    assert resp.status_code == 200

    pl = pm.get_playlist("CycleTest")
    assert pl is not None
    assert (
        pl.cycle_interval_seconds >= 60
    ), f"cycle_interval_seconds should be at least 60, got {pl.cycle_interval_seconds}"


def test_update_playlist_rejects_special_char_name(client, device_config_dev):
    """JTN-256: update_playlist must validate new_name and reject XSS-style names."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("SafeName", "12:00", "13:00")
    device_config_dev.write_config()

    upd = {
        "new_name": "<script>alert(1)</script>",
        "start_time": "12:00",
        "end_time": "13:00",
    }
    resp = client.put("/update_playlist/SafeName", json=upd)
    assert resp.status_code == 400
    j = resp.get_json()
    assert j.get("success") is False


def test_update_playlist_rejects_name_over_64_chars(client, device_config_dev):
    """JTN-256: update_playlist must reject names longer than 64 characters."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("LongNameTest", "14:00", "15:00")
    device_config_dev.write_config()

    long_name = "A" * 65
    upd = {
        "new_name": long_name,
        "start_time": "14:00",
        "end_time": "15:00",
    }
    resp = client.put("/update_playlist/LongNameTest", json=upd)
    assert resp.status_code == 400
    j = resp.get_json()
    assert j.get("success") is False


def test_toggle_only_fresh_and_snooze(client, device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "A",
            "plugin_settings": {},
            "refresh": {"interval": 60},
        }
    )
    device_config_dev.write_config()

    # Only-fresh and snooze endpoints removed; nothing to assert here now (keep test for compatibility)
    assert True


# JTN-217: Overlap-with-Default warning


def _ensure_default_playlist(device_config_dev) -> None:
    """Ensure a Default (00:00-24:00) playlist exists in the config."""
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
        device_config_dev.write_config()


def _assert_overlap_warning(data) -> None:
    """Assert the response includes a Default-overlap warning."""
    assert "warning" in data
    assert "Default" in data["warning"]
    assert "priority" in data["warning"]


def test_create_playlist_overlapping_default_returns_warning(client, device_config_dev):
    """Creating a playlist whose hours overlap Default should succeed and return a warning."""
    _ensure_default_playlist(device_config_dev)

    payload = {"playlist_name": "Morning", "start_time": "06:00", "end_time": "09:00"}
    resp = client.post("/create_playlist", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True
    _assert_overlap_warning(data)


def test_create_default_playlist_does_not_warn_about_itself(client, device_config_dev):
    """Creating a playlist named 'Default' should not emit a warning about overlapping Default."""
    pm = device_config_dev.get_playlist_manager()
    pm.delete_playlist("Default")
    device_config_dev.write_config()

    payload = {"playlist_name": "Default", "start_time": "00:00", "end_time": "24:00"}
    resp = client.post("/create_playlist", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True
    assert "warning" not in data or data.get("warning") is None


def test_update_playlist_overlapping_default_returns_warning(client, device_config_dev):
    """Updating a playlist so its hours overlap Default should succeed and return a warning."""
    _ensure_default_playlist(device_config_dev)
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Morning"):
        pm.add_playlist("Morning", "06:00", "09:00")
        device_config_dev.write_config()

    upd = {
        "new_name": "Morning",
        "start_time": "07:00",
        "end_time": "10:00",
    }
    resp = client.put("/update_playlist/Morning", json=upd)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True
    _assert_overlap_warning(data)


def test_update_default_playlist_does_not_warn_about_itself(client, device_config_dev):
    """Updating the Default playlist itself should not emit a warning about overlapping Default."""
    _ensure_default_playlist(device_config_dev)
    upd = {
        "new_name": "Default",
        "start_time": "00:00",
        "end_time": "24:00",
    }
    resp = client.put("/update_playlist/Default", json=upd)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True
    assert "warning" not in data or data.get("warning") is None
