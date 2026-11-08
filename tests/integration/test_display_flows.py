# pyright: reportMissingImports=false
from datetime import UTC, datetime
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from model import RefreshInfo


def _fixed_now(_device_config: Any) -> Any:
    return datetime(2025, 1, 1, 8, 0, 0, tzinfo=UTC)


def _prepare_playlist(device_config_dev: Any) -> None:
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    # Two instances so we can see rotation and ensure one is "Displayed Now"
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "Weather B",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time="2025-01-01T07:55:00+00:00",
        image_hash=0,
        playlist="Default",
        plugin_instance="Clock A",
    )
    device_config_dev.write_config()


def _simulate_running_refresh_task(
    flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> list[Any]:
    """Make REFRESH_TASK accept manual updates without a real loop thread."""
    rt = flask_app.config["REFRESH_TASK"]
    calls: list[Any] = []

    def _manual_update(action: Any) -> dict[str, Any]:
        calls.append(action)
        return {}

    monkeypatch.setattr(rt, "running", True)
    monkeypatch.setattr(rt, "manual_update", _manual_update)
    return calls


def test_display_plugin_instance_endpoint_success(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> None:
    _prepare_playlist(device_config_dev)
    calls = _simulate_running_refresh_task(flask_app, monkeypatch)

    resp = client.post(
        "/display_plugin_instance",
        json={
            "playlist_name": "Default",
            "plugin_id": "clock",
            "plugin_instance": "Clock A",
        },
    )
    assert resp.status_code == 200
    assert resp.json.get("success") is True
    assert len(calls) == 1


def test_display_plugin_instance_returns_503_when_refresh_task_stopped(
    client: FlaskClient, device_config_dev: Any, flask_app: Flask
) -> None:
    """B2: a stopped refresh task must not be reported as "Display updated"."""
    _prepare_playlist(device_config_dev)
    assert flask_app.config["REFRESH_TASK"].running is False

    resp = client.post(
        "/display_plugin_instance",
        json={
            "playlist_name": "Default",
            "plugin_id": "clock",
            "plugin_instance": "Clock A",
        },
    )
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["success"] is False
    assert body["code"] == "refresh_task_unavailable"
    assert body["error"] == "Display refresh service is not running"


def test_display_next_in_playlist_success(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> None:
    _prepare_playlist(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    calls = _simulate_running_refresh_task(flask_app, monkeypatch)

    resp = client.post("/display_next_in_playlist", json={"playlist_name": "Default"})
    assert resp.status_code == 200
    assert resp.json.get("success") is True
    assert resp.json.get("playlist") == "Default"
    assert len(calls) == 1
    assert device_config_dev.get_playlist_manager().active_playlist == "Default"


def test_display_next_in_playlist_returns_503_when_refresh_task_stopped(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> None:
    """B2: nothing is displayed, so the active playlist must not change either."""
    _prepare_playlist(device_config_dev)
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Other", "00:00", "24:00")
    pm.get_playlist("Other").add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock O",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    before = pm.active_playlist
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    assert flask_app.config["REFRESH_TASK"].running is False

    resp = client.post("/display_next_in_playlist", json={"playlist_name": "Other"})
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["success"] is False
    assert body["code"] == "refresh_task_unavailable"
    assert pm.active_playlist == before
    assert pm.active_playlist != "Other"


def test_main_display_next_happy_path(
    client: FlaskClient,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    flask_app: Flask,
) -> Any:
    # Force direct path by marking refresh_task.running = False
    rt = flask_app.config["REFRESH_TASK"]
    rt.running = False

    _prepare_playlist(device_config_dev)
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)

    # Stub plugin generation and display to avoid heavy work/network
    from plugins import plugin_registry

    class _StubPlugin:
        def generate_image(self, settings: Any, device_config: Any) -> Any:
            return Image.new("RGB", (800, 480), "white")

    monkeypatch.setattr(
        plugin_registry, "get_plugin_instance", lambda cfg: _StubPlugin(), raising=True
    )
    called = {"displayed": False}

    def _display_image(
        image: Any, image_settings: Any = None, history_meta: Any = None
    ) -> None:
        called["displayed"] = True

    flask_app.config["DISPLAY_MANAGER"].display_image = _display_image

    resp = client.post("/display-next")
    assert resp.status_code == 200
    assert resp.json.get("success") is True
    assert called["displayed"] is True
