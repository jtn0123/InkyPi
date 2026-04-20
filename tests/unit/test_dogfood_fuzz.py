# pyright: reportMissingImports=false
"""Dogfood fuzz/regression checks for settings and playlist validation."""

from pathlib import Path

import pytest

PLAYLIST_SHARED_JS = (
    Path(__file__).resolve().parents[2] / "src/static/scripts/playlist/shared.js"
)
EXPECTED_COPY = (
    "Playlist name can only contain ASCII letters, "
    "numbers, spaces, underscores, and hyphens"
)


class TestDeviceNameValidation:
    """Regression coverage for device-name validation edge cases."""

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

    def _form(self, **overrides):
        """Build a valid settings payload with optional overrides."""
        form = {**self.VALID_FORM}
        form.update(overrides)
        return form

    def test_device_name_length_is_capped(self, client):
        """Device names longer than the configured cap should be rejected."""
        resp = client.post(
            "/save_settings",
            data=self._form(deviceName="a" * 65),
        )
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["details"]["field"] == "deviceName"

    def test_device_name_padding_cannot_bypass_length_cap(self, client):
        """Over-padded submissions should still honor the raw input cap."""
        padded_name = f" {'a' * 64} "
        resp = client.post("/save_settings", data=self._form(deviceName=padded_name))
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["details"]["field"] == "deviceName"

    @pytest.mark.parametrize(
        "bad_name",
        [
            "\nDeviceName",
            "Device\nName",
            "Device\rName",
            "Device\x00Name",
            "Device\x0bName",
            "Device\x1fName",
        ],
    )
    def test_device_name_control_chars_are_rejected(
        self, client, device_config_dev, bad_name
    ):
        """Control characters should be rejected without mutating persisted config."""
        original_name = device_config_dev.get_config("name")
        resp = client.post("/save_settings", data=self._form(deviceName=bad_name))
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["details"]["field"] == "deviceName"
        assert device_config_dev.get_config("name") == original_name

    def test_device_name_is_trimmed_before_persisting(self, client, device_config_dev):
        """Leading and trailing whitespace should not be persisted."""
        resp = client.post(
            "/save_settings",
            data=self._form(deviceName="  Device\tName  "),
        )
        assert resp.status_code == 200
        assert device_config_dev.get_config("name") == "Device\tName"

    def test_device_name_tab_is_allowed(self, client, device_config_dev):
        """Tabs inside the device name are allowed and preserved."""
        name_with_tab = "Device\tName"
        resp = client.post("/save_settings", data=self._form(deviceName=name_with_tab))
        assert resp.status_code == 200
        assert device_config_dev.get_config("name") == name_with_tab


def test_non_ascii_playlist_names_match_ui_copy(client):
    """Non-ASCII playlist names should be rejected by both UI copy and server."""
    js = PLAYLIST_SHARED_JS.read_text()
    assert "^[A-Za-z0-9 _-]+$" in js
    assert EXPECTED_COPY in js

    for name in ("Météo", "東京", "Cafe\u0301"):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": name, "start_time": "08:00", "end_time": "12:00"},
        )
        assert resp.status_code == 400, name
        data = resp.get_json()
        assert data["success"] is False
        assert data["details"]["field"] == "playlist_name"
        assert EXPECTED_COPY in data["error"]
