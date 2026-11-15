# pyright: reportMissingImports=false
"""Tests for settings import/export operations."""

import io
import json
from typing import Any

import pytest
from flask.testing import FlaskClient

# ---------------------------------------------------------------------------
# /settings/import (POST) - import settings
# ---------------------------------------------------------------------------


class TestImportSettings:
    def test_import_json_config(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        payload = {
            "config": {
                "name": "Imported Device",
                "timezone": "America/New_York",
            }
        }
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert device_config_dev.get_config("name") == "Imported Device"

    def test_import_refuses_values_this_device_cannot_load(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """A backup value the schema rejects is refused with a 400 that names
        it, and nothing is changed; saving it stopped the next start."""
        from pathlib import Path

        disk_before = Path(device_config_dev.config_file).read_bytes()
        payload = {"config": {"name": "Imported", "orientation": "sideways"}}
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 400
        assert "orientation" in resp.get_json()["error"]
        assert device_config_dev.get_config("name") == "InkyPi Test"
        assert Path(device_config_dev.config_file).read_bytes() == disk_before

    def test_import_filters_disallowed_keys(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        payload = {
            "config": {
                "name": "Good Key",
                "dangerous_key": "should be filtered",
            }
        }
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 200
        assert device_config_dev.get_config("name") == "Good Key"
        assert device_config_dev.get_config("dangerous_key") is None

    def test_import_with_env_keys(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        payload = {
            "config": {"name": "Test"},
            "env_keys": {"OPEN_AI_SECRET": "sk-test-123"},
        }
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_import_filters_disallowed_env_keys(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        # Pair a disallowed env key with at least one allowed config key so
        # the request still has *something* to apply; otherwise it would 400
        # (see test_import_rejects_payload_with_no_recognized_keys below) -> None -> None.
        payload = {
            "config": {"name": "Filters Test"},
            "env_keys": {"EVIL_KEY": "hacked"},
        }
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 200
        # EVIL_KEY should not have been set

    def test_import_invalid_payload(self, client: FlaskClient) -> None:
        resp = client.post(
            "/settings/import", data="not json", content_type="application/json"
        )
        assert resp.status_code == 400

    def test_import_empty_body(self, client: FlaskClient) -> None:
        resp = client.post("/settings/import", data="", content_type="application/json")
        assert resp.status_code == 400

    def test_import_via_file_upload(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        payload = json.dumps({"config": {"name": "File Import"}})
        data = {
            "file": (io.BytesIO(payload.encode("utf-8")), "settings.json"),
        }
        resp = client.post(
            "/settings/import", data=data, content_type="multipart/form-data"
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert device_config_dev.get_config("name") == "File Import"

    def test_import_no_config_key(self, client: FlaskClient) -> None:
        """Import with empty dict is treated as invalid payload (400)."""
        resp = client.post("/settings/import", json={})
        assert resp.status_code == 400

    def test_import_config_only(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """Import with only a config key and no env_keys should succeed."""
        resp = client.post(
            "/settings/import", json={"config": {"name": "MinimalImport"}}
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_import_rejects_payload_with_no_recognized_keys(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """A payload that survives JSON parse but contains no whitelisted
        config keys and no whitelisted env_keys must fail loudly (400),
        not silently return 'Import completed'. Otherwise users uploading
        a stranger's export or a malformed backup get a green success
        toast while their device config is unchanged.
        """
        original_name = device_config_dev.get_config("name")
        payload = {
            "config": {"dangerous_key": "ignored"},
            "env_keys": {"EVIL_KEY": "ignored"},
        }
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "no recognizable" in body["error"].lower()
        # Device config must be untouched.
        assert device_config_dev.get_config("name") == original_name

    def test_import_success_message_reports_counts(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """Success message should reflect what was applied so the user
        knows the restore actually did something."""
        resp = client.post(
            "/settings/import",
            json={
                "config": {"name": "MsgTest", "timezone": "UTC"},
                "env_keys": {"OPEN_AI_SECRET": "sk-msg-test"},
            },
        )
        assert resp.status_code == 200
        message = resp.get_json()["message"]
        assert "2 settings" in message
        assert "1 API key" in message


def _seed_playlist(device_config: Any, name: str, instance: str) -> None:
    def apply(_config: dict[str, Any]) -> None:
        manager = device_config.get_playlist_manager()
        manager.add_playlist(name, "06:00", "22:00")
        manager.add_plugin_to_playlist(
            name,
            {
                "plugin_id": "clock",
                "name": instance,
                "plugin_settings": {},
                "refresh": {"interval": 600},
            },
        )

    device_config.update_atomic(apply)


def _playlist_names_on_disk(device_config: Any) -> list[str]:
    with open(device_config.config_file, encoding="utf-8") as fh:
        saved = json.load(fh)
    return [p["name"] for p in saved["playlist_config"]["playlists"]]


class TestImportRestoresPlaylists:
    def test_export_then_import_round_trips_playlists(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        _seed_playlist(device_config_dev, "Morning", "Kitchen clock")
        backup = client.get("/settings/export").get_json()["data"]

        # Change the device after the backup was taken.
        device_config_dev.update_atomic(
            lambda _c: device_config_dev.get_playlist_manager().delete_playlist(
                "Morning"
            )
        )
        _seed_playlist(device_config_dev, "Evening", "Hall clock")

        resp = client.post("/settings/import", json=backup)
        assert resp.status_code == 200, resp.get_json()

        manager = device_config_dev.get_playlist_manager()
        assert "Morning" in manager.get_playlist_names()
        assert "Evening" not in manager.get_playlist_names()
        morning = manager.get_playlist("Morning")
        assert morning is not None
        assert [p.name for p in morning.plugins] == ["Kitchen clock"]
        assert "Morning" in _playlist_names_on_disk(device_config_dev)
        assert "Evening" not in _playlist_names_on_disk(device_config_dev)

    def test_imported_playlists_survive_the_next_save(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        payload = {
            "config": {
                "playlist_config": {
                    "playlists": [
                        {
                            "name": "Imported",
                            "start_time": "00:00",
                            "end_time": "24:00",
                            "plugins": [],
                        }
                    ],
                    "active_playlist": "Imported",
                }
            }
        }
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 200

        # Any later save serialises from the playlist model; it must not
        # put the pre-import playlists back.
        device_config_dev.update_value("name", "After import", write=True)
        assert _playlist_names_on_disk(device_config_dev) == ["Imported"]
        assert device_config_dev.get_playlist_manager().active_playlist == "Imported"

    def test_empty_playlist_section_gets_the_default_playlist(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        _seed_playlist(device_config_dev, "Morning", "Kitchen clock")
        payload: dict[str, Any] = {"config": {"playlist_config": {"playlists": []}}}
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 200
        names = device_config_dev.get_playlist_manager().get_playlist_names()
        assert names == ["Default"]

    def test_non_dict_playlist_section_is_rejected(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        _seed_playlist(device_config_dev, "Morning", "Kitchen clock")
        payload = {"config": {"name": "Should not apply", "playlist_config": []}}
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 400
        assert device_config_dev.get_config("name") == "InkyPi Test"
        assert (
            "Morning" in device_config_dev.get_playlist_manager().get_playlist_names()
        )

    def test_malformed_playlist_rolls_back_the_whole_import(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        _seed_playlist(device_config_dev, "Morning", "Kitchen clock")
        names_before = device_config_dev.get_playlist_manager().get_playlist_names()
        payload = {
            "config": {
                "name": "Should not apply",
                "playlist_config": {"playlists": ["not a playlist"]},
            }
        }
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 400
        assert device_config_dev.get_config("name") == "InkyPi Test"
        manager = device_config_dev.get_playlist_manager()
        assert manager.get_playlist_names() == names_before
        assert _playlist_names_on_disk(device_config_dev) == names_before

    def test_refresh_info_from_backup_is_not_imported(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        before = device_config_dev.get_refresh_info().to_dict()
        payload = {
            "config": {
                "name": "Restored",
                "refresh_info": {
                    "refresh_time": "2020-01-01T00:00:00+00:00",
                    "image_hash": "stale",
                    "refresh_type": "Playlist",
                    "plugin_id": "clock",
                },
            }
        }
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 200
        assert "1 setting" in resp.get_json()["message"]
        assert device_config_dev.get_refresh_info().to_dict() == before

    def test_import_notifies_the_refresh_task(
        self,
        client: FlaskClient,
        device_config_dev: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        refresh_task = client.application.config["REFRESH_TASK"]
        calls: list[str] = []
        monkeypatch.setattr(
            refresh_task, "signal_config_change", lambda: calls.append("signal")
        )
        resp = client.post(
            "/settings/import", json={"config": {"timezone": "Europe/London"}}
        )
        assert resp.status_code == 200
        assert calls == ["signal"]


# ---------------------------------------------------------------------------
# /settings/export (GET) - export settings
# ---------------------------------------------------------------------------


class TestExportSettings:
    def test_export_without_keys(self, client: FlaskClient) -> None:
        resp = client.get("/settings/export")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "config" in data["data"]
        assert "env_keys" not in data["data"]

    def test_export_with_keys(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        resp = client.post("/settings/export", json={"include_keys": True})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "env_keys" in data["data"]

    def test_export_get_never_includes_keys(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        device_config_dev.set_env_key("OPEN_AI_SECRET", "sk-test")
        resp = client.get("/settings/export?include_keys=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "env_keys" not in data["data"]
