# pyright: reportMissingImports=false
"""Comprehensive tests for playlist blueprint routes."""

import json
import threading
from datetime import UTC, datetime
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_playlist(client, name="TestPlaylist", start="08:00", end="12:00"):
    """Shortcut to create a playlist via the API and return the response."""
    return client.post(
        "/create_playlist",
        json={"playlist_name": name, "start_time": start, "end_time": end},
    )


def _add_plugin_to_playlist(
    client, playlist_name, instance_name="MyPlugin", plugin_id="weather"
):
    """Shortcut to add a plugin instance to a playlist via form data."""
    refresh_settings = json.dumps(
        {
            "playlist": playlist_name,
            "instance_name": instance_name,
            "refreshType": "interval",
            "unit": "minute",
            "interval": "10",
        }
    )
    return client.post(
        "/add_plugin",
        data={"plugin_id": plugin_id, "refresh_settings": refresh_settings},
    )


def test_safe_now_device_tz_falls_back_to_aware_utc(monkeypatch):
    import blueprints.playlist as playlist_mod

    class _FallbackDateTime:
        @staticmethod
        def now(tz=None):
            return datetime(2025, 1, 1, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(
        playlist_mod,
        "now_device_tz",
        lambda _cfg: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(playlist_mod, "datetime", _FallbackDateTime)

    current_dt = playlist_mod._safe_now_device_tz(object())

    assert current_dt == datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert current_dt.tzinfo is UTC


# ---------------------------------------------------------------------------
# /create_playlist (POST)
# ---------------------------------------------------------------------------


class TestCreatePlaylist:
    def test_success(self, client, device_config_dev):
        resp = _create_playlist(client, "Morning", "06:00", "10:00")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

        # Verify playlist was actually created
        pm = device_config_dev.get_playlist_manager()
        assert pm.get_playlist("Morning") is not None

    def test_missing_name(self, client):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": "", "start_time": "08:00", "end_time": "12:00"},
        )
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False

    def test_missing_name_key(self, client):
        resp = client.post(
            "/create_playlist",
            json={"start_time": "08:00", "end_time": "12:00"},
        )
        assert resp.status_code == 400

    def test_missing_times(self, client):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": "NoTimes"},
        )
        assert resp.status_code == 400
        assert "time" in resp.get_json()["error"].lower()

    def test_same_start_end(self, client):
        resp = _create_playlist(client, "Same", "10:00", "10:00")
        assert resp.status_code == 400
        assert "same" in resp.get_json()["error"].lower()

    def test_invalid_time_format(self, client):
        resp = _create_playlist(client, "Bad", "not-a-time", "12:00")
        assert resp.status_code == 400

    def test_duplicate_name(self, client):
        _create_playlist(client, "Dup", "06:00", "08:00")
        resp = _create_playlist(client, "Dup", "14:00", "16:00")
        assert resp.status_code == 400
        assert "already exists" in resp.get_json()["error"]

    def test_overlapping_windows(self, client):
        _create_playlist(client, "First", "08:00", "12:00")
        resp = _create_playlist(client, "Second", "10:00", "14:00")
        assert resp.status_code == 400
        assert "overlap" in resp.get_json()["error"].lower()

    def test_non_overlapping_windows(self, client):
        _create_playlist(client, "A", "08:00", "10:00")
        resp = _create_playlist(client, "B", "10:00", "12:00")
        assert resp.status_code == 200

    def test_form_data_fallback(self, client):
        resp = client.post(
            "/create_playlist",
            data={
                "playlist_name": "FormPL",
                "start_time": "13:00",
                "end_time": "15:00",
            },
        )
        assert resp.status_code == 200

    def test_unsupported_media_type(self, client):
        """POST with non-JSON content type and no form keys returns 415."""
        resp = client.post(
            "/create_playlist",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 415

    def test_whitespace_only_name(self, client):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": "   ", "start_time": "08:00", "end_time": "12:00"},
        )
        assert resp.status_code == 400

    def test_default_playlist_skipped_overlap_check(self, client, device_config_dev):
        """A Default playlist should not block overlap checks."""
        pm = device_config_dev.get_playlist_manager()
        pm.add_default_playlist()
        device_config_dev.write_config()
        # Default is 00:00-24:00 which covers everything, but should be skipped
        resp = _create_playlist(client, "Anytime", "08:00", "12:00")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /update_playlist/<name> (PUT)
# ---------------------------------------------------------------------------


class TestUpdatePlaylist:
    def test_success(self, client, device_config_dev):
        _create_playlist(client, "Old", "06:00", "10:00")
        resp = client.put(
            "/update_playlist/Old",
            json={"new_name": "New", "start_time": "07:00", "end_time": "11:00"},
        )
        assert resp.status_code == 200
        pm = device_config_dev.get_playlist_manager()
        assert pm.get_playlist("New") is not None
        assert pm.get_playlist("Old") is None

    def test_nonexistent_playlist(self, client):
        resp = client.put(
            "/update_playlist/DoesNotExist",
            json={"new_name": "X", "start_time": "06:00", "end_time": "10:00"},
        )
        assert resp.status_code == 400
        assert "does not exist" in resp.get_json()["error"]

    def test_missing_fields(self, client):
        _create_playlist(client, "Exists", "06:00", "10:00")
        resp = client.put(
            "/update_playlist/Exists",
            json={"new_name": "Updated"},
        )
        assert resp.status_code == 400

    def test_invalid_json(self, client):
        resp = client.put(
            "/update_playlist/X",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_same_start_end(self, client):
        _create_playlist(client, "ToUpdate", "06:00", "10:00")
        resp = client.put(
            "/update_playlist/ToUpdate",
            json={"new_name": "ToUpdate", "start_time": "08:00", "end_time": "08:00"},
        )
        assert resp.status_code == 400
        assert "same" in resp.get_json()["error"].lower()

    def test_invalid_time_format(self, client):
        _create_playlist(client, "ToUpdate2", "06:00", "10:00")
        resp = client.put(
            "/update_playlist/ToUpdate2",
            json={"new_name": "ToUpdate2", "start_time": "bad", "end_time": "10:00"},
        )
        assert resp.status_code == 400

    def test_overlap_with_other_playlist(self, client):
        _create_playlist(client, "Existing", "08:00", "12:00")
        _create_playlist(client, "Target", "14:00", "16:00")
        resp = client.put(
            "/update_playlist/Target",
            json={"new_name": "Target", "start_time": "09:00", "end_time": "11:00"},
        )
        assert resp.status_code == 400
        assert "overlap" in resp.get_json()["error"].lower()

    def test_cycle_minutes_override(self, client, device_config_dev):
        _create_playlist(client, "Cycled", "06:00", "10:00")
        resp = client.put(
            "/update_playlist/Cycled",
            json={
                "new_name": "Cycled",
                "start_time": "06:00",
                "end_time": "10:00",
                "cycle_minutes": 15,
            },
        )
        assert resp.status_code == 200
        pm = device_config_dev.get_playlist_manager()
        pl = pm.get_playlist("Cycled")
        assert pl.cycle_interval_seconds == 15 * 60


# ---------------------------------------------------------------------------
# /delete_playlist/<name> (DELETE)
# ---------------------------------------------------------------------------


class TestDeletePlaylist:
    def test_success(self, client, device_config_dev):
        _create_playlist(client, "ToDelete", "08:00", "12:00")
        resp = client.delete("/delete_playlist/ToDelete")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        pm = device_config_dev.get_playlist_manager()
        assert pm.get_playlist("ToDelete") is None

    def test_nonexistent(self, client):
        resp = client.delete("/delete_playlist/Ghost")
        assert resp.status_code == 400
        assert "does not exist" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# /update_device_cycle (PUT)
# ---------------------------------------------------------------------------


class TestUpdateDeviceCycle:
    def test_valid_minutes(self, client, device_config_dev):
        resp = client.put("/update_device_cycle", json={"minutes": 30})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        val = device_config_dev.get_config("plugin_cycle_interval_seconds")
        assert val == 30 * 60

    def test_minimum_boundary(self, client):
        resp = client.put("/update_device_cycle", json={"minutes": 1})
        assert resp.status_code == 200

    def test_maximum_boundary(self, client):
        resp = client.put("/update_device_cycle", json={"minutes": 1440})
        assert resp.status_code == 200

    def test_below_minimum(self, client):
        resp = client.put("/update_device_cycle", json={"minutes": 0})
        assert resp.status_code == 400

    def test_above_maximum(self, client):
        resp = client.put("/update_device_cycle", json={"minutes": 1441})
        assert resp.status_code == 400

    def test_invalid_type(self, client):
        resp = client.put("/update_device_cycle", json={"minutes": "abc"})
        assert resp.status_code == 400

    def test_missing_minutes(self, client):
        resp = client.put("/update_device_cycle", json={})
        assert resp.status_code == 400

    def test_no_json_body(self, client):
        resp = client.put("/update_device_cycle")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /reorder_plugins (POST)
# ---------------------------------------------------------------------------


class TestReorderPlugins:
    def test_success(self, client, device_config_dev):
        _create_playlist(client, "Reorder", "08:00", "12:00")
        _add_plugin_to_playlist(client, "Reorder", "PlugA", "weather")
        _add_plugin_to_playlist(client, "Reorder", "PlugB", "weather")

        pm = device_config_dev.get_playlist_manager()
        pl = pm.get_playlist("Reorder")
        assert len(pl.plugins) == 2

        # Reverse order
        resp = client.post(
            "/reorder_plugins",
            json={
                "playlist_name": "Reorder",
                "ordered": [
                    {"plugin_id": "weather", "name": "PlugB"},
                    {"plugin_id": "weather", "name": "PlugA"},
                ],
            },
        )
        assert resp.status_code == 200

    def test_missing_playlist_name(self, client):
        resp = client.post(
            "/reorder_plugins",
            json={"ordered": []},
        )
        assert resp.status_code == 400

    def test_missing_ordered_list(self, client, device_config_dev):
        _create_playlist(client, "ReorderMissing", "08:00", "12:00")
        resp = client.post(
            "/reorder_plugins",
            json={"playlist_name": "ReorderMissing"},
        )
        assert resp.status_code == 400

    def test_nonexistent_playlist(self, client):
        resp = client.post(
            "/reorder_plugins",
            json={"playlist_name": "NoSuch", "ordered": []},
        )
        assert resp.status_code == 400

    def test_invalid_order_payload(self, client, device_config_dev):
        _create_playlist(client, "ReorderBad", "08:00", "12:00")
        _add_plugin_to_playlist(client, "ReorderBad", "OnlyPlug", "weather")
        # Wrong count -- 0 items when 1 expected
        resp = client.post(
            "/reorder_plugins",
            json={"playlist_name": "ReorderBad", "ordered": []},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /add_plugin (POST)
# ---------------------------------------------------------------------------


class TestAddPlugin:
    def test_success_interval(self, client, device_config_dev):
        _create_playlist(client, "AddPlug", "08:00", "12:00")
        resp = _add_plugin_to_playlist(client, "AddPlug", "Weather1", "weather")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_missing_playlist(self, client):
        refresh_settings = json.dumps(
            {
                "playlist": "",
                "instance_name": "Inst",
                "refreshType": "interval",
                "unit": "minute",
                "interval": "5",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["details"]["field"] == "playlist"

    def test_missing_instance_name(self, client, device_config_dev):
        _create_playlist(client, "NoInst", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "NoInst",
                "instance_name": "",
                "refreshType": "interval",
                "unit": "minute",
                "interval": "5",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422
        assert resp.get_json()["details"]["field"] == "instance_name"

    def test_instance_name_too_long(self, client, device_config_dev):
        _create_playlist(client, "LongName", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "LongName",
                "instance_name": "A" * 65,
                "refreshType": "interval",
                "unit": "minute",
                "interval": "5",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422
        assert "64" in resp.get_json()["error"]

    def test_instance_name_invalid_chars(self, client, device_config_dev):
        _create_playlist(client, "BadChars", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "BadChars",
                "instance_name": "Bad@Name!",
                "refreshType": "interval",
                "unit": "minute",
                "interval": "5",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422
        assert (
            "letters, numbers, spaces, underscores, and hyphens"
            in resp.get_json()["error"]
        )

    def test_missing_refresh_type(self, client, device_config_dev):
        _create_playlist(client, "NoRefType", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "NoRefType",
                "instance_name": "Inst",
                "refreshType": "",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422
        assert resp.get_json()["details"]["field"] == "refreshType"

    def test_invalid_refresh_type(self, client, device_config_dev):
        _create_playlist(client, "BadRefType", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "BadRefType",
                "instance_name": "Inst",
                "refreshType": "once",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422

    def test_duplicate_instance(self, client, device_config_dev):
        _create_playlist(client, "DupInst", "08:00", "12:00")
        _add_plugin_to_playlist(client, "DupInst", "Same", "weather")
        resp = _add_plugin_to_playlist(client, "DupInst", "Same", "weather")
        assert resp.status_code == 400
        assert "already exists" in resp.get_json()["error"]

    def test_missing_interval_unit(self, client, device_config_dev):
        _create_playlist(client, "NoUnit", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "NoUnit",
                "instance_name": "Inst",
                "refreshType": "interval",
                "unit": "",
                "interval": "5",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422
        assert resp.get_json()["details"]["field"] == "unit"

    def test_invalid_interval_unit(self, client, device_config_dev):
        _create_playlist(client, "BadUnit", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "BadUnit",
                "instance_name": "Inst",
                "refreshType": "interval",
                "unit": "week",
                "interval": "5",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422

    def test_missing_interval_value(self, client, device_config_dev):
        _create_playlist(client, "NoIntVal", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "NoIntVal",
                "instance_name": "Inst",
                "refreshType": "interval",
                "unit": "minute",
                "interval": "",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422

    def test_non_numeric_interval(self, client, device_config_dev):
        _create_playlist(client, "NaN", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "NaN",
                "instance_name": "Inst",
                "refreshType": "interval",
                "unit": "minute",
                "interval": "abc",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422
        assert "number" in resp.get_json()["error"].lower()

    def test_interval_out_of_range(self, client, device_config_dev):
        _create_playlist(client, "OOR", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "OOR",
                "instance_name": "Inst",
                "refreshType": "interval",
                "unit": "minute",
                "interval": "1000",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422

    def test_scheduled_success(self, client, device_config_dev):
        _create_playlist(client, "Sched", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "Sched",
                "instance_name": "SchedInst",
                "refreshType": "scheduled",
                "refreshTime": "09:00",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 200

    def test_scheduled_missing_time(self, client, device_config_dev):
        _create_playlist(client, "SchedNoTime", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "SchedNoTime",
                "instance_name": "Inst",
                "refreshType": "scheduled",
                "refreshTime": "",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": refresh_settings},
        )
        assert resp.status_code == 422
        assert resp.get_json()["details"]["field"] == "refreshTime"


# ---------------------------------------------------------------------------
# JTN-451: add_plugin must validate settings (URL scheme bypass)
# ---------------------------------------------------------------------------


class TestAddPluginSettingsValidation:
    """JTN-451: add_plugin must call plugin-specific validate_settings
    to block unsafe values (e.g. javascript: URLs in the Screenshot plugin)."""

    def test_screenshot_javascript_url_rejected(self, client, device_config_dev):
        _create_playlist(client, "SecTest", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "SecTest",
                "instance_name": "SShot1",
                "refreshType": "interval",
                "unit": "minute",
                "interval": "10",
            }
        )
        resp = client.post(
            "/add_plugin",
            data={
                "plugin_id": "screenshot",
                "url": "javascript:alert(1)",
                "refresh_settings": refresh_settings,
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "URL" in data.get("error", "") or "scheme" in data.get("error", "").lower()

    def test_screenshot_file_url_rejected(self, client, device_config_dev):
        _create_playlist(client, "SecTest2", "08:00", "12:00")
        refresh_settings = json.dumps(
            {
                "playlist": "SecTest2",
                "instance_name": "SShot2",
                "refreshType": "interval",
                "unit": "minute",
                "interval": "10",
            },
        )
        resp = client.post(
            "/add_plugin",
            data={
                "plugin_id": "screenshot",
                "url": "file:///etc/passwd",
                "refresh_settings": refresh_settings,
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "URL" in data.get("error", "") or "scheme" in data.get("error", "").lower()


# ---------------------------------------------------------------------------
# /display_next_in_playlist (POST)
# ---------------------------------------------------------------------------


class TestDisplayNextInPlaylist:
    def test_missing_playlist_name(self, client):
        resp = client.post(
            "/display_next_in_playlist",
            json={"playlist_name": ""},
        )
        assert resp.status_code == 400

    def test_nonexistent_playlist(self, client):
        resp = client.post(
            "/display_next_in_playlist",
            json={"playlist_name": "Ghost"},
        )
        assert resp.status_code == 400
        assert "not found" in resp.get_json()["error"]

    def test_no_eligible_plugin(self, client, device_config_dev):
        _create_playlist(client, "Empty", "08:00", "12:00")
        resp = client.post(
            "/display_next_in_playlist",
            json={"playlist_name": "Empty"},
        )
        assert resp.status_code == 400
        assert "eligible" in resp.get_json()["error"].lower()

    def test_success(self, client, device_config_dev):
        _create_playlist(client, "Next", "00:00", "24:00")
        _add_plugin_to_playlist(client, "Next", "Inst1", "weather")

        refresh_task = client.application.config["REFRESH_TASK"]
        with patch.object(refresh_task, "manual_update") as mock_update:
            resp = client.post(
                "/display_next_in_playlist",
                json={"playlist_name": "Next"},
            )
            assert resp.status_code == 200
            assert resp.get_json()["success"] is True
            assert mock_update.called


# ---------------------------------------------------------------------------
# /playlist (GET) - playlist page render
# ---------------------------------------------------------------------------


class TestPlaylistPage:
    def test_renders(self, client, device_config_dev):
        resp = client.get("/playlist")
        assert resp.status_code == 200
        assert b"html" in resp.data.lower() or b"<!doctype" in resp.data.lower()

    def test_uses_singular_labels_for_single_playlist_and_item(
        self, client, device_config_dev
    ):
        device_config = client.application.config["DEVICE_CONFIG"]
        playlist_manager = device_config.get_playlist_manager()
        playlist_manager.delete_playlist("Default")
        playlist_manager.add_playlist("Solo", "00:00", "24:00")
        playlist_manager.add_plugin_to_playlist(
            "Solo",
            {
                "plugin_id": "ai_text",
                "name": "Only Item",
                "plugin_settings": {"title": "T"},
                "refresh": {"interval": 60},
            },
        )
        device_config.write_config()

        resp = client.get("/playlist")

        assert resp.status_code == 200
        normalized_html = " ".join(resp.get_data(as_text=True).split())
        assert "1 playlist" in normalized_html
        assert "1 item" in normalized_html
        assert "1 playlists" not in normalized_html
        assert "1 items" not in normalized_html


# ---------------------------------------------------------------------------
# /playlist/eta/<name> (GET) - ETA endpoint
# ---------------------------------------------------------------------------


class TestPlaylistEta:
    def test_nonexistent_playlist(self, client):
        resp = client.get("/playlist/eta/NoSuch")
        assert resp.status_code == 404

    def test_empty_playlist_eta(self, client, device_config_dev):
        _create_playlist(client, "EtaPL", "08:00", "12:00")
        resp = client.get("/playlist/eta/EtaPL")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_with_plugins(self, client, device_config_dev):
        _create_playlist(client, "EtaFull", "00:00", "24:00")
        _add_plugin_to_playlist(client, "EtaFull", "E1", "weather")
        _add_plugin_to_playlist(client, "EtaFull", "E2", "weather")
        resp = client.get("/playlist/eta/EtaFull")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "eta" in data


# ---------------------------------------------------------------------------
# Playlist name validation
# ---------------------------------------------------------------------------


class TestPlaylistNameValidation:
    def test_create_playlist_name_too_long(self, client):
        """Playlist name exceeding 64 characters should be rejected with field attribution."""
        resp = _create_playlist(client, "A" * 65, "08:00", "12:00")
        assert resp.status_code == 400
        data = resp.get_json()
        # Validator messages are safe static strings, so they are preserved
        # (JTN-658) alongside the field attribution for frontend highlighting.
        assert "64 characters" in data["error"]
        assert data["details"]["field"] == "playlist_name"
        assert data["code"] == "validation_error"

    def test_create_playlist_name_special_chars(self, client):
        """Playlist names containing script tags or path traversal should be rejected."""
        resp = _create_playlist(client, "<script>alert(1)</script>", "08:00", "12:00")
        assert resp.status_code == 400
        data = resp.get_json()
        # Never reflect the raw input back; message is a static sanitised string.
        assert "<script>" not in data["error"]
        assert "only contain" in data["error"]
        assert data["details"]["field"] == "playlist_name"

        resp = _create_playlist(client, "../etc/passwd", "08:00", "12:00")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "../" not in data["error"]
        assert data["details"]["field"] == "playlist_name"

    def test_create_playlist_name_valid_unicode(self, client, device_config_dev):
        r"""Unicode word characters (accented letters matched by \w) should be accepted."""
        resp = _create_playlist(client, "Météo", "08:00", "12:00")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_create_playlist_name_with_spaces(self, client, device_config_dev):
        """Playlist names with spaces should be accepted."""
        resp = _create_playlist(client, "My Playlist", "08:00", "12:00")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ---------------------------------------------------------------------------
# Field-level error attribution (JTN-658)
# ---------------------------------------------------------------------------


class TestValidatorFieldAttribution:
    """Every validator in playlist.py must return ``details.field`` so the
    frontend can highlight the offending input (JTN-658)."""

    def _assert_field(self, resp, field, *, status=400):
        assert resp.status_code == status, resp.get_json()
        data = resp.get_json()
        assert data["success"] is False
        assert data.get("code") == "validation_error", data
        assert data.get("details", {}).get("field") == field, data

    # --- playlist name (create + update) ---

    def test_create_missing_name(self, client):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": "", "start_time": "08:00", "end_time": "12:00"},
        )
        self._assert_field(resp, "playlist_name")

    def test_create_whitespace_name(self, client):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": "   ", "start_time": "08:00", "end_time": "12:00"},
        )
        self._assert_field(resp, "playlist_name")

    def test_create_duplicate_name(self, client):
        _create_playlist(client, "Dup", "06:00", "08:00")
        resp = _create_playlist(client, "Dup", "14:00", "16:00")
        self._assert_field(resp, "playlist_name")

    def test_update_name_invalid(self, client):
        _create_playlist(client, "ToUpd", "06:00", "10:00")
        resp = client.put(
            "/update_playlist/ToUpd",
            json={"new_name": "", "start_time": "06:00", "end_time": "10:00"},
        )
        self._assert_field(resp, "new_name")

    def test_update_nonexistent_playlist(self, client):
        resp = client.put(
            "/update_playlist/Nope",
            json={"new_name": "X", "start_time": "06:00", "end_time": "10:00"},
        )
        self._assert_field(resp, "playlist_name")

    # --- time range ---

    def test_missing_start_time(self, client):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": "T", "start_time": "", "end_time": "12:00"},
        )
        self._assert_field(resp, "start_time")

    def test_missing_end_time(self, client):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": "T", "start_time": "08:00", "end_time": ""},
        )
        self._assert_field(resp, "end_time")

    def test_invalid_start_time_format(self, client):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": "T", "start_time": "bogus", "end_time": "12:00"},
        )
        self._assert_field(resp, "start_time")

    def test_invalid_end_time_format(self, client):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": "T", "start_time": "08:00", "end_time": "bogus"},
        )
        self._assert_field(resp, "end_time")

    def test_same_start_end(self, client):
        resp = _create_playlist(client, "Same", "10:00", "10:00")
        self._assert_field(resp, "end_time")

    def test_overlapping_windows(self, client):
        _create_playlist(client, "First", "08:00", "12:00")
        resp = _create_playlist(client, "Second", "10:00", "14:00")
        self._assert_field(resp, "start_time")

    def test_update_missing_time(self, client):
        _create_playlist(client, "UpdT", "06:00", "10:00")
        resp = client.put(
            "/update_playlist/UpdT",
            json={"new_name": "UpdT", "start_time": "", "end_time": "10:00"},
        )
        self._assert_field(resp, "start_time")

    # --- cycle minutes ---

    def test_cycle_minutes_non_integer(self, client):
        _create_playlist(client, "Cyc", "06:00", "10:00")
        resp = client.put(
            "/update_playlist/Cyc",
            json={
                "new_name": "Cyc",
                "start_time": "06:00",
                "end_time": "10:00",
                "cycle_minutes": "abc",
            },
        )
        self._assert_field(resp, "cycle_minutes")

    def test_cycle_minutes_out_of_range(self, client):
        _create_playlist(client, "Cyc2", "06:00", "10:00")
        resp = client.put(
            "/update_playlist/Cyc2",
            json={
                "new_name": "Cyc2",
                "start_time": "06:00",
                "end_time": "10:00",
                "cycle_minutes": 99999,
            },
        )
        self._assert_field(resp, "cycle_minutes")

    # --- delete ---

    def test_delete_nonexistent(self, client):
        resp = client.delete("/delete_playlist/Ghost")
        self._assert_field(resp, "playlist_name")

    # --- device cycle ---

    def test_device_cycle_out_of_range(self, client):
        resp = client.put("/update_device_cycle", json={"minutes": 0})
        self._assert_field(resp, "minutes")

    def test_device_cycle_invalid_type(self, client):
        resp = client.put("/update_device_cycle", json={"minutes": "abc"})
        self._assert_field(resp, "minutes")

    # --- reorder ---

    def test_reorder_missing_name(self, client):
        resp = client.post(
            "/reorder_plugins",
            json={"ordered": []},
        )
        self._assert_field(resp, "playlist_name")

    def test_reorder_missing_ordered(self, client):
        resp = client.post(
            "/reorder_plugins",
            json={"playlist_name": "X"},
        )
        self._assert_field(resp, "ordered")

    def test_reorder_playlist_not_found(self, client):
        resp = client.post(
            "/reorder_plugins",
            json={"playlist_name": "Ghost", "ordered": []},
        )
        self._assert_field(resp, "playlist_name")

    # --- display next ---

    def test_display_next_missing_name(self, client):
        resp = client.post("/display_next_in_playlist", json={})
        self._assert_field(resp, "playlist_name")

    def test_display_next_not_found(self, client):
        resp = client.post("/display_next_in_playlist", json={"playlist_name": "Ghost"})
        self._assert_field(resp, "playlist_name")

    # --- ETA ---

    def test_eta_not_found(self, client):
        resp = client.get("/playlist/eta/Ghost")
        self._assert_field(resp, "playlist_name", status=404)

    # --- add_plugin ---

    def test_add_plugin_missing_refresh(self, client):
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather"},
        )
        self._assert_field(resp, "refresh_settings")

    def test_add_plugin_invalid_refresh_json(self, client):
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather", "refresh_settings": "not-json"},
        )
        self._assert_field(resp, "refresh_settings")

    def test_add_plugin_missing_instance(self, client):
        _create_playlist(client, "APIPlaylist", "08:00", "12:00")
        resp = client.post(
            "/add_plugin",
            data={
                "plugin_id": "weather",
                "refresh_settings": json.dumps(
                    {
                        "playlist": "APIPlaylist",
                        "instance_name": "",
                        "refreshType": "interval",
                        "unit": "minute",
                        "interval": "10",
                    }
                ),
            },
        )
        self._assert_field(resp, "instance_name", status=422)

    def test_add_plugin_duplicate_instance(self, client):
        _create_playlist(client, "Dup2", "08:00", "12:00")
        _add_plugin_to_playlist(client, "Dup2", "Same", "weather")
        resp = _add_plugin_to_playlist(client, "Dup2", "Same", "weather")
        self._assert_field(resp, "instance_name")


# ---------------------------------------------------------------------------
# ETA cache thread safety (JTN-69)
# ---------------------------------------------------------------------------


class TestEtaCacheThreadSafety:
    def test_concurrent_eta_requests_no_crash(self, client, device_config_dev):
        """Concurrent ETA requests must not raise RuntimeError from dict mutation."""
        _create_playlist(client, "Conc", "00:00", "24:00")
        _add_plugin_to_playlist(client, "Conc", "P1", "weather")
        _add_plugin_to_playlist(client, "Conc", "P2", "weather")

        errors: list[Exception] = []
        barrier = threading.Barrier(4, timeout=5)

        def _hit_eta():
            try:
                barrier.wait()
                for _ in range(10):
                    resp = client.get("/playlist/eta/Conc")
                    assert resp.status_code == 200
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_hit_eta) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Concurrent ETA requests raised: {errors}"

    def test_eta_cache_lock_exists(self):
        """Verify the lock is present at module level."""
        import blueprints.playlist as pl_mod

        assert hasattr(pl_mod, "_eta_cache_lock")
        assert isinstance(pl_mod._eta_cache_lock, type(threading.Lock()))


# ---------------------------------------------------------------------------
# _default_overlap_warning helper tests
# ---------------------------------------------------------------------------


class TestDefaultOverlapWarning:
    def test_returns_warning_when_overlapping_default(self):
        from blueprints.playlist import _default_overlap_warning
        from model import Playlist

        playlists = [Playlist("Default", "00:00", "24:00")]
        from blueprints.playlist import _to_minutes

        result = _default_overlap_warning(
            _to_minutes("09:00"), _to_minutes("17:00"), playlists
        )
        assert result is not None
        assert "Default" in result
        assert "priority" in result

    def test_returns_none_when_no_default(self):
        from blueprints.playlist import _default_overlap_warning, _to_minutes
        from model import Playlist

        playlists = [Playlist("Work", "09:00", "17:00")]
        result = _default_overlap_warning(
            _to_minutes("06:00"), _to_minutes("08:00"), playlists
        )
        assert result is None

    def test_returns_none_when_no_overlap(self):
        from blueprints.playlist import _default_overlap_warning, _to_minutes
        from model import Playlist

        playlists = [Playlist("Default", "09:00", "17:00")]
        result = _default_overlap_warning(
            _to_minutes("18:00"), _to_minutes("20:00"), playlists
        )
        assert result is None
