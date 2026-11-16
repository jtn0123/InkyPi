"""The settings form takes its allowed values from the device config schema.

The form, the saver and the loader used to keep three lists of the same
rules, and they drifted: the page offered "fit" for the preview size, the
schema did not allow it, and every render failed (#835). The schema is now the
one list. These tests change the schema and check that the form, the page and
safe reset follow, and that every choice the page offers saves and reloads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

_VALID_FORM = {
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


def _restart_config(device_config_dev: Any) -> Any:
    """Load the saved file the way the next start does (schema included)."""
    return type(device_config_dev)()


class _EditedSchema:
    """A copy of the device config schema that the app is pointed at."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from utils import config_schema

        self._module = config_schema
        self._monkeypatch = monkeypatch
        self._path = tmp_path / "device_config.schema.json"
        self.schema: dict[str, Any] = json.loads(
            Path(config_schema.SCHEMA_PATH).read_text()
        )

    def rules(self, *path: str) -> dict[str, Any]:
        node = self.schema
        for key in path:
            node = node["properties"][key]
        return node

    def install(self) -> None:
        self._path.write_text(json.dumps(self.schema))
        self._monkeypatch.setattr(self._module, "SCHEMA_PATH", str(self._path))


@pytest.fixture()
def edited_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _EditedSchema:
    return _EditedSchema(tmp_path, monkeypatch)


def _error(resp: Any) -> tuple[int, str, str]:
    body = resp.get_json()
    return resp.status_code, body["details"]["field"], body["error"]


class TestFormFollowsTheSchema:
    def test_device_name_limit(
        self, client: FlaskClient, edited_schema: _EditedSchema
    ) -> None:
        edited_schema.rules("name")["maxLength"] = 10
        edited_schema.install()

        resp = client.post(
            "/save_settings", data={**_VALID_FORM, "deviceName": "A" * 11}
        )
        status, field, message = _error(resp)
        assert (status, field) == (422, "deviceName")
        assert "10 characters" in message

        page = client.get("/settings").get_data(as_text=True)
        assert re.search(r'id="deviceName"[^>]*maxlength="10"', page)

    def test_device_name_pattern(
        self, client: FlaskClient, edited_schema: _EditedSchema
    ) -> None:
        # Tighten the pattern to letters only: the form now refuses a digit.
        edited_schema.rules("name")["pattern"] = "^[A-Za-z]*$"
        edited_schema.install()

        resp = client.post(
            "/save_settings", data={**_VALID_FORM, "deviceName": "Frame2"}
        )
        assert _error(resp)[:2] == (422, "deviceName")

    def test_time_format_choices(
        self, client: FlaskClient, edited_schema: _EditedSchema
    ) -> None:
        edited_schema.rules("time_format")["enum"] = ["24h"]
        edited_schema.install()

        resp = client.post("/save_settings", data={**_VALID_FORM, "timeFormat": "12h"})
        assert _error(resp)[:2] == (422, "timeFormat")

    @pytest.mark.parametrize(
        ("field", "schema_path", "allowed", "refused"),
        [
            ("orientation", ("orientation",), ["vertical"], "horizontal"),
            ("previewSizeMode", ("preview_size_mode",), ["native"], "fit"),
            (
                "screen_rendering",
                ("image_settings", "screen_rendering"),
                ["auto"],
                "dithered",
            ),
        ],
    )
    def test_optional_choices(
        self,
        client: FlaskClient,
        edited_schema: _EditedSchema,
        field: str,
        schema_path: tuple[str, ...],
        allowed: list[str],
        refused: str,
    ) -> None:
        edited_schema.rules(*schema_path)["enum"] = allowed
        edited_schema.install()

        form = {**_VALID_FORM, "orientation": "vertical", field: refused}
        resp = client.post("/save_settings", data=form)
        assert _error(resp)[:2] == (422, field)

    def test_image_setting_range(
        self, client: FlaskClient, edited_schema: _EditedSchema
    ) -> None:
        edited_schema.rules("image_settings", "saturation")["maximum"] = 2
        edited_schema.install()

        resp = client.post("/save_settings", data={**_VALID_FORM, "saturation": "3"})
        status, field, message = _error(resp)
        assert (status, field) == (422, "saturation")
        assert "2.0" in message

    def test_cycle_interval_limit(
        self, client: FlaskClient, edited_schema: _EditedSchema
    ) -> None:
        edited_schema.rules("plugin_cycle_interval_seconds")["maximum"] = 7200
        edited_schema.install()

        resp = client.post(
            "/save_settings", data={**_VALID_FORM, "unit": "hour", "interval": "3"}
        )
        status, field, message = _error(resp)
        assert (status, field) == (422, "interval")
        assert "2 hours" in message

        # The page's client-side cap comes from the same number.
        page = client.get("/settings").get_data(as_text=True)
        assert "pluginCycleIntervalMaxSeconds: 7200" in page

    def test_safe_reset_restores_the_schema_defaults(
        self,
        client: FlaskClient,
        device_config_dev: Any,
        edited_schema: _EditedSchema,
    ) -> None:
        edited_schema.rules("plugin_cycle_interval_seconds")["default"] = 1800
        edited_schema.install()
        device_config_dev.update_value("log_system_stats", True, write=True)

        assert client.post("/settings/safe_reset").status_code == 200

        restarted = _restart_config(device_config_dev)
        assert restarted.get_config("plugin_cycle_interval_seconds") == 1800
        assert restarted.get_config("log_system_stats") is False
        assert restarted.get_config("isolated_plugins") == []


class TestTheRealSchema:
    def test_twenty_four_hours_is_allowed(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """The schema's maximum is 86400 s; the message used to say "less
        than 24 hours" while the saver accepted exactly 24."""
        resp = client.post(
            "/save_settings", data={**_VALID_FORM, "unit": "hour", "interval": "24"}
        )
        assert resp.status_code == 200
        assert (
            _restart_config(device_config_dev).get_config(
                "plugin_cycle_interval_seconds"
            )
            == 86400
        )
        page = client.get("/settings").get_data(as_text=True)
        assert "pluginCycleIntervalMaxSeconds: 86400" in page
        assert re.search(r'id="deviceName"[^>]*maxlength="64"', page)

    def test_every_choice_the_page_offers_saves_and_reloads(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        # The screen-rendering choice is only shown for an Inky panel.
        device_config_dev.update_value("display_type", "inky")
        page = client.get("/settings").get_data(as_text=True)
        offered = {
            field: re.findall(rf'name="{field}" value="([^"]+)"', page)
            for field in ("orientation", "previewSizeMode", "timeFormat")
        }
        select = re.search(
            r'<select id="screen_rendering"[^>]*>(.*?)</select>', page, re.S
        )
        assert select is not None
        offered["screen_rendering"] = re.findall(r'value="([^"]+)"', select.group(1))
        saved_as = {
            "orientation": ("orientation",),
            "previewSizeMode": ("preview_size_mode",),
            "timeFormat": ("time_format",),
            "screen_rendering": ("image_settings", "screen_rendering"),
        }
        for field, values in offered.items():
            assert values, field
            for value in values:
                resp = client.post("/save_settings", data={**_VALID_FORM, field: value})
                assert resp.status_code == 200, (field, value, resp.get_json())
                saved: Any = _restart_config(device_config_dev).get_config()
                for key in saved_as[field]:
                    saved = saved[key]
                assert saved == value, (field, value)

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("name", "two\nlines"),
            ("time_format", "25h"),
            ("image_settings", {"saturation": 11.0}),
        ],
    )
    def test_backup_import_is_held_to_the_same_rules(
        self, client: FlaskClient, device_config_dev: Any, key: str, value: Any
    ) -> None:
        """A backup used to restore values the form refuses, because the
        schema did not know the form's rules."""
        before = device_config_dev.get_config(key)
        resp = client.post("/settings/import", json={"config": {key: value}})
        assert resp.status_code == 400
        assert key in resp.get_json()["error"]
        assert _restart_config(device_config_dev).get_config(key) == before
