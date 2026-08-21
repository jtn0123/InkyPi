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


def _add_empty_playlist(device_config: Any) -> None:
    pm = device_config.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    device_config.write_config()


@pytest.mark.integration
def test_display_next_returns_metrics(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> Any:
    flask_app.config["REFRESH_TASK"].running = False

    _add_playlist_with_plugin(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    from plugins import plugin_registry

    class _StubPlugin:
        def generate_image(self, settings: Any, device_config: Any) -> Any:
            return Image.new("RGB", (800, 480), "white")

    monkeypatch.setattr(
        plugin_registry, "get_plugin_instance", lambda cfg: _StubPlugin(), raising=True
    )

    displayed = {"called": False}

    def _display_image(
        image: Any, image_settings: Any = None, history_meta: Any = None
    ) -> None:
        displayed["called"] = True

    flask_app.config["DISPLAY_MANAGER"].display_image = _display_image

    resp = client.post("/display-next")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("success") is True
    assert displayed["called"] is True
    metrics = body.get("metrics")
    assert isinstance(metrics, dict)
    for key in ("request_ms", "generate_ms", "preprocess_ms", "display_ms"):
        assert key in metrics
    assert metrics["generate_ms"] is not None


@pytest.mark.integration
def test_display_next_no_playlist_returns_error(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> None:
    flask_app.config["REFRESH_TASK"].running = False
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    pm = device_config_dev.get_playlist_manager()
    monkeypatch.setattr(pm, "determine_active_playlist", lambda dt: None, raising=True)

    resp = client.post("/display-next")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body.get("success") is False
    assert body.get("error") == "No active playlist"

    retry = client.post("/display-next")
    assert retry.status_code == 400
    assert retry.get_json()["error"] == "No active playlist"


@pytest.mark.integration
def test_display_next_no_plugin_returns_error(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> None:
    flask_app.config["REFRESH_TASK"].running = False
    _add_empty_playlist(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    resp = client.post("/display-next")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body.get("success") is False
    assert body.get("error") == "No eligible plugin to display"

    retry = client.post("/display-next")
    assert retry.status_code == 400
    assert retry.get_json()["error"] == "No eligible plugin to display"
