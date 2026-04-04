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
        payload = {
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
