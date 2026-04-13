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


def test_cycle_override_zero_rejected(client, device_config_dev):
    """JTN-232/JTN-469: cycle_minutes=0 must be rejected with 400 (range: 1-1440)."""
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
    assert resp.status_code == 400
    j = resp.get_json()
    assert "cycle_minutes" in j.get("error", "").lower()

    # Playlist should remain unchanged (no cycle override applied)
    pl = pm.get_playlist("CycleTest")
    assert pl is not None
    assert pl.cycle_interval_seconds is None


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


# JTN-469: cycle_minutes range validation


def test_update_playlist_rejects_cycle_minutes_above_max(client, device_config_dev):
    """JTN-469: cycle_minutes > 1440 must be rejected with 400 and a clear error."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("RangeTest", "06:00", "10:00")
    device_config_dev.write_config()

    upd = {
        "new_name": "RangeTest",
        "start_time": "06:00",
        "end_time": "10:00",
        "cycle_minutes": 5000,
    }
    resp = client.put("/update_playlist/RangeTest", json=upd)
    assert resp.status_code == 400
    j = resp.get_json()
    assert j.get("success") is False
    assert "cycle_minutes" in j.get("error", "").lower()

    # Confirm no cycle override was applied
    pl = pm.get_playlist("RangeTest")
    assert pl.cycle_interval_seconds is None


def test_update_playlist_valid_cycle_minutes_persisted(client, device_config_dev):
    """JTN-469: valid cycle_minutes (30) must be persisted and readable back."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("PersistTest", "08:00", "12:00")
    device_config_dev.write_config()

    upd = {
        "new_name": "PersistTest",
        "start_time": "08:00",
        "end_time": "12:00",
        "cycle_minutes": 30,
    }
    resp = client.put("/update_playlist/PersistTest", json=upd)
    assert resp.status_code == 200
    j = resp.get_json()
    assert j.get("success") is True

    pl = pm.get_playlist("PersistTest")
    assert pl is not None
    assert pl.cycle_interval_seconds == 30 * 60


def test_update_playlist_absent_cycle_minutes_clears_nothing(client, device_config_dev):
    """JTN-469: omitting cycle_minutes must not change existing cycle override."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("OmitTest", "09:00", "11:00")
    pl = pm.get_playlist("OmitTest")
    pl.cycle_interval_seconds = 45 * 60
    device_config_dev.write_config()

    upd = {
        "new_name": "OmitTest",
        "start_time": "09:00",
        "end_time": "11:00",
        # cycle_minutes deliberately absent
    }
    resp = client.put("/update_playlist/OmitTest", json=upd)
    assert resp.status_code == 200

    pl2 = pm.get_playlist("OmitTest")
    # cycle not modified when key absent
    assert pl2.cycle_interval_seconds == 45 * 60


def test_update_playlist_null_cycle_minutes_leaves_override_unchanged(
    client, device_config_dev
):
    """JTN-469: cycle_minutes=null is treated the same as absent (no-op on cycle)."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("NullTest", "10:00", "12:00")
    pl = pm.get_playlist("NullTest")
    pl.cycle_interval_seconds = 20 * 60
    device_config_dev.write_config()

    upd = {
        "new_name": "NullTest",
        "start_time": "10:00",
        "end_time": "12:00",
        "cycle_minutes": None,
    }
    resp = client.put("/update_playlist/NullTest", json=upd)
    assert resp.status_code == 200

    pl2 = pm.get_playlist("NullTest")
    assert pl2.cycle_interval_seconds == 20 * 60


def test_playlist_to_dict_exposes_cycle_minutes(device_config_dev):
    """JTN-469: Playlist.to_dict() must include cycle_minutes when cycle_interval_seconds is set."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("DictTest", "07:00", "08:00")
    pl = pm.get_playlist("DictTest")
    pl.cycle_interval_seconds = 15 * 60

    d = pl.to_dict()
    assert d.get("cycle_minutes") == 15


def test_playlist_to_dict_no_cycle_minutes_when_unset(device_config_dev):
    """JTN-469: Playlist.to_dict() must not include cycle_minutes when no override is set."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("NoCycleDict", "07:00", "08:00")
    pl = pm.get_playlist("NoCycleDict")

    d = pl.to_dict()
    assert "cycle_minutes" not in d


def test_create_playlist_accepts_wraparound_times(client):
    """JTN-353: Playlists with start > end (wraps past midnight) should be accepted.

    The model already supports wraparound via Playlist.is_active(), so we accept
    the reverse-time case rather than rejecting it.
    """
    payload = {
        "playlist_name": "NightShift",
        "start_time": "20:00",
        "end_time": "08:00",
    }
    resp = client.post("/create_playlist", json=payload)
    assert resp.status_code == 200
    j = resp.get_json()
    assert j.get("success") is True


def test_playlist_page_labels_wraparound_next_day(client):
    """JTN-353: The playlist list summary must mark wrap-past-midnight ranges with '(next day)'.

    Without the label the UI renders '20:00 - 08:00' identically to a normal
    same-day range, so users cannot tell that it wraps.
    """
    payload = {
        "playlist_name": "Overnight",
        "start_time": "22:00",
        "end_time": "06:00",
    }
    resp = client.post("/create_playlist", json=payload)
    assert resp.status_code == 200

    resp = client.get("/playlist")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # The summary line for Overnight should contain the wrap label.
    # Find the Overnight summary section and check for the label nearby.
    assert "22:00 - 06:00" in body
    assert "(next day)" in body
    assert "playlist-wrap-label" in body


def test_playlist_page_no_wrap_label_for_normal_range(client):
    """JTN-353: Normal same-day ranges must NOT get the '(next day)' label."""
    payload = {
        "playlist_name": "Daytime",
        "start_time": "09:00",
        "end_time": "17:00",
    }
    resp = client.post("/create_playlist", json=payload)
    assert resp.status_code == 200

    resp = client.get("/playlist")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "09:00 - 17:00" in body
    # The Daytime row should not carry the wrap label. We can't easily scope to
    # just the Daytime row, so assert that when Daytime is the only non-default
    # playlist the label markup is absent unless another wrap-range exists.
    # To keep the assertion robust, check the substring around "09:00 - 17:00".
    idx = body.find("09:00 - 17:00")
    # Look within the next 200 chars for the label — it must not appear.
    assert "(next day)" not in body[idx : idx + 200]


def test_playlist_page_hides_auto_generated_instance_keys(client, device_config_dev):
    """JTN-620: Playlists page must not display raw {plugin_id}_saved_settings keys.

    Internal ``data-*`` attributes and element ``id``s may still reference
    the raw key because the JS layer needs it for API calls against the
    filesystem settings file — but it must never appear in visible text or
    in ``aria-label`` attributes read by screen readers.
    """
    import re

    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.plugins = []
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "weather_saved_settings",
            "plugin_settings": {},
            "refresh": {"interval": 600},
        }
    )
    device_config_dev.write_config()

    resp = client.get("/playlist")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # No aria-label may expose the raw key.
    aria_labels = re.findall(r'aria-label="([^"]*)"', body)
    leaked_arias = [a for a in aria_labels if "weather_saved_settings" in a]
    assert not leaked_arias, f"aria-labels leak raw key: {leaked_arias}"

    # Visible text inside <span class="plugin-instance"> must not be the raw key.
    visible_spans = re.findall(
        r'<span class="plugin-instance">([^<]*)',
        body,
    )
    assert visible_spans, "expected plugin-instance spans in rendered playlist"
    for span_text in visible_spans:
        assert "weather_saved_settings" not in span_text

    # A humanised label should be present somewhere for the user.
    assert "Weather" in body


def test_playlist_header_chip_uses_plain_language_refresh_interval(client):
    """JTN-640: Playlists header chip must say 'Refresh interval', not jargon
    'Device cadence'."""
    resp = client.get("/playlist")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Device cadence" not in body
    assert "Refresh interval" in body


def test_playlist_default_all_day_renders_as_all_day(client, device_config_dev):
    """JTN-639: A playlist spanning 00:00 - 24:00 should render 'All day'
    instead of the non-standard '24:00' end time."""
    pm = device_config_dev.get_playlist_manager()
    # Ensure a Default-like playlist exists with the full-day range
    pm.add_playlist("JTN639AllDay", "00:00", "24:00")
    device_config_dev.write_config()

    resp = client.get("/playlist")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Find the all-day playlist block and assert its summary copy
    idx = body.find("JTN639AllDay")
    assert idx != -1
    chunk = body[idx : idx + 600]
    assert "All day" in chunk
    assert "00:00 - 24:00" not in chunk


def test_playlist_page_preserves_user_instance_names(client, device_config_dev):
    """User-renamed instances are preserved as visible labels."""
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.plugins = []
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "Kitchen Weather",
            "plugin_settings": {},
            "refresh": {"interval": 600},
        }
    )
    device_config_dev.write_config()

    resp = client.get("/playlist")
    assert resp.status_code == 200
    assert b"Kitchen Weather" in resp.data


def test_playlist_form_uses_native_time_input(client):
    """JTN-647: start/end time fields must be <input type="time"> (not a 15-min <select>).

    This lets users schedule arbitrary HH:MM values (e.g. 09:05) instead of the
    legacy quarter-hour-only dropdown options.
    """
    resp = client.get("/playlist")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Native time input renders for both start and end, not a <select>.
    assert 'type="time"' in body
    assert 'id="start_time"' in body
    assert 'id="end_time"' in body
    # The legacy <select> dropdowns should be gone.
    assert '<select id="start_time"' not in body
    assert '<select id="end_time"' not in body


def test_create_playlist_accepts_non_quarter_hour_times(client):
    """JTN-647: backend accepts arbitrary HH:MM values like 09:05 or 07:10."""
    payload = {
        "playlist_name": "OddHours",
        "start_time": "09:05",
        "end_time": "07:10",  # wraps past midnight; still a valid distinct time
    }
    resp = client.post("/create_playlist", json=payload)
    assert resp.status_code == 200

    # Update to another non-quarter-hour value.
    upd = {
        "new_name": "OddHours",
        "start_time": "06:37",
        "end_time": "22:13",
    }
    resp = client.put("/update_playlist/OddHours", json=upd)
    assert resp.status_code == 200
