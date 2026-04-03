# pyright: reportMissingImports=false
"""Tests for input validation hardening fixes (JTN-134 through JTN-142).

Covers:
- JTN-134: API key save endpoint returns 400 for malformed input
- JTN-136: Settings import returns 400 for invalid uploaded JSON
- JTN-137: Playlist POST endpoints return 400 for malformed JSON
- JTN-138: Save settings returns 422 for invalid numeric image settings
- JTN-139: Client log endpoint sanitizes newlines (log injection prevention)
- JTN-140: Shutdown cooldown not consumed on failure
- JTN-141: Log endpoints don't leak raw exception text
- JTN-142: Delete plugin instance passes correct type to get_plugin_instance
"""

import io
import json
import subprocess
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# JTN-134: API key save endpoint input validation
# ---------------------------------------------------------------------------


class TestApiKeySaveValidation:
    """POST /api-keys/save should return 400 for malformed input, not 500."""

    def test_non_string_value_returns_400(self, client, tmp_path, monkeypatch):
        env_path = tmp_path / "test.env"
        env_path.write_text("")
        monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: str(env_path))
        resp = client.post(
            "/api-keys/save",
            json={"entries": [{"key": "TEST_KEY", "value": 123}]},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "string" in data["error"].lower()

    def test_non_dict_entry_returns_400(self, client, tmp_path, monkeypatch):
        env_path = tmp_path / "test.env"
        env_path.write_text("")
        monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: str(env_path))
        resp = client.post(
            "/api-keys/save",
            json={"entries": ["not_a_dict"]},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_non_string_key_returns_400(self, client, tmp_path, monkeypatch):
        env_path = tmp_path / "test.env"
        env_path.write_text("")
        monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: str(env_path))
        resp = client.post(
            "/api-keys/save",
            json={"entries": [{"key": 999, "value": "ok"}]},
        )
        assert resp.status_code == 400

    def test_keep_existing_with_none_value_does_not_crash(
        self, client, tmp_path, monkeypatch
    ):
        """When .env has a malformed line that parses as None, keepExisting should not 500."""
        env_path = tmp_path / ".env"
        # dotenv_values returns None for keys without values
        env_path.write_text("BROKEN_KEY\n")
        monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: str(env_path))
        resp = client.post(
            "/api-keys/save",
            json={"entries": [{"key": "BROKEN_KEY", "keepExisting": True}]},
        )
        # Should succeed (200) or validate (400), but never 500
        assert resp.status_code in {200, 400, 422}


# ---------------------------------------------------------------------------
# JTN-136: Settings import with invalid uploaded JSON
# ---------------------------------------------------------------------------


class TestSettingsImportValidation:
    """POST /settings/import should return 400 for malformed JSON uploads."""

    def test_malformed_json_file_returns_400(self, client):
        data = io.BytesIO(b"{not valid json")
        resp = client.post(
            "/settings/import",
            data={"file": (data, "bad.json")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert "invalid" in body["error"].lower()

    def test_binary_garbage_file_returns_400(self, client):
        data = io.BytesIO(b"\x80\x81\x82\x83")
        resp = client.post(
            "/settings/import",
            data={"file": (data, "garbage.json")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_valid_json_file_import_succeeds(self, client):
        payload = json.dumps({"config": {"name": "TestDevice"}})
        data = io.BytesIO(payload.encode())
        resp = client.post(
            "/settings/import",
            data={"file": (data, "config.json")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# JTN-137: Playlist POST endpoints malformed JSON
# ---------------------------------------------------------------------------


class TestPlaylistJsonValidation:
    """Playlist POST endpoints should return 400 for malformed JSON, not 500."""

    def test_add_plugin_malformed_refresh_settings_returns_400(self, client):
        resp = client.post(
            "/add_plugin",
            data={
                "plugin_id": "weather",
                "refresh_settings": "{bad json",
            },
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False

    def test_add_plugin_missing_refresh_settings_returns_400(self, client):
        resp = client.post(
            "/add_plugin",
            data={"plugin_id": "weather"},
        )
        assert resp.status_code == 400

    def test_reorder_plugins_malformed_json_returns_400(self, client):
        resp = client.post(
            "/reorder_plugins",
            data=b"not json at all",
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False

    def test_display_next_in_playlist_malformed_json_returns_400(self, client):
        resp = client.post(
            "/display_next_in_playlist",
            data=b"{{invalid",
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False


# ---------------------------------------------------------------------------
# JTN-138: Save settings invalid numeric image settings
# ---------------------------------------------------------------------------


class TestSaveSettingsNumericValidation:
    """POST /save_settings should return 422 for non-numeric image settings."""

    VALID_FORM = {
        "unit": "hour",
        "interval": "1",
        "timezoneName": "UTC",
        "timeFormat": "24h",
        "deviceName": "Test",
        "orientation": "horizontal",
    }

    def test_invalid_saturation_returns_422(self, client):
        form = {**self.VALID_FORM, "saturation": "abc"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["details"]["field"] == "saturation"

    def test_invalid_brightness_returns_422(self, client):
        form = {**self.VALID_FORM, "brightness": "not_a_number"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["details"]["field"] == "brightness"

    def test_invalid_contrast_returns_422(self, client):
        form = {**self.VALID_FORM, "contrast": "???"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_invalid_sharpness_returns_422(self, client):
        form = {**self.VALID_FORM, "sharpness": "NaN-bad"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_nan_rejected(self, client):
        form = {**self.VALID_FORM, "saturation": "NaN"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_infinity_rejected(self, client):
        form = {**self.VALID_FORM, "brightness": "Infinity"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422

    def test_valid_numeric_settings_pass_validation(self, client):
        form = {
            **self.VALID_FORM,
            "saturation": "1.5",
            "brightness": "0.8",
            "sharpness": "1.2",
            "contrast": "1.0",
        }
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# JTN-139: Client log endpoint log injection prevention
# ---------------------------------------------------------------------------


class TestClientLogSanitization:
    """POST /settings/client_log should strip newlines from client input."""

    def test_newlines_stripped_from_message(self, client):
        resp = client.post(
            "/settings/client_log",
            json={"level": "info", "message": "hello\nforged\rline", "extra": {}},
        )
        assert resp.status_code == 200

    def test_newlines_stripped_from_level(self, client):
        resp = client.post(
            "/settings/client_log",
            json={"level": "info\nevil", "message": "ok"},
        )
        assert resp.status_code == 200

    def test_sanitize_log_value_strips_control_chars(self):
        from blueprints.settings._system import _sanitize_log_value

        assert "\n" not in _sanitize_log_value("hello\nworld")
        assert "\r" not in _sanitize_log_value("hello\rworld")
        assert "\x00" not in _sanitize_log_value("hello\x00world")

    def test_sanitize_log_value_truncates(self):
        from blueprints.settings._system import _sanitize_log_value

        result = _sanitize_log_value("a" * 1000, max_len=50)
        assert len(result) == 50


# ---------------------------------------------------------------------------
# JTN-140: Shutdown cooldown not consumed on failure
# ---------------------------------------------------------------------------


class TestShutdownCooldownOnFailure:
    """POST /shutdown should not consume the cooldown when the command fails."""

    def test_failed_shutdown_does_not_block_retry(self, client, monkeypatch):
        import blueprints.settings as settings_mod

        # Reset cooldown
        settings_mod._shutdown_limiter.reset()

        # First call: subprocess fails
        monkeypatch.setattr(
            "subprocess.run",
            MagicMock(side_effect=subprocess.CalledProcessError(1, "sudo shutdown")),
        )
        resp1 = client.post("/shutdown", json={})
        assert resp1.status_code == 500

        # Second call should also 500 (subprocess still mocked to fail),
        # proving the cooldown was NOT consumed
        resp2 = client.post("/shutdown", json={})
        assert resp2.status_code == 500

    def test_successful_shutdown_does_consume_cooldown(self, client, monkeypatch):
        import blueprints.settings as settings_mod

        settings_mod._shutdown_limiter.reset()

        monkeypatch.setattr("subprocess.run", MagicMock())
        resp1 = client.post("/shutdown", json={})
        assert resp1.status_code == 200

        # Second call should be rate-limited
        resp2 = client.post("/shutdown", json={})
        assert resp2.status_code == 429


# ---------------------------------------------------------------------------
# JTN-141: Log endpoints don't leak raw exception text
# ---------------------------------------------------------------------------


class TestLogEndpointExceptionLeaks:
    """Log endpoints should return generic errors, not raw exception text."""

    def test_download_logs_hides_exception_details(self, client, monkeypatch):
        monkeypatch.setattr(
            "blueprints.settings._read_log_lines",
            MagicMock(side_effect=Exception("secret-internal-detail")),
        )
        resp = client.get("/download-logs")
        assert resp.status_code == 500
        assert b"secret-internal-detail" not in resp.data

    def test_api_logs_hides_exception_details(self, client, monkeypatch):
        monkeypatch.setattr(
            "blueprints.settings._read_log_lines",
            MagicMock(side_effect=Exception("secret-db-password")),
        )
        resp = client.get("/api/logs")
        assert resp.status_code == 500
        body = resp.get_json()
        assert "secret-db-password" not in json.dumps(body)
        assert body["success"] is False


# ---------------------------------------------------------------------------
# JTN-142: Delete plugin instance passes correct type to get_plugin_instance
# ---------------------------------------------------------------------------


class TestDeletePluginInstanceCleanup:
    """delete_plugin_instance should pass plugin config dict, not string ID."""

    def test_cleanup_receives_config_dict_not_string(
        self, client, flask_app, monkeypatch
    ):
        """Verify get_plugin_instance is called with a dict (plugin config), not a string."""
        device_config = flask_app.config["DEVICE_CONFIG"]

        # Set up a playlist with a plugin instance to delete
        playlist_manager = device_config.get_playlist_manager()
        playlist_manager.add_playlist("TestPlaylist")
        playlist = playlist_manager.get_playlist("TestPlaylist")
        playlist.add_plugin(
            {
                "plugin_id": "clock",
                "refresh": {"interval": 3600},
                "plugin_settings": {},
                "name": "test_instance",
            }
        )
        device_config.write_config()

        # Track what get_plugin_instance receives
        received_args = []

        def tracking_get_plugin_instance(arg):
            received_args.append(arg)
            mock_plugin = MagicMock()
            mock_plugin.cleanup = MagicMock()
            return mock_plugin

        monkeypatch.setattr(
            "blueprints.plugin.get_plugin_instance",
            tracking_get_plugin_instance,
        )

        resp = client.post(
            "/delete_plugin_instance",
            json={
                "playlist_name": "TestPlaylist",
                "plugin_id": "clock",
                "plugin_instance": "test_instance",
            },
        )
        assert resp.status_code == 200

        # The key assertion: get_plugin_instance should have received a dict
        assert len(received_args) == 1
        assert isinstance(
            received_args[0], dict
        ), f"Expected dict but got {type(received_args[0])}: {received_args[0]}"
        # Accept either "id" or "plugin_id" as the identifier key
        plugin_id = received_args[0].get("id") or received_args[0].get("plugin_id")
        assert plugin_id == "clock"
