# pyright: reportMissingImports=false
"""Tests for save settings, validation, plugin isolation, safe reset, and API keys."""

from unittest.mock import patch

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

    def test_post_isolation_trims_plugin_id(self, client):
        resp = client.post("/settings/isolation", json={"plugin_id": " weather "})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "weather" in data["isolated_plugins"]
        assert " weather " not in data["isolated_plugins"]

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

    def test_isolation_unknown_plugin_id(self, client):
        resp = client.post("/settings/isolation", json={"plugin_id": "nonexistent"})
        assert resp.status_code == 422

    def test_delete_unknown_plugin_id(self, client):
        resp = client.delete("/settings/isolation", json={"plugin_id": "nonexistent"})
        assert resp.status_code == 422


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
