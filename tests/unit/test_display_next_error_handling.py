"""Tests for display-next error handling (JTN-178).

Verifies that generate_image RuntimeError returns 400 with a useful message
instead of a generic 500, and that missing plugin config returns 404.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image


def _fixed_now(_device_config: Any) -> Any:
    return datetime(2025, 1, 1, 8, 0, 0, tzinfo=UTC)


def _add_playlist_with_plugin(device_config: Any) -> None:
    pm = device_config.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config.write_config()


class TestGenerateImageRuntimeError:
    """When generate_image raises RuntimeError, endpoint returns 400."""

    @pytest.mark.integration
    def test_generate_image_runtime_error_returns_400(
        self,
        client: FlaskClient,
        device_config_dev: Any,
        monkeypatch: pytest.MonkeyPatch,
        flask_app: Flask,
    ) -> None:
        flask_app.config["REFRESH_TASK"].running = False
        _add_playlist_with_plugin(device_config_dev)
        monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

        from plugins import plugin_registry

        class _FailingPlugin:
            def generate_image(self, settings: Any, device_config: Any) -> None:
                raise RuntimeError("API key missing for clock plugin")

        monkeypatch.setattr(
            plugin_registry,
            "get_plugin_instance",
            lambda cfg: _FailingPlugin(),
            raising=True,
        )

        resp = client.post("/display-next")
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        # Generic message only — raw exception detail must not leak
        # (CodeQL py/stack-trace-exposure).
        assert body["error"] == "Plugin image generation failed"
        assert "API key missing for clock plugin" not in resp.get_data(as_text=True)

    @pytest.mark.integration
    def test_generate_image_runtime_error_does_not_trigger_cooldown(
        self,
        client: FlaskClient,
        device_config_dev: Any,
        monkeypatch: pytest.MonkeyPatch,
        flask_app: Flask,
    ) -> Any:
        """A failed generate_image should not consume the rate-limit window."""
        flask_app.config["REFRESH_TASK"].running = False
        _add_playlist_with_plugin(device_config_dev)
        monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

        from plugins import plugin_registry

        call_count = {"n": 0}

        class _FailOnceThenSucceed:
            def generate_image(self, settings: Any, device_config: Any) -> Any:
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise RuntimeError("transient failure")
                return Image.new("RGB", (800, 480), "white")

        monkeypatch.setattr(
            plugin_registry,
            "get_plugin_instance",
            lambda cfg: _FailOnceThenSucceed(),
            raising=True,
        )

        displayed = {"called": False}

        def _display_image(
            image: Any, image_settings: Any = None, history_meta: Any = None
        ) -> None:
            displayed["called"] = True

        flask_app.config["DISPLAY_MANAGER"].display_image = _display_image

        # First call: RuntimeError -> 400
        resp1 = client.post("/display-next")
        assert resp1.status_code == 400

        # Second call should NOT be rate-limited (error didn't set cooldown)
        resp2 = client.post("/display-next")
        assert resp2.status_code == 200
        assert displayed["called"] is True


class TestPluginConfigNotFound:
    """When plugin config is missing, endpoint returns 404."""

    @pytest.mark.integration
    def test_missing_plugin_config_returns_404(
        self,
        client: FlaskClient,
        device_config_dev: Any,
        monkeypatch: pytest.MonkeyPatch,
        flask_app: Flask,
    ) -> None:
        flask_app.config["REFRESH_TASK"].running = False
        _add_playlist_with_plugin(device_config_dev)
        monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

        # Patch get_plugin to return None, simulating missing config
        monkeypatch.setattr(
            device_config_dev,
            "get_plugin",
            lambda plugin_id: None,
            raising=True,
        )

        resp = client.post("/display-next")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body["success"] is False
        assert body["error"] == "Plugin config not found"


class TestManualUpdateFailure:
    """When manual_update raises, endpoint returns 400 with message."""

    @pytest.mark.integration
    def test_manual_update_exception_returns_400(
        self,
        client: FlaskClient,
        device_config_dev: Any,
        monkeypatch: pytest.MonkeyPatch,
        flask_app: Flask,
    ) -> None:
        flask_app.config["REFRESH_TASK"].running = True
        _add_playlist_with_plugin(device_config_dev)
        monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

        def _failing_manual_update(playlist_refresh: Any) -> None:
            raise RuntimeError("background task crashed")

        flask_app.config["REFRESH_TASK"].manual_update = _failing_manual_update

        resp = client.post("/display-next")
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        # Generic message only — raw exception detail must not leak
        # (CodeQL py/stack-trace-exposure).
        assert body["error"] == "Plugin update failed"
        assert "background task crashed" not in resp.get_data(as_text=True)
