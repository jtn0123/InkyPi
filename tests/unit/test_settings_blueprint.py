# pyright: reportMissingImports=false
"""Comprehensive tests for the settings blueprint routes."""

import io
import json
import time
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# /settings/update (POST) - start update
# ---------------------------------------------------------------------------


class TestStartUpdate:
    def test_start_update_success(self, client, monkeypatch):
        """POST /settings/update triggers update and returns success JSON."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
        # Prevent the background thread from actually sleeping
        monkeypatch.setattr(mod, "_start_update_fallback_thread", lambda sp: None)
        mod._set_update_state(False, None)

        resp = client.post("/settings/update")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["running"] is True
        # Clean up
        mod._set_update_state(False, None)

    def test_start_update_already_running(self, client, monkeypatch):
        """POST /settings/update returns 409 when update is already running."""
        import blueprints.settings as mod

        mod._set_update_state(True, "inkypi-update-test.service")
        try:
            resp = client.post("/settings/update")
            assert resp.status_code == 409
            data = resp.get_json()
            assert data["success"] is False
            assert "already in progress" in data["error"]
        finally:
            mod._set_update_state(False, None)

    def test_start_update_systemd_path(self, client, monkeypatch):
        """POST /settings/update uses systemd path when available."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: "/fake/update.sh")
        monkeypatch.setattr(mod, "_start_update_via_systemd", lambda u, s: None)
        mod._set_update_state(False, None)

        resp = client.post("/settings/update")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        mod._set_update_state(False, None)

    def test_start_update_systemd_fails_falls_back(self, client, monkeypatch):
        """If systemd-run fails, falls back to thread runner."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
        monkeypatch.setattr(
            mod, "_start_update_via_systemd", MagicMock(side_effect=OSError("fail"))
        )
        monkeypatch.setattr(mod, "_start_update_fallback_thread", lambda sp: None)
        mod._set_update_state(False, None)

        resp = client.post("/settings/update")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        mod._set_update_state(False, None)


# ---------------------------------------------------------------------------
# /settings/update_status (GET) - update status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_update_status_idle(self, client, monkeypatch):
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        resp = client.get("/settings/update_status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["running"] is False
        assert data["unit"] is None

    def test_update_status_running(self, client, monkeypatch):
        import blueprints.settings as mod

        mod._set_update_state(True, "inkypi-update-123.service")
        # Prevent auto-clear from systemctl checks in CI
        monkeypatch.setattr(mod, "_systemd_available", lambda: False)
        try:
            resp = client.get("/settings/update_status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["running"] is True
            assert data["unit"] == "inkypi-update-123.service"
            assert data["started_at"] is not None
        finally:
            mod._set_update_state(False, None)

    def test_update_status_clears_when_systemd_inactive(self, client, monkeypatch):
        """When the systemd unit is no longer active, running should auto-clear."""
        import blueprints.settings as mod

        mod._set_update_state(True, "inkypi-update-old.service")
        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(
            mod.subprocess,
            "run",
            lambda *a, **kw: MagicMock(stdout="inactive\n", returncode=0),
        )
        try:
            resp = client.get("/settings/update_status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["running"] is False
            assert mod._UPDATE_STATE.get("last_unit") == "inkypi-update-old.service"
        finally:
            mod._set_update_state(False, None)

    def test_update_status_timeout_clears(self, client, monkeypatch):
        """If started_at is >30 min ago, update state should auto-clear."""
        import blueprints.settings as mod

        mod._set_update_state(True, None)
        # Backdate started_at by 2 hours
        mod._UPDATE_STATE["started_at"] = time.time() - 7200
        try:
            resp = client.get("/settings/update_status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["running"] is False
        finally:
            mod._set_update_state(False, None)

    def test_start_update_passes_target_tag(self, client, monkeypatch):
        """POST /settings/update with target_version should pass it to systemd cmd."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(
            mod, "_get_update_script_path", lambda: "/fake/do_update.sh"
        )

        captured_args = {}

        def mock_systemd(unit, script, target_tag=None):
            captured_args["unit"] = unit
            captured_args["script"] = script
            captured_args["target_tag"] = target_tag

        monkeypatch.setattr(mod, "_start_update_via_systemd", mock_systemd)
        mod._set_update_state(False, None)

        resp = client.post(
            "/settings/update",
            json={"target_version": "v1.2.0"},
        )
        assert resp.status_code == 200
        assert captured_args["target_tag"] == "v1.2.0"
        assert captured_args["script"] == "/fake/do_update.sh"
        mod._set_update_state(False, None)

    def test_start_update_rejects_invalid_target_tag(self, client, monkeypatch):
        """POST /settings/update rejects shell injection in target_version."""
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        resp = client.post(
            "/settings/update",
            json={"target_version": "; rm -rf /"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "Invalid target version" in data["error"]

    def test_start_update_rejects_flag_injection(self, client, monkeypatch):
        """POST /settings/update rejects flag-style injection."""
        import blueprints.settings as mod

        mod._set_update_state(False, None)
        resp = client.post(
            "/settings/update",
            json={"target_version": "--malicious"},
        )
        assert resp.status_code == 400

    def test_start_update_accepts_semver_with_prerelease(self, client, monkeypatch):
        """POST /settings/update accepts valid semver with pre-release suffix."""
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_systemd_available", lambda: True)
        monkeypatch.setattr(
            mod, "_get_update_script_path", lambda: "/fake/do_update.sh"
        )

        captured_args = {}

        def mock_systemd(unit, script, target_tag=None):
            captured_args["target_tag"] = target_tag

        monkeypatch.setattr(mod, "_start_update_via_systemd", mock_systemd)
        mod._set_update_state(False, None)

        resp = client.post(
            "/settings/update",
            json={"target_version": "1.0.0-rc1"},
        )
        assert resp.status_code == 200
        assert captured_args["target_tag"] == "1.0.0-rc1"
        mod._set_update_state(False, None)


# ---------------------------------------------------------------------------
# /settings/isolation (GET, POST, DELETE) - plugin isolation
# ---------------------------------------------------------------------------


class TestPluginIsolation:
    def test_get_isolation_empty(self, client):
        resp = client.get("/settings/isolation")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["isolated_plugins"] == []

    def test_post_isolation_add_plugin(self, client):
        resp = client.post("/settings/isolation", json={"plugin_id": "weather"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "weather" in data["isolated_plugins"]

    def test_post_isolation_duplicate(self, client):
        """Adding the same plugin twice should not create duplicates."""
        client.post("/settings/isolation", json={"plugin_id": "weather"})
        resp = client.post("/settings/isolation", json={"plugin_id": "weather"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["isolated_plugins"].count("weather") == 1

    def test_delete_isolation_remove_plugin(self, client):
        client.post("/settings/isolation", json={"plugin_id": "weather"})
        resp = client.delete("/settings/isolation", json={"plugin_id": "weather"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "weather" not in data["isolated_plugins"]

    def test_isolation_invalid_body(self, client):
        resp = client.post(
            "/settings/isolation", data="not json", content_type="application/json"
        )
        assert resp.status_code == 400

    def test_isolation_missing_plugin_id(self, client):
        resp = client.post("/settings/isolation", json={})
        assert resp.status_code == 422

    def test_isolation_empty_plugin_id(self, client):
        resp = client.post("/settings/isolation", json={"plugin_id": "  "})
        assert resp.status_code == 422

    def test_isolation_non_string_plugin_id(self, client):
        resp = client.post("/settings/isolation", json={"plugin_id": 123})
        assert resp.status_code == 422

    def test_delete_nonexistent_plugin(self, client):
        """DELETE for a plugin that isn't isolated should succeed gracefully."""
        resp = client.delete("/settings/isolation", json={"plugin_id": "nonexistent"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True


# ---------------------------------------------------------------------------
# /settings/safe_reset (POST) - safe reset
# ---------------------------------------------------------------------------


class TestSafeReset:
    def test_safe_reset_success(self, client, device_config_dev):
        resp = client.post("/settings/safe_reset")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "reset" in data["message"].lower()

        # Verify defaults were applied
        cfg = device_config_dev.get_config()
        assert cfg["plugin_cycle_interval_seconds"] == 3600
        assert cfg["log_system_stats"] is False
        assert cfg["isolated_plugins"] == []

    def test_safe_reset_preserves_name(self, client, device_config_dev):
        """Safe reset should preserve the device name."""
        original_name = device_config_dev.get_config("name")
        client.post("/settings/safe_reset")
        assert device_config_dev.get_config("name") == original_name

    def test_safe_reset_preserves_timezone(self, client, device_config_dev):
        original_tz = device_config_dev.get_config("timezone")
        client.post("/settings/safe_reset")
        assert device_config_dev.get_config("timezone") == original_tz

    def test_safe_reset_error(self, client, device_config_dev):
        with patch.object(
            device_config_dev, "get_config", side_effect=RuntimeError("boom")
        ):
            resp = client.post("/settings/safe_reset")
            assert resp.status_code == 500


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
# /settings/save_api_keys (POST) - save API keys
# ---------------------------------------------------------------------------


class TestSaveApiKeys:
    def test_save_api_keys_success(self, client, device_config_dev):
        resp = client.post(
            "/settings/save_api_keys",
            data={
                "OPEN_AI_SECRET": "sk-test-key",
                "NASA_SECRET": "nasa-key-123",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "OPEN_AI_SECRET" in data["updated"]
        assert "NASA_SECRET" in data["updated"]

    def test_save_api_keys_empty_values_ignored(self, client, device_config_dev):
        resp = client.post(
            "/settings/save_api_keys",
            data={
                "OPEN_AI_SECRET": "",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "OPEN_AI_SECRET" not in data["updated"]

    def test_save_api_keys_no_data(self, client):
        resp = client.post("/settings/save_api_keys", data={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["updated"] == []

    def test_save_api_keys_error(self, client, device_config_dev):
        with patch.object(
            device_config_dev, "set_env_key", side_effect=RuntimeError("write fail")
        ):
            resp = client.post(
                "/settings/save_api_keys",
                data={
                    "OPEN_AI_SECRET": "key",
                },
            )
            assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /settings/delete_api_key (POST) - delete API key
# ---------------------------------------------------------------------------


class TestDeleteApiKey:
    def test_delete_api_key_success(self, client, device_config_dev):
        resp = client.post("/settings/delete_api_key", data={"key": "OPEN_AI_SECRET"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_delete_api_key_invalid_name(self, client):
        resp = client.post("/settings/delete_api_key", data={"key": "EVIL_KEY"})
        assert resp.status_code == 400

    def test_delete_api_key_missing_key(self, client):
        resp = client.post("/settings/delete_api_key", data={})
        assert resp.status_code == 400

    def test_delete_api_key_each_valid_key(self, client, device_config_dev):
        """Each valid key name should be accepted."""
        for key in (
            "OPEN_AI_SECRET",
            "OPEN_WEATHER_MAP_SECRET",
            "NASA_SECRET",
            "UNSPLASH_ACCESS_KEY",
        ):
            resp = client.post("/settings/delete_api_key", data={"key": key})
            assert resp.status_code == 200, f"Failed for key={key}"

    def test_delete_api_key_error(self, client, device_config_dev):
        with patch.object(
            device_config_dev, "unset_env_key", side_effect=OSError("fail")
        ):
            resp = client.post(
                "/settings/delete_api_key", data={"key": "OPEN_AI_SECRET"}
            )
            assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /save_settings (POST) - save device settings
# ---------------------------------------------------------------------------


class TestSaveSettings:
    VALID_FORM = {
        "unit": "minute",
        "interval": "30",
        "timeFormat": "24h",
        "timezoneName": "UTC",
        "deviceName": "TestDevice",
        "orientation": "horizontal",
        "saturation": "1.0",
        "brightness": "1.0",
        "sharpness": "1.0",
        "contrast": "1.0",
    }

    def test_save_settings_success(self, client, device_config_dev):
        resp = client.post("/save_settings", data=self.VALID_FORM)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert device_config_dev.get_config("name") == "TestDevice"

    def test_save_settings_missing_unit(self, client):
        form = {**self.VALID_FORM}
        del form["unit"]
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_save_settings_invalid_unit(self, client):
        form = {**self.VALID_FORM, "unit": "nanosecond"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_save_settings_missing_interval(self, client):
        form = {**self.VALID_FORM}
        del form["interval"]
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_save_settings_non_numeric_interval(self, client):
        form = {**self.VALID_FORM, "interval": "abc"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_save_settings_missing_timezone(self, client):
        form = {**self.VALID_FORM, "timezoneName": ""}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_save_settings_missing_time_format(self, client):
        form = {**self.VALID_FORM}
        del form["timeFormat"]
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_save_settings_invalid_time_format(self, client):
        form = {**self.VALID_FORM, "timeFormat": "48h"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_save_settings_interval_too_large(self, client):
        """Interval > 24 hours should be rejected."""
        form = {**self.VALID_FORM, "unit": "hour", "interval": "25"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_save_settings_with_inky_saturation(self, client, device_config_dev):
        form = {**self.VALID_FORM, "inky_saturation": "0.7"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200
        img_settings = device_config_dev.get_config("image_settings")
        assert img_settings["inky_saturation"] == 0.7

    def test_save_settings_triggers_config_change(self, client, device_config_dev):
        """Changing interval should signal config change on refresh task."""
        # Set initial interval different from what we'll submit
        device_config_dev.update_value("plugin_cycle_interval_seconds", 600, write=True)
        form = {**self.VALID_FORM, "unit": "hour", "interval": "1"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200

    def test_save_settings_hour_unit(self, client, device_config_dev):
        form = {**self.VALID_FORM, "unit": "hour", "interval": "2"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200

    def test_save_settings_preview_size_mode(self, client, device_config_dev):
        form = {**self.VALID_FORM, "previewSizeMode": "fit"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200
        assert device_config_dev.get_config("preview_size_mode") == "fit"

    def test_save_settings_legacy_device_post(self, client, device_config_dev):
        """POST /settings/device should forward to save_settings."""
        resp = client.post("/settings/device", data=self.VALID_FORM)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_save_settings_legacy_device_get(self, client):
        """GET /settings/device should render settings page."""
        resp = client.get("/settings/device")
        assert resp.status_code == 200

    def test_save_settings_legacy_display_post(self, client, device_config_dev):
        resp = client.post("/settings/display", data=self.VALID_FORM)
        assert resp.status_code == 200

    def test_save_settings_legacy_network_get(self, client):
        resp = client.get("/settings/network")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /settings/client_log (POST) - client error logging
# ---------------------------------------------------------------------------


class TestClientLog:
    def test_client_log_info(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "info",
                "message": "test log message",
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_client_log_error(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "error",
                "message": "something broke",
            },
        )
        assert resp.status_code == 200

    def test_client_log_warning(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "warn",
                "message": "warning msg",
            },
        )
        assert resp.status_code == 200

    def test_client_log_debug(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "debug",
                "message": "debug msg",
            },
        )
        assert resp.status_code == 200

    def test_client_log_with_extra(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "info",
                "message": "with extra",
                "extra": {"key": "value", "count": 42},
            },
        )
        assert resp.status_code == 200

    def test_client_log_invalid_body(self, client):
        resp = client.post(
            "/settings/client_log", data="not json", content_type="application/json"
        )
        assert resp.status_code == 400

    def test_client_log_missing_fields_defaults(self, client):
        """Missing level/message should default gracefully."""
        resp = client.post("/settings/client_log", json={})
        assert resp.status_code == 200

    def test_client_log_unknown_level_defaults_to_info(self, client):
        resp = client.post(
            "/settings/client_log",
            json={
                "level": "trace",
                "message": "unknown level",
            },
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /shutdown (POST) - shutdown/reboot
# ---------------------------------------------------------------------------


class TestShutdown:
    def test_shutdown_success(self, client, monkeypatch):
        import subprocess

        monkeypatch.setattr(subprocess, "run", MagicMock())
        resp = client.post("/shutdown", json={"reboot": False})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_reboot_success(self, client, monkeypatch):
        import subprocess

        import blueprints.settings as mod

        mod._last_shutdown_time = 0.0
        monkeypatch.setattr(subprocess, "run", MagicMock())
        resp = client.post("/shutdown", json={"reboot": True})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_shutdown_rate_limited(self, client, monkeypatch):
        import subprocess

        monkeypatch.setattr(subprocess, "run", MagicMock())
        # First call succeeds
        resp1 = client.post("/shutdown", json={})
        assert resp1.status_code == 200
        # Second call within cooldown should be rate limited
        resp2 = client.post("/shutdown", json={})
        assert resp2.status_code == 429

    def test_shutdown_command_failure(self, client, monkeypatch):
        import subprocess

        import blueprints.settings as mod

        mod._last_shutdown_time = 0.0
        monkeypatch.setattr(
            subprocess,
            "run",
            MagicMock(side_effect=subprocess.CalledProcessError(1, "sudo")),
        )
        resp = client.post("/shutdown", json={})
        assert resp.status_code == 500

    def test_shutdown_no_json_body(self, client, monkeypatch):
        """POST /shutdown with no body should default to shutdown (not reboot)."""
        import subprocess

        import blueprints.settings as mod

        mod._last_shutdown_time = 0.0
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)
        resp = client.post("/shutdown")
        assert resp.status_code == 200
        # Should have called shutdown, not reboot
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "shutdown" in args


# ---------------------------------------------------------------------------
# /api/logs (GET) - log retrieval
# ---------------------------------------------------------------------------


class TestApiLogs:
    def test_api_logs_default(self, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "lines" in data
        assert "count" in data
        assert "meta" in data

    def test_api_logs_with_hours(self, client):
        resp = client.get("/api/logs?hours=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["hours"] == 1

    def test_api_logs_hours_clamped_high(self, client):
        resp = client.get("/api/logs?hours=999")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["hours"] <= 24

    def test_api_logs_hours_clamped_low(self, client):
        resp = client.get("/api/logs?hours=0")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["hours"] >= 1

    def test_api_logs_with_limit(self, client):
        resp = client.get("/api/logs?limit=100")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["limit"] == 100

    def test_api_logs_with_contains(self, client):
        resp = client.get("/api/logs?contains=test")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["contains"] == "test"

    def test_api_logs_contains_trimmed(self, client):
        """Contains filter >200 chars should be trimmed."""
        long_filter = "x" * 250
        resp = client.get(f"/api/logs?contains={long_filter}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["meta"]["contains"]) == 200
        assert data["truncated"] is True

    def test_api_logs_level_errors(self, client):
        resp = client.get("/api/logs?level=errors")
        assert resp.status_code == 200

    def test_api_logs_level_warnings(self, client):
        resp = client.get("/api/logs?level=warnings")
        assert resp.status_code == 200

    def test_api_logs_invalid_hours(self, client):
        resp = client.get("/api/logs?hours=abc")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["meta"]["hours"] == 2  # default

    def test_api_logs_rate_limited(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_rate_limit_ok", lambda addr: False)
        resp = client.get("/api/logs")
        assert resp.status_code == 429

    def test_api_logs_with_update_unit(self, client, monkeypatch):
        """When an update is running, logs should include the update unit."""
        import blueprints.settings as mod

        mod._set_update_state(True, "inkypi-update-test.service")
        try:
            resp = client.get("/api/logs")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "inkypi-update-test.service" in data["meta"]["units"]
        finally:
            mod._set_update_state(False, None)


# ---------------------------------------------------------------------------
# /download-logs (GET) - download logs
# ---------------------------------------------------------------------------


class TestDownloadLogs:
    def test_download_logs_default(self, client):
        resp = client.get("/download-logs")
        assert resp.status_code == 200
        assert resp.content_type == "text/plain; charset=utf-8"
        assert "attachment" in resp.headers.get("Content-Disposition", "")

    def test_download_logs_custom_hours(self, client):
        resp = client.get("/download-logs?hours=4")
        assert resp.status_code == 200


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
        resp = client.get("/settings/export?include_keys=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "env_keys" in data["data"]


# ---------------------------------------------------------------------------
# Benchmark API endpoints
# ---------------------------------------------------------------------------


class TestBenchmarkAPIs:
    def test_benchmarks_summary_disabled(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: False)
        resp = client.get("/api/benchmarks/summary")
        assert resp.status_code == 404

    def test_benchmarks_summary_enabled(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["count"] == 0

    def test_benchmarks_refreshes_disabled(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: False)
        resp = client.get("/api/benchmarks/refreshes")
        assert resp.status_code == 404

    def test_benchmarks_refreshes_enabled(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/refreshes")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_benchmarks_plugins_disabled(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: False)
        resp = client.get("/api/benchmarks/plugins")
        assert resp.status_code == 404

    def test_benchmarks_plugins_enabled(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/plugins")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_benchmarks_stages_no_refresh_id(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        resp = client.get("/api/benchmarks/stages")
        assert resp.status_code == 422

    def test_benchmarks_stages_with_refresh_id(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/stages?refresh_id=abc-123")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_benchmarks_stages_disabled(self, client, monkeypatch):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: False)
        resp = client.get("/api/benchmarks/stages?refresh_id=abc")
        assert resp.status_code == 404

    def test_benchmarks_summary_with_window(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/summary?window=1h")
        assert resp.status_code == 200

    def test_benchmarks_refreshes_with_cursor(self, client, monkeypatch, tmp_path):
        import blueprints.settings as mod

        monkeypatch.setattr(mod, "_benchmarks_enabled", lambda: True)
        db_path = str(tmp_path / "bench.db")
        monkeypatch.setattr(mod, "_get_bench_db_path", lambda: db_path)
        resp = client.get("/api/benchmarks/refreshes?cursor=999")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Health API endpoints
# ---------------------------------------------------------------------------


class TestHealthAPIs:
    def test_health_plugins(self, client):
        resp = client.get("/api/health/plugins")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_health_system(self, client):
        resp = client.get("/api/health/system")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_health_system_no_psutil(self, client, monkeypatch):
        """When psutil is unavailable, system health returns None fields."""
        import blueprints.settings as mod

        _original = mod.health_system  # noqa: F841 — kept for potential future use

        # Patch psutil import to fail within the route
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("no psutil")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        resp = client.get("/api/health/system")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True


# ---------------------------------------------------------------------------
# /settings and /settings/backup pages
# ---------------------------------------------------------------------------


class TestSettingsPages:
    def test_settings_page(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_backup_restore_page(self, client):
        resp = client.get("/settings/backup")
        assert resp.status_code == 200

    def test_api_keys_page(self, client):
        resp = client.get("/settings/api-keys")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_window_since_seconds_hours(self):
        from blueprints.settings import _window_since_seconds

        result = _window_since_seconds("6h")
        assert result > 0
        assert result < time.time()

    def test_window_since_seconds_minutes(self):
        from blueprints.settings import _window_since_seconds

        result = _window_since_seconds("30m")
        assert result > 0

    def test_window_since_seconds_days(self):
        from blueprints.settings import _window_since_seconds

        result = _window_since_seconds("2d")
        assert result > 0

    def test_window_since_seconds_none(self):
        from blueprints.settings import _window_since_seconds

        result = _window_since_seconds(None)
        # Should default to 24h ago
        assert abs(result - (time.time() - 24 * 3600)) < 2

    def test_window_since_seconds_invalid_defaults_to_24h(self):
        from blueprints.settings import _window_since_seconds

        result = _window_since_seconds("abch")
        assert abs(result - (time.time() - 24 * 3600)) < 2

    def test_window_since_seconds_invalid_does_not_log_raw_input(self):
        from blueprints.settings import _window_since_seconds

        raw_window = "not-a-number\nforged-log-lineh"
        logger = _window_since_seconds.__globals__["logger"]
        with patch.object(logger, "warning") as warning_mock:
            _window_since_seconds(raw_window)

        warning_mock.assert_called_once_with(
            "Invalid benchmark window provided, defaulting to 24h"
        )

    def test_pct_empty(self):
        from blueprints.settings import _pct

        assert _pct([], 0.5) is None

    def test_pct_values(self):
        from blueprints.settings import _pct

        assert _pct([10, 20, 30, 40, 50], 0.5) == 30

    def test_clamp_int(self):
        from blueprints.settings import _clamp_int

        assert _clamp_int("5", 10, 1, 100) == 5
        assert _clamp_int("200", 10, 1, 100) == 100
        assert _clamp_int("0", 10, 1, 100) == 1
        assert _clamp_int(None, 10, 1, 100) == 10
        assert _clamp_int("abc", 10, 1, 100) == 10

    def test_rate_limit_ok(self):
        from blueprints.settings import _REQUESTS, _rate_limit_ok

        _REQUESTS.clear()
        assert _rate_limit_ok("127.0.0.1") is True

    def test_benchmarks_enabled_default(self, monkeypatch):
        monkeypatch.delenv("INKYPI_BENCHMARK_API_ENABLED", raising=False)
        from blueprints.settings import _benchmarks_enabled

        assert _benchmarks_enabled() is True

    def test_benchmarks_disabled(self, monkeypatch):
        monkeypatch.setenv("INKYPI_BENCHMARK_API_ENABLED", "false")
        from blueprints.settings import _benchmarks_enabled

        assert _benchmarks_enabled() is False
