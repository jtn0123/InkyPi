# pyright: reportMissingImports=false
"""Tests for settings import/export operations."""

import io
import json

# ---------------------------------------------------------------------------
# /settings/import (POST) - import settings
# ---------------------------------------------------------------------------


class TestImportSettings:
    def test_import_json_config(self, client, device_config_dev):
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

    def test_import_filters_disallowed_keys(self, client, device_config_dev):
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

    def test_import_with_env_keys(self, client, device_config_dev):
        payload = {
            "config": {"name": "Test"},
            "env_keys": {"OPEN_AI_SECRET": "sk-test-123"},
        }
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_import_filters_disallowed_env_keys(self, client, device_config_dev):
        # Pair a disallowed env key with at least one allowed config key so
        # the request still has *something* to apply; otherwise it would 400
        # (see test_import_rejects_payload_with_no_recognized_keys below).
        payload = {
            "config": {"name": "Filters Test"},
            "env_keys": {"EVIL_KEY": "hacked"},
        }
        resp = client.post("/settings/import", json=payload)
        assert resp.status_code == 200
        # EVIL_KEY should not have been set

    def test_import_invalid_payload(self, client):
        resp = client.post(
            "/settings/import", data="not json", content_type="application/json"
        )
        assert resp.status_code == 400

    def test_import_empty_body(self, client):
        resp = client.post("/settings/import", data="", content_type="application/json")
        assert resp.status_code == 400

    def test_import_via_file_upload(self, client, device_config_dev):
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

    def test_import_no_config_key(self, client):
        """Import with empty dict is treated as invalid payload (400)."""
        resp = client.post("/settings/import", json={})
        assert resp.status_code == 400

    def test_import_config_only(self, client, device_config_dev):
        """Import with only a config key and no env_keys should succeed."""
        resp = client.post(
            "/settings/import", json={"config": {"name": "MinimalImport"}}
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_import_rejects_payload_with_no_recognized_keys(
        self, client, device_config_dev
    ):
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

    def test_import_success_message_reports_counts(self, client, device_config_dev):
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


# ---------------------------------------------------------------------------
# /settings/export (GET) - export settings
# ---------------------------------------------------------------------------


class TestExportSettings:
    def test_export_without_keys(self, client):
        resp = client.get("/settings/export")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "config" in data["data"]
        assert "env_keys" not in data["data"]

    def test_export_with_keys(self, client, device_config_dev):
        resp = client.post("/settings/export", json={"include_keys": True})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "env_keys" in data["data"]

    def test_export_get_never_includes_keys(self, client, device_config_dev):
        device_config_dev.set_env_key("OPEN_AI_SECRET", "sk-test")
        resp = client.get("/settings/export?include_keys=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "env_keys" not in data["data"]
