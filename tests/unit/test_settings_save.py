# pyright: reportMissingImports=false
"""Tests for save settings, validation, plugin isolation, safe reset, and API keys."""

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from flask.testing import FlaskClient


def _saved_config_text(device_config_dev: Any) -> str:
    return Path(device_config_dev.config_file).read_text()


def _env_file(device_config_dev: Any) -> Path:
    return Path(device_config_dev.get_env_file_path())


def _restart_config(device_config_dev: Any) -> Any:
    """Load the saved config the way the next start (and every render
    worker) does; raises ConfigValidationError if the file is invalid."""
    return type(device_config_dev)()


# ---------------------------------------------------------------------------
# /settings/isolation (GET, POST, DELETE) - plugin isolation
# ---------------------------------------------------------------------------


class TestPluginIsolation:
    def test_get_isolation_empty(self, client: FlaskClient) -> None:
        resp = client.get("/settings/isolation")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["isolated_plugins"] == []

    def test_post_isolation_add_plugin(self, client: FlaskClient) -> None:
        resp = client.post("/settings/isolation", json={"plugin_id": "weather"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "weather" in data["isolated_plugins"]

    def test_post_isolation_duplicate(self, client: FlaskClient) -> None:
        """Adding the same plugin twice should not create duplicates."""
        client.post("/settings/isolation", json={"plugin_id": "weather"})
        resp = client.post("/settings/isolation", json={"plugin_id": "weather"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["isolated_plugins"].count("weather") == 1

    def test_post_isolation_trims_plugin_id(self, client: FlaskClient) -> None:
        resp = client.post("/settings/isolation", json={"plugin_id": " weather "})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "weather" in data["isolated_plugins"]
        assert " weather " not in data["isolated_plugins"]

    def test_delete_isolation_remove_plugin(self, client: FlaskClient) -> None:
        client.post("/settings/isolation", json={"plugin_id": "weather"})
        resp = client.delete("/settings/isolation", json={"plugin_id": "weather"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "weather" not in data["isolated_plugins"]

    @pytest.mark.parametrize(
        ("method", "request_kwargs", "status", "error"),
        [
            pytest.param(
                "post",
                {"data": "not json", "content_type": "application/json"},
                400,
                "Request body must be a JSON object",
                id="invalid-body",
            ),
            pytest.param(
                "post",
                {"json": {}},
                422,
                "plugin_id is required and must be a non-empty string",
                id="missing",
            ),
            pytest.param(
                "post",
                {"json": {"plugin_id": "  "}},
                422,
                "plugin_id is required and must be a non-empty string",
                id="blank",
            ),
            pytest.param(
                "post",
                {"json": {"plugin_id": 123}},
                422,
                "plugin_id is required and must be a non-empty string",
                id="not-a-string",
            ),
            pytest.param(
                "post",
                {"json": {"plugin_id": "nonexistent"}},
                422,
                "plugin_id must reference a registered plugin",
                id="unknown",
            ),
            pytest.param(
                "delete",
                {"json": {"plugin_id": "nonexistent"}},
                422,
                "plugin_id must reference a registered plugin",
                id="delete-unknown",
            ),
        ],
    )
    def test_isolation_refusal_keeps_the_saved_list(
        self,
        client: FlaskClient,
        device_config_dev: Any,
        method: str,
        request_kwargs: dict[str, Any],
        status: int,
        error: str,
    ) -> None:
        assert (
            client.post("/settings/isolation", json={"plugin_id": "weather"})
        ).status_code == 200

        resp = getattr(client, method)("/settings/isolation", **request_kwargs)
        assert resp.status_code == status
        assert resp.get_json()["error"] == error
        saved = json.loads(_saved_config_text(device_config_dev))
        assert saved["isolated_plugins"] == ["weather"]


# ---------------------------------------------------------------------------
# /settings/safe_reset (POST) - safe reset
# ---------------------------------------------------------------------------


class TestSafeReset:
    def test_safe_reset_success(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
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

    def test_safe_reset_preserves_name(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """Safe reset should preserve the device name."""
        original_name = device_config_dev.get_config("name")
        client.post("/settings/safe_reset")
        assert device_config_dev.get_config("name") == original_name

    def test_safe_reset_preserves_timezone(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        original_tz = device_config_dev.get_config("timezone")
        client.post("/settings/safe_reset")
        assert device_config_dev.get_config("timezone") == original_tz

    def test_safe_reset_leaves_a_config_the_device_can_start_with(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """Keys that were never set stay unset. Copying them in wrote null,
        which the schema rejects, so the next start exited."""
        assert device_config_dev.get_config("preview_size_mode") is None
        resp = client.post("/settings/safe_reset")
        assert resp.status_code == 200
        on_disk = json.loads(Path(device_config_dev.config_file).read_text())
        assert "preview_size_mode" not in on_disk
        restarted = _restart_config(device_config_dev)
        assert restarted.get_config("plugin_cycle_interval_seconds") == 3600

    def test_safe_reset_error(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        device_config_dev.update_value("plugin_cycle_interval_seconds", 600, write=True)
        before = _saved_config_text(device_config_dev)
        with patch.object(
            device_config_dev, "update_config", side_effect=RuntimeError("disk on fire")
        ):
            resp = client.post("/settings/safe_reset")
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["error"] == "An internal error occurred"
        assert body["details"]["context"] == "safe reset"
        assert "disk on fire" not in resp.get_data(as_text=True)
        assert _saved_config_text(device_config_dev) == before


# ---------------------------------------------------------------------------
# /settings/save_api_keys (POST) - save API keys
# ---------------------------------------------------------------------------


class TestSaveApiKeys:
    def test_save_api_keys_success(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
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

    def test_save_api_keys_empty_values_ignored(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        resp = client.post(
            "/settings/save_api_keys",
            data={
                "OPEN_AI_SECRET": "",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "OPEN_AI_SECRET" not in data["updated"]

    def test_save_api_keys_no_data(self, client: FlaskClient) -> None:
        resp = client.post("/settings/save_api_keys", data={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["updated"] == []

    def test_save_api_keys_error(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        with patch.object(
            device_config_dev, "set_env_key", side_effect=RuntimeError("disk on fire")
        ):
            resp = client.post(
                "/settings/save_api_keys",
                data={
                    "OPEN_AI_SECRET": "key",
                },
            )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["error"] == "An internal error occurred"
        assert body["details"]["context"] == "saving API keys"
        assert "disk on fire" not in resp.get_data(as_text=True)
        assert _env_file(device_config_dev).read_text() == ""


# ---------------------------------------------------------------------------
# /settings/delete_api_key (POST) - delete API key
# ---------------------------------------------------------------------------


class TestDeleteApiKey:
    def test_delete_api_key_success(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        resp = client.post("/settings/delete_api_key", data={"key": "OPEN_AI_SECRET"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    @pytest.mark.parametrize(
        "form",
        [pytest.param({"key": "EVIL_KEY"}, id="unknown"), pytest.param({}, id="none")],
    )
    def test_delete_api_key_refuses_a_name_it_does_not_manage(
        self, client: FlaskClient, device_config_dev: Any, form: dict[str, str]
    ) -> None:
        device_config_dev.set_env_key("NASA_SECRET", "keep-me")
        before = _env_file(device_config_dev).read_text()

        resp = client.post("/settings/delete_api_key", data=form)
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Invalid key name"
        assert _env_file(device_config_dev).read_text() == before
        assert device_config_dev.load_env_key("NASA_SECRET") == "keep-me"

    def test_delete_api_key_each_valid_key(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """Each managed key can be deleted, and only that key goes."""
        keys = (
            "OPEN_AI_SECRET",
            "OPEN_WEATHER_MAP_SECRET",
            "NASA_SECRET",
            "UNSPLASH_ACCESS_KEY",
            "GITHUB_SECRET",
            "GOOGLE_AI_SECRET",
        )
        for key in keys:
            device_config_dev.set_env_key(key, f"value-{key}")
        for i, key in enumerate(keys):
            resp = client.post("/settings/delete_api_key", data={"key": key})
            assert resp.status_code == 200, f"Failed for key={key}"
            assert resp.get_json()["message"] == f"Deleted {key}."
            env_text = _env_file(device_config_dev).read_text()
            assert f"value-{key}" not in env_text
            for kept in keys[i + 1 :]:
                assert f"value-{kept}" in env_text

    def test_delete_api_key_error(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        device_config_dev.set_env_key("OPEN_AI_SECRET", "keep-me")
        with patch.object(
            device_config_dev, "unset_env_key", side_effect=OSError("disk on fire")
        ):
            resp = client.post(
                "/settings/delete_api_key", data={"key": "OPEN_AI_SECRET"}
            )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["error"] == "An internal error occurred"
        assert "disk on fire" not in resp.get_data(as_text=True)
        assert device_config_dev.load_env_key("OPEN_AI_SECRET") == "keep-me"


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

    def test_save_settings_success(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        resp = client.post("/save_settings", data=self.VALID_FORM)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert device_config_dev.get_config("name") == "TestDevice"

    def test_save_settings_reconfigures_log_timezone(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import blueprints.settings._config as settings_config

        configured: list[str | None] = []
        monkeypatch.setattr(
            settings_config,
            "configure_log_timezone",
            lambda tz_name: configured.append(tz_name),
        )

        resp = client.post(
            "/save_settings",
            data={**self.VALID_FORM, "timezoneName": "America/Los_Angeles"},
        )

        assert resp.status_code == 200
        assert configured == ["America/Los_Angeles"]

    @pytest.mark.parametrize(
        ("changes", "field", "error"),
        [
            pytest.param(
                {"unit": None},
                "unit",
                "Plugin cycle interval unit is required",
                id="unit-missing",
            ),
            pytest.param(
                {"unit": "nanosecond"},
                "unit",
                "Plugin cycle interval unit is required",
                id="unit-unknown",
            ),
            pytest.param(
                {"interval": None},
                "interval",
                "Refresh interval is required",
                id="interval-missing",
            ),
            pytest.param(
                {"interval": "abc"},
                "interval",
                "Refresh interval must be a number",
                id="interval-text",
            ),
            pytest.param(
                {"timezoneName": ""},
                "timezoneName",
                "Time Zone is required",
                id="timezone-empty",
            ),
            pytest.param(
                {"timezoneName": None},
                "timezoneName",
                "Time Zone is required",
                id="timezone-missing",
            ),
            pytest.param(
                {"timeFormat": None},
                "timeFormat",
                "Time format is required",
                id="time-format-missing",
            ),
            pytest.param(
                {"timeFormat": "48h"},
                "timeFormat",
                "Time format is required",
                id="time-format-unknown",
            ),
            pytest.param(
                {"unit": "hour", "interval": "25"},
                "interval",
                "Plugin cycle interval must be 24 hours or less",
                id="interval-over-a-day",
            ),
        ],
    )
    def test_save_settings_refuses_an_invalid_form(
        self,
        client: FlaskClient,
        device_config_dev: Any,
        changes: dict[str, str | None],
        field: str,
        error: str,
    ) -> None:
        form = {**self.VALID_FORM, **changes}
        form = {k: v for k, v in form.items() if v is not None}
        before = _saved_config_text(device_config_dev)

        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["code"] == "validation_error"
        assert data["details"]["field"] == field
        assert data["error"] == error
        assert _saved_config_text(device_config_dev) == before

    def test_save_settings_hides_an_unexpected_error(
        self,
        client: FlaskClient,
        device_config_dev: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(*args: Any) -> None:
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(device_config_dev, "update_config", boom)
        before = _saved_config_text(device_config_dev)

        resp = client.post("/save_settings", data=self.VALID_FORM)
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["error"] == "An internal error occurred"
        assert body["code"] == "internal_error"
        assert body["details"]["context"] == "saving device settings"
        assert "disk on fire" not in resp.get_data(as_text=True)
        assert _saved_config_text(device_config_dev) == before

    def test_save_settings_with_inky_saturation(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        form = {**self.VALID_FORM, "inky_saturation": "0.7"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200
        img_settings = device_config_dev.get_config("image_settings")
        assert img_settings["inky_saturation"] == 0.7

    @pytest.mark.parametrize("mode", ["auto", "dithered"])
    def test_save_settings_with_screen_rendering(
        self, client: FlaskClient, device_config_dev: Any, mode: str
    ) -> None:
        form = {**self.VALID_FORM, "screen_rendering": mode}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200
        img_settings = device_config_dev.get_config("image_settings")
        assert img_settings["screen_rendering"] == mode

    def test_save_settings_rejects_unknown_screen_rendering(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        form = {**self.VALID_FORM, "screen_rendering": "sparkly"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422
        img_settings = device_config_dev.get_config("image_settings") or {}
        assert "screen_rendering" not in img_settings

    def test_settings_page_shows_screen_rendering_for_inky(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        device_config_dev.update_value("display_type", "inky")
        device_config_dev.update_value(
            "image_settings", {"screen_rendering": "dithered"}
        )
        html = client.get("/settings").get_data(as_text=True)
        assert 'name="screen_rendering"' in html
        assert '<option value="dithered" selected>' in html

    @pytest.mark.parametrize(
        ("previous", "woken"),
        [pytest.param(600, True, id="changed"), pytest.param(3600, False, id="same")],
    )
    def test_save_settings_wakes_the_loop_only_when_the_interval_changes(
        self,
        client: FlaskClient,
        device_config_dev: Any,
        monkeypatch: pytest.MonkeyPatch,
        previous: int,
        woken: bool,
    ) -> None:
        import blueprints.settings._config as settings_config

        wakes: list[str] = []
        monkeypatch.setattr(settings_config, "wake_refresh_loop", wakes.append)
        device_config_dev.update_value(
            "plugin_cycle_interval_seconds", previous, write=True
        )
        device_config_dev.update_value("timezone", "UTC", write=True)

        form = {**self.VALID_FORM, "unit": "hour", "interval": "1"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200
        assert device_config_dev.get_config("plugin_cycle_interval_seconds") == 3600
        assert wakes == (["saving device settings"] if woken else [])

    def test_save_settings_hour_unit(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        form = {**self.VALID_FORM, "unit": "hour", "interval": "2"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200
        assert resp.get_json()["message"] == "Saved settings."
        saved = _restart_config(device_config_dev)
        assert saved.get_config("plugin_cycle_interval_seconds") == 7200

    def test_save_without_orientation_keeps_the_saved_one(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """Orientation is optional on the form. Leaving it out used to write
        null, which the schema rejects at the next start."""
        device_config_dev.update_value("orientation", "vertical", write=True)
        form = {k: v for k, v in self.VALID_FORM.items() if k != "orientation"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200
        assert _restart_config(device_config_dev).get_config("orientation") == (
            "vertical"
        )

    def test_every_preview_size_on_the_page_survives_a_restart(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """Each preview size the settings page offers saves, and the saved
        file still loads. "Fit to container" used to fail the schema, which
        broke every render and stopped the next start."""
        html = client.get("/settings").get_data(as_text=True)
        offered = re.findall(r'name="previewSizeMode" value="([^"]+)"', html)
        assert "fit" in offered
        for mode in offered:
            form = {**self.VALID_FORM, "previewSizeMode": mode}
            resp = client.post("/save_settings", data=form)
            assert resp.status_code == 200, mode
            assert device_config_dev.get_config("preview_size_mode") == mode
            restarted = _restart_config(device_config_dev)
            assert restarted.get_config("preview_size_mode") == mode

    def test_save_settings_legacy_device_post(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """POST /settings/device should forward to save_settings."""
        resp = client.post("/settings/device", data=self.VALID_FORM)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    @pytest.mark.parametrize("path", ["/settings/device", "/settings/network"])
    def test_save_settings_legacy_pages_render_the_settings_form(
        self, client: FlaskClient, path: str
    ) -> None:
        resp = client.get(path)
        assert resp.status_code == 200
        assert 'name="deviceName"' in resp.get_data(as_text=True)

    def test_save_settings_legacy_display_post(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        form = {**self.VALID_FORM, "deviceName": "Legacy Display"}
        resp = client.post("/settings/display", data=form)
        assert resp.status_code == 200
        assert _restart_config(device_config_dev).get_config("name") == (
            "Legacy Display"
        )

    def test_save_settings_missing_device_name(self, client: FlaskClient) -> None:
        form = {**self.VALID_FORM}
        del form["deviceName"]
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["details"]["field"] == "deviceName"

    def test_save_settings_empty_device_name(self, client: FlaskClient) -> None:
        form = {**self.VALID_FORM, "deviceName": ""}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["details"]["field"] == "deviceName"

    def test_save_settings_whitespace_device_name(self, client: FlaskClient) -> None:
        form = {**self.VALID_FORM, "deviceName": "   "}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["details"]["field"] == "deviceName"

    def test_save_settings_zero_interval(self, client: FlaskClient) -> None:
        form = {**self.VALID_FORM, "interval": "0"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["details"]["field"] == "interval"

    def test_save_settings_checkbox_on_stores_true(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """Checkbox fields submitted as 'on' should be stored as boolean True."""
        form = {**self.VALID_FORM, "invertImage": "on", "logSystemStats": "on"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200
        assert device_config_dev.get_config("inverted_image") is True
        assert device_config_dev.get_config("log_system_stats") is True

    def test_save_settings_checkbox_absent_stores_false(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """Checkboxes not present in form (unchecked) should be stored as boolean False."""
        form = {**self.VALID_FORM}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200
        assert device_config_dev.get_config("inverted_image") is False
        assert device_config_dev.get_config("log_system_stats") is False

    def test_save_settings_checkbox_not_string_on(
        self, client: FlaskClient, device_config_dev: Any
    ) -> None:
        """Checkbox value other than 'on' should be stored as boolean False."""
        form = {**self.VALID_FORM, "invertImage": "yes", "logSystemStats": "true"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 200
        assert device_config_dev.get_config("inverted_image") is False
        assert device_config_dev.get_config("log_system_stats") is False

    def test_save_settings_negative_interval_accurate_error(
        self, client: FlaskClient
    ) -> None:
        """Negative interval should say 'must be at least 1', not 'is required'."""
        form = {**self.VALID_FORM, "interval": "-5"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["details"]["field"] == "interval"
        assert "at least 1" in data["error"]
        assert "required" not in data["error"].lower()

    def test_save_settings_non_integer_interval_error(
        self, client: FlaskClient
    ) -> None:
        """Non-numeric interval should say 'must be a number'."""
        form = {**self.VALID_FORM, "interval": "abc"}
        resp = client.post("/save_settings", data=form)
        assert resp.status_code == 422
        data = resp.get_json()
        assert "number" in data["error"].lower()
