# pyright: reportMissingImports=false
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask
from flask.testing import FlaskClient


def test_playlist_page_renders(client: FlaskClient) -> None:
    resp = client.get("/playlist")
    assert resp.status_code == 200
    assert b'data-page-shell="dashboard"' in resp.data
    assert b'id="newPlaylistBtn"' in resp.data
    assert b'data-collapsed-label="Open"' in resp.data


def _add_instance(device_config_dev: Any, name: str, **state: Any) -> Any:
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pm.get_playlist("Default").add_plugin(
        {
            "plugin_id": "clock",
            "name": name,
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    inst = pm.find_plugin("clock", name)
    for key, value in state.items():
        setattr(inst, key, value)
    return inst


def test_playlist_page_shows_paused_plugin_and_retry_time(
    client: FlaskClient, device_config_dev: Any, monkeypatch: Any
) -> None:
    """A circuit-breaker pause is visible, with its reason and retry time."""
    monkeypatch.delenv("PLUGIN_PAUSE_COOLDOWN_SECONDS", raising=False)
    _add_instance(
        device_config_dev,
        "Paused Clock",
        paused=True,
        consecutive_failure_count=5,
        disabled_reason="Paused after 5 consecutive failures. Last error: boom",
        # Far future: the retry time is deterministic and still to come.
        paused_at="2999-01-01T03:15:00+00:00",
    )
    _add_instance(device_config_dev, "Legacy Paused", paused=True)
    _add_instance(device_config_dev, "Healthy Clock")

    resp = client.get("/playlist")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # device_config_dev runs in UTC: 03:15 + 6 h cooldown.
    assert "Paused — retrying at 09:15" in html
    assert "Last error: boom" in html
    # A pause from before paused_at existed is retried on its next turn.
    assert "Paused — retrying on its next turn" in html
    assert html.count("plugin-paused-chip") == 2


def test_playlist_page_paused_label_when_auto_retry_is_off(
    client: FlaskClient, device_config_dev: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("PLUGIN_PAUSE_COOLDOWN_SECONDS", "0")
    _add_instance(device_config_dev, "Paused Clock", paused=True)

    html = client.get("/playlist").get_data(as_text=True)

    assert ">Paused</span>" in html
    assert "retrying" not in html


def _saved_playlists(device_config_dev: Any) -> dict[str, dict[str, Any]]:
    """The playlists in device.json, as the device would load them on boot."""
    saved = json.loads(Path(device_config_dev.config_file).read_text())
    return {p["name"]: p for p in saved["playlist_config"]["playlists"]}


def test_create_update_delete_playlist_flow(
    client: FlaskClient, device_config_dev: Any
) -> None:
    # Create
    payload = {"playlist_name": "Morning", "start_time": "06:00", "end_time": "09:00"}
    resp = client.post("/create_playlist", json=payload)
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    created = _saved_playlists(device_config_dev)["Morning"]
    assert (created["start_time"], created["end_time"]) == ("06:00", "09:00")
    assert "cycle_minutes" not in created
    assert client.get("/playlist/eta/Morning").status_code == 200

    # Update: rename, move the window, and set a 5-minute cycle override.
    upd = {
        "new_name": "EarlyMorning",
        "start_time": "05:00",
        "end_time": "08:00",
        "cycle_minutes": 5,
    }
    resp = client.put("/update_playlist/Morning", json=upd)
    assert resp.status_code == 200
    saved = _saved_playlists(device_config_dev)
    assert "Morning" not in saved
    updated = saved["EarlyMorning"]
    assert (updated["start_time"], updated["end_time"]) == ("05:00", "08:00")
    assert updated["cycle_minutes"] == 5
    assert client.get("/playlist/eta/Morning").status_code == 404

    # Delete
    resp = client.delete("/delete_playlist/EarlyMorning")
    assert resp.status_code == 200
    assert "EarlyMorning" not in _saved_playlists(device_config_dev)
    assert client.get("/playlist/eta/EarlyMorning").status_code == 404


def test_create_playlist_from_a_form_post_saves_it(
    client: FlaskClient, device_config_dev: Any
) -> None:
    resp = client.post(
        "/create_playlist",
        data={
            "playlist_name": "Test Playlist",
            "start_time": "08:00",
            "end_time": "22:00",
        },
    )
    assert resp.status_code == 200
    saved = _saved_playlists(device_config_dev)["Test Playlist"]
    assert (saved["start_time"], saved["end_time"]) == ("08:00", "22:00")
    assert saved["plugins"] == []


def test_create_playlist_refuses_a_duplicate_name(
    client: FlaskClient, device_config_dev: Any
) -> None:
    payload = {"playlist_name": "Evening", "start_time": "18:00", "end_time": "20:00"}
    assert client.post("/create_playlist", json=payload).status_code == 200

    again = {**payload, "start_time": "20:00", "end_time": "22:00"}
    resp = client.post("/create_playlist", json=again)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "A playlist with that name already exists"
    saved = _saved_playlists(device_config_dev)["Evening"]
    assert (saved["start_time"], saved["end_time"]) == ("18:00", "20:00")


def test_delete_unknown_playlist_is_not_found_and_deletes_nothing(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """JTN-782: an unknown name is a 404, not a silent success."""
    before = set(_saved_playlists(device_config_dev))

    resp = client.delete("/delete_playlist/DoesNotExist")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["success"] is False
    assert data["code"] == "not_found"
    assert set(_saved_playlists(device_config_dev)) == before


def test_update_playlist_accepts_form_payload(
    client: FlaskClient, device_config_dev: Any
) -> None:
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("FormUpdate", "06:00", "09:00")
    device_config_dev.write_config()

    resp = client.put(
        "/update_playlist/FormUpdate",
        data={
            "new_name": "FormUpdated",
            "start_time": "07:00",
            "end_time": "10:00",
            "cycle_minutes": "12",
        },
    )

    assert resp.status_code == 200
    playlist = pm.get_playlist("FormUpdated")
    assert playlist is not None
    assert playlist.cycle_interval_seconds == 12 * 60


def test_update_playlist_malformed_json_returns_fielded_error(
    client: FlaskClient,
) -> None:
    resp = client.put(
        "/update_playlist/Default",
        data=b"{{invalid",
        content_type="application/json",
    )

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"] == "Invalid JSON data"
    assert body["code"] == "validation_error"


def test_create_playlist_persists_cycle_override(
    client: Any, device_config_dev: Any
) -> None:
    payload = {
        "playlist_name": "FastLoop",
        "start_time": "06:00",
        "end_time": "09:00",
        "cycle_minutes": 12,
    }

    resp = client.post("/create_playlist", json=payload)

    assert resp.status_code == 200
    playlist = device_config_dev.get_playlist_manager().get_playlist("FastLoop")
    assert playlist.cycle_interval_seconds == 12 * 60


def test_delete_default_playlist_is_refused(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """JTN-781: DELETE /delete_playlist/Default must return 400 and keep the playlist."""
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    device_config_dev.write_config()

    resp = client.delete("/delete_playlist/Default")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["code"] == "validation_error"
    assert "default" in body["error"].lower()
    # Default must still exist after the rejected delete
    assert pm.get_playlist("Default") is not None


def test_delete_non_default_playlist_still_succeeds(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """JTN-781: guard must not regress deletion of regular user-created playlists."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Evening", "18:00", "22:00")
    device_config_dev.write_config()

    resp = client.delete("/delete_playlist/Evening")
    assert resp.status_code == 200
    assert pm.get_playlist("Evening") is None


def test_delete_lowercase_default_playlist_is_allowed(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """JTN-781: the guard is case-sensitive — 'default' (lowercase) is a
    user-created playlist and remains deletable. Matches how create/update
    elsewhere key off the exact string 'Default'."""
    pm = device_config_dev.get_playlist_manager()
    # Create a lowercase 'default' that is distinct from the canonical one.
    pm.add_playlist("default", "09:00", "10:00")
    device_config_dev.write_config()

    resp = client.delete("/delete_playlist/default")
    assert resp.status_code == 200
    assert pm.get_playlist("default") is None


def test_add_plugin_to_playlist_validation(client: FlaskClient) -> None:
    # Missing fields
    resp = client.post("/add_plugin", data={})
    assert resp.status_code == 500 or resp.status_code == 400


def test_reorder_plugins_endpoint(client: FlaskClient, device_config_dev: Any) -> None:
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


def test_reorder_plugins_rejects_empty_plugin_id(
    client: FlaskClient, device_config_dev: Any
) -> None:
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("BadReorder", "00:00", "24:00")
    pl = pm.get_playlist("BadReorder")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "A",
            "plugin_settings": {},
            "refresh": {"interval": 60},
        }
    )
    device_config_dev.write_config()

    resp = client.post(
        "/reorder_plugins",
        json={
            "playlist_name": "BadReorder",
            "ordered": [{"plugin_id": "", "name": "A"}],
        },
    )

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["details"]["field"] == "ordered"


def test_cycle_override_zero_rejected(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_update_playlist_rejects_special_char_name(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_update_playlist_rejects_name_over_64_chars(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_toggle_only_fresh_and_snooze(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def _ensure_default_playlist(device_config_dev: Any) -> None:
    """Ensure a Default (00:00-24:00) playlist exists in the config."""
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
        device_config_dev.write_config()


def _assert_overlap_warning(data: Any) -> None:
    """Assert the response includes a Default-overlap warning."""
    assert "warning" in data
    assert "Default" in data["warning"]
    assert "priority" in data["warning"]


def test_create_playlist_overlapping_default_returns_warning(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """Creating a playlist whose hours overlap Default should succeed and return a warning."""
    _ensure_default_playlist(device_config_dev)

    payload = {"playlist_name": "Morning", "start_time": "06:00", "end_time": "09:00"}
    resp = client.post("/create_playlist", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True
    _assert_overlap_warning(data)


def test_create_default_playlist_does_not_warn_about_itself(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_update_playlist_overlapping_default_returns_warning(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_update_default_playlist_does_not_warn_about_itself(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_update_playlist_rejects_cycle_minutes_above_max(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_update_playlist_valid_cycle_minutes_persisted(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_update_playlist_absent_cycle_minutes_clears_nothing(
    client: FlaskClient, device_config_dev: Any
) -> None:
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
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_playlist_to_dict_exposes_cycle_minutes(device_config_dev: Any) -> None:
    """JTN-469: Playlist.to_dict() must include cycle_minutes when cycle_interval_seconds is set."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("DictTest", "07:00", "08:00")
    pl = pm.get_playlist("DictTest")
    pl.cycle_interval_seconds = 15 * 60

    d = pl.to_dict()
    assert d.get("cycle_minutes") == 15


def test_playlist_to_dict_no_cycle_minutes_when_unset(device_config_dev: Any) -> None:
    """JTN-469: Playlist.to_dict() must not include cycle_minutes when no override is set."""
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("NoCycleDict", "07:00", "08:00")
    pl = pm.get_playlist("NoCycleDict")

    d = pl.to_dict()
    assert "cycle_minutes" not in d


def test_create_playlist_accepts_wraparound_times(client: FlaskClient) -> None:
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


def test_playlist_page_labels_wraparound_next_day(client: FlaskClient) -> None:
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


def test_playlist_page_no_wrap_label_for_normal_range(client: FlaskClient) -> None:
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


def test_playlist_page_hides_auto_generated_instance_keys(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_playlist_header_chip_uses_plain_language_refresh_interval(
    client: FlaskClient,
) -> None:
    """JTN-640: Playlists header chip must say 'Refresh interval', not jargon
    'Device cadence'."""
    resp = client.get("/playlist")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Device cadence" not in body
    assert "Refresh interval" in body


def test_playlist_default_all_day_renders_as_all_day(
    client: FlaskClient, device_config_dev: Any
) -> None:
    """JTN-639: A playlist spanning 00:00 - 24:00 should render 'All day'
    instead of the non-standard '24:00' end time."""
    pm = device_config_dev.get_playlist_manager()
    # Ensure a Default-like playlist exists with the full-day range
    pm.add_playlist("JTN639AllDay", "00:00", "24:00")
    device_config_dev.write_config()

    resp = client.get("/playlist")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Find the all-day playlist block and assert its summary copy. The window
    # is sized generously because the playlist card now carries a toggle
    # button with full a11y metadata (data-collapsed-label, data-expanded-label,
    # aria-label, title) before the summary copy, which pushes "All day"
    # further from the first `data-playlist-name` attribute occurrence.
    idx = body.find("JTN639AllDay")
    assert idx != -1
    chunk = body[idx : idx + 2000]
    assert "All day" in chunk
    assert "00:00 - 24:00" not in chunk


def test_playlist_page_preserves_user_instance_names(
    client: FlaskClient, device_config_dev: Any
) -> None:
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


def test_playlist_form_uses_native_time_input(client: FlaskClient) -> None:
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


def test_create_playlist_accepts_non_quarter_hour_times(client: FlaskClient) -> None:
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


# ---- /update_device_cycle: the loop's default interval ----


def _saved_device_cycle_seconds(device_config_dev: Any) -> Any:
    saved = json.loads(Path(device_config_dev.config_file).read_text())
    return saved["plugin_cycle_interval_seconds"]


@pytest.mark.parametrize("minutes", [1, 30, 1440])
def test_update_device_cycle_saves_the_interval(
    client: FlaskClient, device_config_dev: Any, minutes: int
) -> None:
    resp = client.put("/update_device_cycle", json={"minutes": minutes})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert _saved_device_cycle_seconds(device_config_dev) == minutes * 60


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        pytest.param({"minutes": 0}, "between 1 and 1440", id="zero"),
        pytest.param({"minutes": 1441}, "between 1 and 1440", id="over-a-day"),
        pytest.param({"minutes": "abc"}, "Invalid minutes", id="not-a-number"),
        pytest.param({}, None, id="missing"),
    ],
)
def test_update_device_cycle_rejects_a_bad_interval_and_keeps_the_old_one(
    client: FlaskClient, device_config_dev: Any, payload: Any, error: str | None
) -> None:
    assert client.put("/update_device_cycle", json={"minutes": 30}).status_code == 200

    resp = client.put("/update_device_cycle", json=payload)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    if error is not None:
        assert error in body["error"]
    assert _saved_device_cycle_seconds(device_config_dev) == 30 * 60


def test_update_device_cycle_wakes_the_refresh_loop(
    client: FlaskClient, flask_app: Flask
) -> None:
    signal = MagicMock()
    flask_app.config["REFRESH_TASK"].signal_config_change = signal

    assert client.put("/update_device_cycle", json={"minutes": 60}).status_code == 200
    signal.assert_called_once_with()


def test_update_device_cycle_is_saved_even_if_the_wake_up_fails(
    client: FlaskClient, flask_app: Flask, device_config_dev: Any
) -> None:
    def raise_error() -> None:
        raise RuntimeError("signal failed")

    flask_app.config["REFRESH_TASK"].signal_config_change = raise_error

    resp = client.put("/update_device_cycle", json={"minutes": 60})
    assert resp.status_code == 200
    assert _saved_device_cycle_seconds(device_config_dev) == 60 * 60


# ---- playlist time windows may not overlap ----


def _create(client: FlaskClient, name: str, start: str, end: str) -> Any:
    return client.post(
        "/create_playlist",
        json={"playlist_name": name, "start_time": start, "end_time": end},
    )


def test_create_playlist_refuses_an_overlapping_window(
    client: FlaskClient, device_config_dev: Any
) -> None:
    assert _create(client, "Morning", "06:00", "09:00").status_code == 200

    resp = _create(client, "Overlap", "08:00", "10:00")
    assert resp.status_code == 400
    assert "overlaps" in resp.get_json()["error"].lower()
    assert "Overlap" not in _saved_playlists(device_config_dev)


def test_create_playlist_accepts_separate_windows(
    client: FlaskClient, device_config_dev: Any
) -> None:
    assert _create(client, "Morning", "06:00", "09:00").status_code == 200
    assert _create(client, "Afternoon", "12:00", "15:00").status_code == 200

    saved = _saved_playlists(device_config_dev)
    assert (saved["Morning"]["start_time"], saved["Morning"]["end_time"]) == (
        "06:00",
        "09:00",
    )
    assert (saved["Afternoon"]["start_time"], saved["Afternoon"]["end_time"]) == (
        "12:00",
        "15:00",
    )


@pytest.mark.parametrize(
    ("start", "end"), [("22:00", "24:00"), ("22:00", "05:00")], ids=str
)
def test_create_playlist_saves_windows_that_reach_midnight(
    client: FlaskClient, device_config_dev: Any, start: str, end: str
) -> None:
    assert _create(client, "Night", start, end).status_code == 200
    saved = _saved_playlists(device_config_dev)["Night"]
    assert (saved["start_time"], saved["end_time"]) == (start, end)


def test_update_playlist_may_overlap_its_own_old_window(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _create(client, "First", "06:00", "09:00")
    _create(client, "Second", "12:00", "15:00")

    resp = client.put(
        "/update_playlist/First",
        json={"new_name": "First", "start_time": "05:00", "end_time": "10:00"},
    )
    assert resp.status_code == 200
    saved = _saved_playlists(device_config_dev)["First"]
    assert (saved["start_time"], saved["end_time"]) == ("05:00", "10:00")


def test_update_playlist_refuses_to_overlap_another(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _create(client, "First", "06:00", "09:00")
    _create(client, "Second", "12:00", "15:00")

    resp = client.put(
        "/update_playlist/First",
        json={"new_name": "First", "start_time": "11:00", "end_time": "13:00"},
    )
    assert resp.status_code == 400
    assert "overlaps" in resp.get_json()["error"].lower()
    saved = _saved_playlists(device_config_dev)["First"]
    assert (saved["start_time"], saved["end_time"]) == ("06:00", "09:00")


def test_update_playlist_rejects_a_body_that_is_not_json_or_a_form(
    client: FlaskClient,
) -> None:
    resp = client.put(
        "/update_playlist/Any", data="not-json", content_type="text/plain"
    )
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


# ---- /display_next_in_playlist ----


def test_display_next_in_playlist_needs_a_playlist_name(client: FlaskClient) -> None:
    resp = client.post("/display_next_in_playlist", json={})
    assert resp.status_code == 400
    assert "required" in resp.get_json()["error"].lower()


def test_display_next_in_playlist_unknown_playlist(client: FlaskClient) -> None:
    resp = client.post("/display_next_in_playlist", json={"playlist_name": "NoSuch"})
    assert resp.status_code == 400
    assert "not found" in resp.get_json()["error"].lower()


def test_display_next_in_playlist_with_nothing_to_show(
    client: FlaskClient, device_config_dev: Any
) -> None:
    device_config_dev.get_playlist_manager().add_playlist("Empty", "00:00", "24:00")
    device_config_dev.write_config()

    resp = client.post("/display_next_in_playlist", json={"playlist_name": "Empty"})
    assert resp.status_code == 400
    assert "no eligible" in resp.get_json()["error"].lower()


def test_display_next_in_playlist_refreshes_that_playlists_next_item(
    client: FlaskClient, flask_app: Flask, device_config_dev: Any
) -> None:
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Test", "00:00", "24:00")
    pm.get_playlist("Test").add_plugin(
        {
            "plugin_id": "clock",
            "name": "TestClock",
            "plugin_settings": {},
            "refresh": {"interval": 60},
        }
    )
    device_config_dev.write_config()
    manual_update = MagicMock(return_value={})
    flask_app.config["REFRESH_TASK"].manual_update = manual_update

    resp = client.post("/display_next_in_playlist", json={"playlist_name": "Test"})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    manual_update.assert_called_once()
    action = manual_update.call_args.args[0]
    assert action.get_refresh_info() == {
        "refresh_type": "Playlist",
        "playlist": "Test",
        "plugin_id": "clock",
        "plugin_instance": "TestClock",
    }


# ---- /add_plugin with a daily scheduled time ----


def test_add_plugin_saves_a_scheduled_refresh(
    client: FlaskClient, device_config_dev: Any
) -> None:
    payload = {
        "plugin_id": "clock",
        "refresh_settings": json.dumps(
            {
                "playlist": "Default",
                "instance_name": "ScheduledClock",
                "refreshType": "scheduled",
                "refreshTime": "08:00",
            }
        ),
    }
    resp = client.post("/add_plugin", data=payload)
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    default = _saved_playlists(device_config_dev)["Default"]
    instance = next(p for p in default["plugins"] if p["name"] == "ScheduledClock")
    assert instance["plugin_id"] == "clock"
    assert instance["refresh"] == {"scheduled": "08:00"}


# ---- /reorder_plugins failures leave the order alone ----


def test_reorder_plugins_unknown_playlist(client: FlaskClient) -> None:
    payload = {
        "playlist_name": "NoSuch",
        "ordered": [{"plugin_id": "clock", "name": "A"}],
    }
    resp = client.post("/reorder_plugins", json=payload)
    assert resp.status_code == 400
    assert "not found" in resp.get_json()["error"].lower()


def test_reorder_plugins_refuses_an_order_naming_other_instances(
    client: FlaskClient, device_config_dev: Any
) -> None:
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Test", "00:00", "24:00")
    for name in ("A", "B"):
        pm.get_playlist("Test").add_plugin(
            {
                "plugin_id": "clock",
                "name": name,
                "plugin_settings": {},
                "refresh": {"interval": 60},
            }
        )
    device_config_dev.write_config()

    payload = {
        "playlist_name": "Test",
        "ordered": [
            {"plugin_id": "clock", "name": "B"},
            {"plugin_id": "weather", "name": "C"},
        ],
    }
    resp = client.post("/reorder_plugins", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    saved = _saved_playlists(device_config_dev)["Test"]
    assert [p["name"] for p in saved["plugins"]] == ["A", "B"]


def test_reorder_plugins_needs_an_order(client: FlaskClient) -> None:
    resp = client.post("/reorder_plugins", json={"playlist_name": "Test"})
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


# ---- /playlist/eta ----


def test_playlist_eta_of_an_empty_playlist_is_empty(
    client: FlaskClient, device_config_dev: Any
) -> None:
    device_config_dev.get_playlist_manager().add_playlist("Empty", "00:00", "24:00")
    device_config_dev.write_config()

    resp = client.get("/playlist/eta/Empty")
    assert resp.status_code == 200
    assert resp.get_json()["eta"] == {}


def test_playlist_eta_is_stable_within_a_minute(
    client: FlaskClient, device_config_dev: Any
) -> None:
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Cached", "00:00", "24:00")
    pm.get_playlist("Cached").add_plugin(
        {
            "plugin_id": "clock",
            "name": "A",
            "plugin_settings": {},
            "refresh": {"interval": 60},
        }
    )
    device_config_dev.write_config()

    first = client.get("/playlist/eta/Cached").get_json()["eta"]
    second = client.get("/playlist/eta/Cached").get_json()["eta"]
    assert list(first) == ["A"]
    assert first == second


# ---- relative times on the playlist page ----


def test_format_relative_time_reads_a_naive_timestamp_as_utc() -> None:
    """Bug 13: a timestamp without a zone is UTC, not an error."""
    from blueprints.playlist._pages import format_relative_time

    naive = (datetime.now(UTC) - timedelta(minutes=30)).replace(tzinfo=None)
    assert format_relative_time(naive.isoformat()) == "30 minutes ago"


def test_format_relative_time_says_just_now_under_two_minutes() -> None:
    from blueprints.playlist._pages import format_relative_time

    now = datetime.now().astimezone()
    assert format_relative_time((now - timedelta(seconds=119)).isoformat()) == (
        "just now"
    )
    assert format_relative_time((now - timedelta(seconds=120)).isoformat()) == (
        "2 minutes ago"
    )
