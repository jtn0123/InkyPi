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
