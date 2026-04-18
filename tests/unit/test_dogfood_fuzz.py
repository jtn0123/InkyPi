# pyright: reportMissingImports=false
"""Focused fuzz/regression tests for JTN-746 settings validation."""

import pytest


class TestDeviceNameValidation:
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
        form = {**self.VALID_FORM}
        form.update(overrides)
        return form

    def test_device_name_length_is_capped(self, client):
        resp = client.post(
            "/save_settings",
            data=self._form(deviceName="a" * 65),
        )
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
    def test_device_name_control_chars_are_rejected_or_stripped(
        self, client, device_config_dev, bad_name
    ):
        resp = client.post("/save_settings", data=self._form(deviceName=bad_name))
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["details"]["field"] == "deviceName"
        assert device_config_dev.get_config("name") != bad_name

    def test_device_name_tab_is_allowed(self, client, device_config_dev):
        name_with_tab = "Device\tName"
        resp = client.post("/save_settings", data=self._form(deviceName=name_with_tab))
        assert resp.status_code == 200
        assert device_config_dev.get_config("name") == name_with_tab
