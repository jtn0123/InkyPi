# pyright: reportMissingImports=false
"""Tests that plugin validate_settings errors are surfaced, not silently swallowed (JTN-349).

Theme 2 of dogfood pass 3: weather lat/lon, calendar URL, and image_folder path
fields must reject invalid data at save time with a clear error.
"""

from unittest.mock import patch


class TestWeatherValidation:
    """Weather plugin must reject out-of-range lat/lon at save time."""

    def test_weather_save_rejects_out_of_range_latitude(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "weather",
                "latitude": "999",
                "longitude": "0",
                "units": "imperial",
                "weatherProvider": "OpenMeteo",
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Latitude" in data["error"] or "latitude" in data["error"].lower()

    def test_weather_save_rejects_out_of_range_longitude(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "weather",
                "latitude": "40",
                "longitude": "999",
                "units": "imperial",
                "weatherProvider": "OpenMeteo",
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Longitude" in data["error"] or "longitude" in data["error"].lower()

    def test_weather_save_rejects_non_numeric_latitude(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "weather",
                "latitude": "not-a-number",
                "longitude": "0",
                "units": "imperial",
                "weatherProvider": "OpenMeteo",
            },
        )
        assert resp.status_code == 400

    def test_weather_save_rejects_missing_latitude(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "weather",
                "latitude": "",
                "longitude": "0",
                "units": "imperial",
                "weatherProvider": "OpenMeteo",
            },
        )
        assert resp.status_code == 400

    def test_weather_save_accepts_valid_coordinates(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "weather",
                "latitude": "40.7128",
                "longitude": "-74.006",
                "units": "imperial",
                "weatherProvider": "OpenMeteo",
            },
        )
        assert resp.status_code == 200


class TestCalendarValidation:
    """Calendar plugin must reject invalid URLs at save time."""

    def test_calendar_save_rejects_non_url(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "calendar",
                "calendarURLs[]": "not-a-url",
                "calendarColors[]": "#007BFF",
                "viewMode": "dayGridMonth",
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "not valid" in data["error"].lower() or "url" in data["error"].lower()

    def test_calendar_save_rejects_javascript_url(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "calendar",
                "calendarURLs[]": "javascript:alert(1)",
                "calendarColors[]": "#007BFF",
                "viewMode": "dayGridMonth",
            },
        )
        assert resp.status_code == 400

    def test_calendar_save_rejects_empty_url(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "calendar",
                "calendarURLs[]": "",
                "calendarColors[]": "#007BFF",
                "viewMode": "dayGridMonth",
            },
        )
        assert resp.status_code == 400

    def test_calendar_save_accepts_valid_url(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "calendar",
                "calendarURLs[]": "https://calendar.google.com/basic.ics",
                "calendarColors[]": "#007BFF",
                "viewMode": "dayGridMonth",
            },
        )
        assert resp.status_code == 200


class TestImageFolderValidation:
    """Image Folder plugin must reject non-existent folder paths at save time."""

    def test_image_folder_save_rejects_nonexistent_path(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "image_folder",
                "folder_path": "/nonexistent/fake/path/12345",
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "not" in data["error"].lower() or "exist" in data["error"].lower()

    def test_image_folder_save_rejects_folder_with_no_images(self, client, tmp_path):
        """An existing folder with zero image files should be rejected."""
        empty = tmp_path / "empty-folder"
        empty.mkdir()
        (empty / "readme.txt").write_text("not an image")
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "image_folder",
                "folder_path": str(empty),
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "no image" in data["error"].lower() or "image" in data["error"].lower()

    def test_image_folder_save_rejects_unreadable_folder(self, client, tmp_path):
        """A folder without read permission should be rejected."""
        import os

        if os.geteuid() == 0:
            # Skip under root because permission checks are bypassed
            import pytest

            pytest.skip("cannot test read-permission check under root")
        folder = tmp_path / "no-read"
        folder.mkdir()
        os.chmod(folder, 0o200)  # write-only
        try:
            resp = client.post(
                "/save_plugin_settings",
                data={
                    "plugin_id": "image_folder",
                    "folder_path": str(folder),
                },
            )
            assert resp.status_code == 400
            data = resp.get_json()
            assert "readable" in data["error"].lower() or "not" in data["error"].lower()
        finally:
            # Restore permissions so pytest can clean up
            os.chmod(folder, 0o700)

    def test_image_folder_save_rejects_empty_path(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={
                "plugin_id": "image_folder",
                "folder_path": "",
            },
        )
        assert resp.status_code == 400


class TestPluginValidateSettingsException:
    """If validate_settings raises an exception, the error must be surfaced."""

    def test_validate_settings_exception_returns_400(self, client):
        """A validate_settings method that raises should return 400, not silently succeed."""
        with patch(
            "plugins.weather.weather.Weather.validate_settings",
            side_effect=ValueError("unexpected error"),
        ):
            resp = client.post(
                "/save_plugin_settings",
                data={
                    "plugin_id": "weather",
                    "latitude": "40",
                    "longitude": "-74",
                    "units": "imperial",
                    "weatherProvider": "OpenMeteo",
                },
            )
            assert resp.status_code == 400
            data = resp.get_json()
            assert "validation failed" in data["error"].lower()

    def test_validate_settings_exception_htmx_returns_error_partial(self, client):
        """HTMX clients should receive an HTML error partial, not JSON."""
        with patch(
            "plugins.weather.weather.Weather.validate_settings",
            side_effect=ValueError("unexpected error"),
        ):
            resp = client.post(
                "/save_plugin_settings",
                data={
                    "plugin_id": "weather",
                    "latitude": "40",
                    "longitude": "-74",
                    "units": "imperial",
                    "weatherProvider": "OpenMeteo",
                },
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 400
            assert "text/html" in resp.headers.get("Content-Type", "")
            body = resp.get_data(as_text=True)
            assert "validation failed" in body.lower()

    def test_get_plugin_instance_exception_allows_save(self, client, tmp_path):
        """If get_plugin_instance raises, save should still succeed (plugin=None skips validation)."""
        from PIL import Image

        folder = tmp_path / "pics"
        folder.mkdir()
        Image.new("RGB", (4, 4), "white").save(folder / "a.png")

        with patch(
            "blueprints.plugin.get_plugin_instance",
            side_effect=RuntimeError("boom"),
        ):
            resp = client.post(
                "/save_plugin_settings",
                data={
                    "plugin_id": "image_folder",
                    "folder_path": str(folder),
                },
            )
            # Save succeeds because validation is skipped when the plugin
            # instance cannot be loaded; the error is logged but not surfaced.
            assert resp.status_code == 200

    def test_validate_required_fields_exception_continues_to_validate_settings(
        self, client, tmp_path
    ):
        """If validate_plugin_required_fields raises, we still reach validate_settings."""
        from PIL import Image

        folder = tmp_path / "pics"
        folder.mkdir()
        Image.new("RGB", (4, 4), "white").save(folder / "a.png")

        with patch(
            "blueprints.plugin.validate_plugin_required_fields",
            side_effect=RuntimeError("boom"),
        ):
            resp = client.post(
                "/save_plugin_settings",
                data={
                    "plugin_id": "image_folder",
                    "folder_path": str(folder),
                },
            )
            # validate_settings on image_folder returns None when folder exists
            # and has images, so the save should succeed even though the
            # required-field check raised and was swallowed/logged.
            assert resp.status_code == 200


class TestPluginIdLogSanitization:
    """Regression test for pythonsecurity:S5145 — user input must be sanitized in logs."""

    def test_save_with_malicious_plugin_id_sanitizes_log(self, client, caplog):
        """A plugin_id containing newlines should not leak into logs verbatim."""
        import logging

        caplog.set_level(logging.WARNING, logger="blueprints.plugin")

        # Known-missing plugin id with log-injection characters
        resp = client.post(
            "/save_plugin_settings",
            data={"plugin_id": "weather\ninjected\rline"},
        )
        assert resp.status_code == 404
        # None of the captured log records should contain a raw newline from
        # the user-controlled plugin_id value.
        for record in caplog.records:
            assert "\ninjected" not in record.getMessage()
            assert "\rline" not in record.getMessage()


class TestUpdatePluginInstanceValidation:
    """update_plugin_instance route must enforce validation (JTN-349)."""

    def _add_instance(self, flask_app, plugin_id, instance_name, settings=None):
        """Seed a plugin instance on the Default playlist for update tests."""
        device_config = flask_app.config["DEVICE_CONFIG"]
        pm = device_config.get_playlist_manager()
        playlist_name = "Default"
        if not pm.get_playlist(playlist_name):
            pm.add_playlist(playlist_name)
        playlist = pm.get_playlist(playlist_name)
        playlist.add_plugin(
            {
                "plugin_id": plugin_id,
                "name": instance_name,
                "plugin_settings": settings or {},
                "refresh": {"interval": 3600},
            }
        )
        return instance_name

    def test_update_rejects_out_of_range_latitude(self, client, flask_app):
        name = self._add_instance(flask_app, "weather", "weather_test_invalid")
        resp = client.put(
            f"/update_plugin_instance/{name}",
            data={
                "plugin_id": "weather",
                "latitude": "999",
                "longitude": "0",
                "units": "imperial",
                "weatherProvider": "OpenMeteo",
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "latitude" in data["error"].lower()

    def test_update_surfaces_validate_settings_exception(self, client, flask_app):
        name = self._add_instance(flask_app, "weather", "weather_test_raise")
        with patch(
            "plugins.weather.weather.Weather.validate_settings",
            side_effect=ValueError("boom"),
        ):
            resp = client.put(
                f"/update_plugin_instance/{name}",
                data={
                    "plugin_id": "weather",
                    "latitude": "40",
                    "longitude": "-74",
                    "units": "imperial",
                    "weatherProvider": "OpenMeteo",
                },
            )
            assert resp.status_code == 400
            data = resp.get_json()
            assert "validation failed" in data["error"].lower()

    def test_update_continues_when_get_plugin_instance_raises(
        self, client, flask_app, tmp_path
    ):
        from PIL import Image

        folder = tmp_path / "pics"
        folder.mkdir()
        Image.new("RGB", (4, 4), "white").save(folder / "a.png")

        name = self._add_instance(
            flask_app, "image_folder", "if_test_loaderfail", {"folder_path": ""}
        )
        with patch(
            "blueprints.plugin.get_plugin_instance",
            side_effect=RuntimeError("cannot load"),
        ):
            resp = client.put(
                f"/update_plugin_instance/{name}",
                data={
                    "plugin_id": "image_folder",
                    "folder_path": str(folder),
                },
            )
            # Update still succeeds — validation is skipped and logged.
            assert resp.status_code == 200
