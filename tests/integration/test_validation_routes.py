"""Integration tests for input validation on worst-offender routes.

Tests that invalid inputs are rejected with 400/422 and valid inputs succeed.

Worst offenders:
  - POST /save_settings  (settings update endpoint)
  - POST /save_plugin_settings  (plugin save endpoint)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_SETTINGS = {
    "deviceName": "Test Device",
    "orientation": "horizontal",
    "invertImage": "",
    "logSystemStats": "",
    "timezoneName": "UTC",
    "timeFormat": "24h",
    "interval": "1",
    "unit": "hour",
    "saturation": "1.0",
    "brightness": "1.0",
    "sharpness": "1.0",
    "contrast": "1.0",
}


# ---------------------------------------------------------------------------
# /save_settings — settings update endpoint
# ---------------------------------------------------------------------------


class TestSaveSettingsValidation:
    """Validate that /save_settings enforces field constraints."""

    def test_valid_settings_returns_200(self, client):
        resp = client.post("/save_settings", data=_VALID_SETTINGS)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True

    def test_missing_device_name_returns_422(self, client):
        data = {**_VALID_SETTINGS, "deviceName": ""}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 422

    def test_missing_timezone_returns_422(self, client):
        data = {**_VALID_SETTINGS, "timezoneName": ""}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 422

    def test_invalid_time_format_returns_422(self, client):
        data = {**_VALID_SETTINGS, "timeFormat": "weird"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 422

    def test_invalid_unit_returns_422(self, client):
        data = {**_VALID_SETTINGS, "unit": "week"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 422

    def test_non_numeric_interval_returns_422(self, client):
        data = {**_VALID_SETTINGS, "interval": "abc"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 422

    def test_zero_interval_returns_422(self, client):
        data = {**_VALID_SETTINGS, "interval": "0"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 422

    def test_saturation_out_of_range_returns_422(self, client):
        # 999.999 is well beyond any reasonable image adjustment range
        data = {**_VALID_SETTINGS, "saturation": "999.999"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 422

    def test_brightness_out_of_range_returns_422(self, client):
        data = {**_VALID_SETTINGS, "brightness": "-5.0"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 422

    def test_invalid_orientation_returns_422(self, client):
        data = {**_VALID_SETTINGS, "orientation": "diagonal"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 422

    def test_invalid_preview_size_mode_returns_422(self, client):
        data = {**_VALID_SETTINGS, "previewSizeMode": "unknown_mode_xyz"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 422

    def test_valid_orientation_horizontal_passes(self, client):
        data = {**_VALID_SETTINGS, "orientation": "horizontal"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 200

    def test_valid_orientation_vertical_passes(self, client):
        data = {**_VALID_SETTINGS, "orientation": "vertical"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 200

    def test_non_finite_saturation_returns_422(self, client):
        data = {**_VALID_SETTINGS, "saturation": "inf"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 422

    def test_saturation_at_boundary_0_passes(self, client):
        data = {**_VALID_SETTINGS, "saturation": "0.0"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 200

    def test_saturation_at_boundary_10_passes(self, client):
        data = {**_VALID_SETTINGS, "saturation": "10.0"}
        resp = client.post("/save_settings", data=data)
        assert resp.status_code == 200

    def test_response_body_is_json(self, client):
        resp = client.post("/save_settings", data=_VALID_SETTINGS)
        body = resp.get_json()
        assert body is not None
        assert "success" in body

    def test_missing_all_fields_returns_4xx(self, client):
        resp = client.post("/save_settings", data={})
        assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# /save_plugin_settings — plugin save endpoint
# ---------------------------------------------------------------------------


class TestSavePluginSettingsValidation:
    """Validate that /save_plugin_settings rejects missing plugin_id."""

    def test_missing_plugin_id_returns_422(self, client):
        resp = client.post("/save_plugin_settings", data={"city": "London"})
        assert resp.status_code == 422
        body = resp.get_json()
        assert body is not None

    def test_nonexistent_plugin_id_returns_404(self, client):
        resp = client.post(
            "/save_plugin_settings",
            data={"plugin_id": "no_such_plugin_xyz"},
        )
        assert resp.status_code == 404

    def test_empty_plugin_id_returns_422(self, client):
        resp = client.post("/save_plugin_settings", data={"plugin_id": ""})
        assert resp.status_code == 422

    def test_valid_clock_plugin_saves_successfully(self, client):
        """Clock plugin has no required fields — saving empty settings should succeed."""
        resp = client.post(
            "/save_plugin_settings",
            data={"plugin_id": "clock"},
        )
        # Clock plugin exists in test registry → expect 200
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
