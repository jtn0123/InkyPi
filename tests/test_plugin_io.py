"""Tests for the plugin instance export/import endpoints (JTN-448)."""

from __future__ import annotations

import io
import json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_plugin_instance(
    device_config, plugin_id="clock", name="My Clock", settings=None
):
    """Insert a plugin instance into the Default playlist and persist."""
    if settings is None:
        settings = {"time_format": "24h"}
    pm = device_config.get_playlist_manager()
    playlist = pm.get_playlist("Default")
    if not playlist:
        pm.add_playlist("Default")
        playlist = pm.get_playlist("Default")
    playlist.add_plugin(
        {
            "plugin_id": plugin_id,
            "name": name,
            "refresh": {"interval": 3600},
            "plugin_settings": settings,
        }
    )
    device_config.write_config()
    return playlist


# ---------------------------------------------------------------------------
# Export – single instance
# ---------------------------------------------------------------------------


class TestExportSingleInstance:
    def test_export_existing_instance_returns_attachment(
        self, client, device_config_dev
    ):
        _add_plugin_instance(device_config_dev, name="Living Room")

        resp = client.get("/api/plugins/export?instance=Living+Room")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        body = json.loads(resp.data)
        assert body["version"] == 1
        assert "exported_at" in body
        assert len(body["instances"]) == 1
        inst = body["instances"][0]
        assert inst["plugin_id"] == "clock"
        assert inst["name"] == "Living Room"
        assert "settings" in inst

    def test_export_nonexistent_instance_returns_404(self, client, device_config_dev):
        resp = client.get("/api/plugins/export?instance=DoesNotExist")
        assert resp.status_code == 404

    def test_export_single_instance_settings_match(self, client, device_config_dev):
        settings = {"time_format": "12h", "show_seconds": True}
        _add_plugin_instance(device_config_dev, name="Bedroom", settings=settings)

        resp = client.get("/api/plugins/export?instance=Bedroom")
        assert resp.status_code == 200
        body = json.loads(resp.data)
        exported_settings = body["instances"][0]["settings"]
        assert exported_settings.get("time_format") == "12h"


# ---------------------------------------------------------------------------
# Export – all instances
# ---------------------------------------------------------------------------


class TestExportAllInstances:
    def test_export_all_returns_array(self, client, device_config_dev):
        _add_plugin_instance(device_config_dev, name="Inst1")
        _add_plugin_instance(device_config_dev, name="Inst2", settings={"x": "y"})

        resp = client.get("/api/plugins/export")
        assert resp.status_code == 200
        body = json.loads(resp.data)
        assert body["version"] == 1
        names = {i["name"] for i in body["instances"]}
        assert "Inst1" in names
        assert "Inst2" in names

    def test_export_all_empty_playlist_returns_empty_array(
        self, client, device_config_dev
    ):
        resp = client.get("/api/plugins/export")
        assert resp.status_code == 200
        body = json.loads(resp.data)
        assert body["instances"] == []

    def test_export_all_content_disposition_has_filename(
        self, client, device_config_dev
    ):
        resp = client.get("/api/plugins/export")
        assert "attachment" in resp.headers.get("Content-Disposition", "")


# ---------------------------------------------------------------------------
# Import – valid JSON
# ---------------------------------------------------------------------------


class TestImportValid:
    def _payload(self, plugin_id="clock", name="Imported Clock", settings=None):
        return {
            "version": 1,
            "exported_at": "2026-01-01T00:00:00+00:00",
            "instances": [
                {
                    "plugin_id": plugin_id,
                    "name": name,
                    "settings": settings or {},
                }
            ],
        }

    def test_import_valid_json_adds_instance(self, client, device_config_dev):
        resp = client.post(
            "/api/plugins/import",
            json=self._payload(name="Test Import"),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["imported"] == 1
        assert body["skipped"] == []

        # Verify the instance was actually written
        pm = device_config_dev.get_playlist_manager()
        found = pm.find_plugin("clock", "Test Import")
        assert found is not None

    def test_import_preserves_settings(self, client, device_config_dev):
        settings = {"time_format": "12h", "color": "blue"}
        payload = self._payload(name="Settings Test", settings=settings)
        resp = client.post("/api/plugins/import", json=payload)
        assert resp.status_code == 200

        pm = device_config_dev.get_playlist_manager()
        inst = pm.find_plugin("clock", "Settings Test")
        assert inst is not None
        assert inst.settings.get("time_format") == "12h"
        assert inst.settings.get("color") == "blue"

    def test_import_multiple_instances(self, client, device_config_dev):
        payload = {
            "version": 1,
            "exported_at": "2026-01-01T00:00:00+00:00",
            "instances": [
                {"plugin_id": "clock", "name": "Multi A", "settings": {}},
                {"plugin_id": "clock", "name": "Multi B", "settings": {}},
            ],
        }
        resp = client.post("/api/plugins/import", json=payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["imported"] == 2


# ---------------------------------------------------------------------------
# Import – invalid JSON / bad shape
# ---------------------------------------------------------------------------


class TestImportInvalid:
    def test_import_empty_body_returns_400(self, client, device_config_dev):
        resp = client.post(
            "/api/plugins/import",
            data="not-json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_import_missing_version_returns_400(self, client, device_config_dev):
        payload = {"instances": [{"plugin_id": "clock", "name": "x", "settings": {}}]}
        resp = client.post("/api/plugins/import", json=payload)
        assert resp.status_code == 400

    def test_import_missing_instances_returns_400(self, client, device_config_dev):
        payload = {"version": 1}
        resp = client.post("/api/plugins/import", json=payload)
        assert resp.status_code == 400

    def test_import_instances_not_array_returns_400(self, client, device_config_dev):
        payload = {"version": 1, "instances": "not-a-list"}
        resp = client.post("/api/plugins/import", json=payload)
        assert resp.status_code == 400

    def test_import_instance_missing_plugin_id_returns_400(
        self, client, device_config_dev
    ):
        payload = {"version": 1, "instances": [{"name": "x", "settings": {}}]}
        resp = client.post("/api/plugins/import", json=payload)
        assert resp.status_code == 400

    def test_import_instance_missing_settings_returns_400(
        self, client, device_config_dev
    ):
        payload = {"version": 1, "instances": [{"plugin_id": "clock", "name": "x"}]}
        resp = client.post("/api/plugins/import", json=payload)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Import – unknown plugin_id
# ---------------------------------------------------------------------------


class TestImportSkipsUnknown:
    def test_import_unknown_plugin_id_skipped(self, client, device_config_dev):
        payload = {
            "version": 1,
            "exported_at": "2026-01-01T00:00:00+00:00",
            "instances": [
                {"plugin_id": "nonexistent_plugin_xyz", "name": "Bad", "settings": {}},
            ],
        }
        resp = client.post("/api/plugins/import", json=payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["imported"] == 0
        assert "nonexistent_plugin_xyz" in body["skipped"]

    def test_import_mixed_known_unknown(self, client, device_config_dev):
        payload = {
            "version": 1,
            "exported_at": "2026-01-01T00:00:00+00:00",
            "instances": [
                {"plugin_id": "clock", "name": "Good", "settings": {}},
                {"plugin_id": "phantom_plugin", "name": "Bad", "settings": {}},
            ],
        }
        resp = client.post("/api/plugins/import", json=payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["imported"] == 1
        assert "phantom_plugin" in body["skipped"]


# ---------------------------------------------------------------------------
# Import – name collision
# ---------------------------------------------------------------------------


class TestImportNameCollision:
    def test_import_collision_appends_imported(self, client, device_config_dev):
        # Pre-add an instance with the name we'll try to import
        _add_plugin_instance(device_config_dev, name="Clock One")

        payload = {
            "version": 1,
            "exported_at": "2026-01-01T00:00:00+00:00",
            "instances": [
                {"plugin_id": "clock", "name": "Clock One", "settings": {}},
            ],
        }
        resp = client.post("/api/plugins/import", json=payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["imported"] == 1
        assert len(body["renamed"]) == 1
        assert "Clock One" in body["renamed"][0]
        assert "(imported)" in body["renamed"][0]

        pm = device_config_dev.get_playlist_manager()
        assert pm.find_plugin("clock", "Clock One (imported)") is not None

    def test_import_double_collision_increments_suffix(self, client, device_config_dev):
        _add_plugin_instance(device_config_dev, name="Widget")
        _add_plugin_instance(device_config_dev, name="Widget (imported)", settings={})

        payload = {
            "version": 1,
            "exported_at": "2026-01-01T00:00:00+00:00",
            "instances": [
                {"plugin_id": "clock", "name": "Widget", "settings": {}},
            ],
        }
        resp = client.post("/api/plugins/import", json=payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["imported"] == 1

        pm = device_config_dev.get_playlist_manager()
        assert pm.find_plugin("clock", "Widget (imported 2)") is not None


# ---------------------------------------------------------------------------
# Round-trip: export → import
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_export_then_import_produces_equal_instances(
        self, client, device_config_dev
    ):
        settings = {"time_format": "24h", "show_date": True}
        _add_plugin_instance(device_config_dev, name="Round Trip", settings=settings)

        # Export
        export_resp = client.get("/api/plugins/export?instance=Round+Trip")
        assert export_resp.status_code == 200
        exported = json.loads(export_resp.data)

        # Rename the original so we can import without collision
        pm = device_config_dev.get_playlist_manager()
        orig = pm.find_plugin("clock", "Round Trip")
        assert orig is not None
        orig.name = "Round Trip Original"
        device_config_dev.write_config()

        # Import
        import_resp = client.post("/api/plugins/import", json=exported)
        assert import_resp.status_code == 200
        body = import_resp.get_json()
        assert body["imported"] == 1

        # Verify round-tripped instance matches
        pm = device_config_dev.get_playlist_manager()
        imported_inst = pm.find_plugin("clock", "Round Trip")
        assert imported_inst is not None
        assert imported_inst.settings.get("time_format") == "24h"
        assert imported_inst.settings.get("show_date") is True


# ---------------------------------------------------------------------------
# Multipart file upload
# ---------------------------------------------------------------------------


class TestImportMultipart:
    def test_import_via_file_upload(self, client, device_config_dev):
        payload = {
            "version": 1,
            "exported_at": "2026-01-01T00:00:00+00:00",
            "instances": [
                {"plugin_id": "clock", "name": "File Import", "settings": {"x": 1}},
            ],
        }
        data = json.dumps(payload).encode()
        resp = client.post(
            "/api/plugins/import",
            data={"file": (io.BytesIO(data), "export.json", "application/json")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["imported"] == 1

        pm = device_config_dev.get_playlist_manager()
        assert pm.find_plugin("clock", "File Import") is not None
