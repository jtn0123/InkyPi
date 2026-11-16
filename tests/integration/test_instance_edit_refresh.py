"""Editing an instance's settings retires the picture drawn with the old ones.

Both ways of saving settings are covered: "Update instance" on a playlist
instance, and "Save settings" on the plugin page, which keeps the plugin's
``<plugin>_saved_settings`` instance in the Default playlist.

Playlist turns reuse an instance's cached picture until its own refresh
interval (up to a day) runs out. A settings change must make the next turn
render a new picture; saving the same settings again must not, since that
can cost a paid API call (AI image, AI text).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

_NAME = "Hall clock"


def _instance(flask_app: Flask) -> Any:
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    return pm.find_plugin("clock", _NAME)


def _add_rendered_clock(flask_app: Flask) -> str:
    device_config = flask_app.config["DEVICE_CONFIG"]
    pm = device_config.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default")
    pm.get_playlist("Default").add_plugin(
        {
            "plugin_id": "clock",
            "name": _NAME,
            "plugin_settings": {"selectedClockFace": "Gradient Clock"},
            "refresh": {"interval": 86400},
        }
    )
    rendered_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    _instance(flask_app).latest_refresh_time = rendered_at
    device_config.write_config()
    return rendered_at


def _save(client: FlaskClient, face: str) -> Any:
    return client.put(
        f"/update_plugin_instance/{_NAME}",
        data={"plugin_id": "clock", "selectedClockFace": face},
    )


def test_changed_settings_render_a_new_picture_on_the_next_turn(
    client: FlaskClient, flask_app: Flask
) -> None:
    _add_rendered_clock(flask_app)

    assert _save(client, "Digital Clock").status_code == 200

    instance = _instance(flask_app)
    assert instance.settings["selectedClockFace"] == "Digital Clock"
    assert instance.latest_refresh_time is None
    assert instance.should_refresh(datetime.now(UTC))

    # The reset is saved, so a restart doesn't bring the old picture back.
    reloaded = type(flask_app.config["DEVICE_CONFIG"])()
    on_disk = reloaded.get_playlist_manager().find_plugin("clock", _NAME)
    assert on_disk.latest_refresh_time is None


def test_saving_the_same_settings_keeps_the_current_picture(
    client: FlaskClient, flask_app: Flask
) -> None:
    rendered_at = _add_rendered_clock(flask_app)

    assert _save(client, "Gradient Clock").status_code == 200

    instance = _instance(flask_app)
    assert instance.latest_refresh_time == rendered_at
    assert not instance.should_refresh(datetime.now(UTC))


# --- "Save settings" on the plugin page (the <plugin>_saved_settings entry) ---

_SAVED = "clock_saved_settings"


def _saved_instance(flask_app: Flask) -> Any:
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    return pm.find_plugin("clock", _SAVED)


def _add_saved_settings_with_cached_picture(flask_app: Flask) -> str:
    """Seed the Save-settings instance as if it rendered 5 minutes ago."""
    device_config = flask_app.config["DEVICE_CONFIG"]
    pm = device_config.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default")
    pm.get_playlist("Default").add_plugin(
        {
            "plugin_id": "clock",
            "name": _SAVED,
            "plugin_settings": {"selectedClockFace": "Gradient Clock"},
            "refresh": {"interval": 86400},
        }
    )
    instance = _saved_instance(flask_app)
    rendered_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    instance.latest_refresh_time = rendered_at
    cached = Path(device_config.plugin_image_dir) / instance.get_image_path()
    cached.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), "red").save(cached)
    device_config.write_config()
    return rendered_at


def _save_settings(client: FlaskClient, face: str) -> Any:
    return client.post(
        "/save_plugin_settings",
        data={"plugin_id": "clock", "selectedClockFace": face},
    )


class _Renderer:
    """Stands in for the clock plugin; draws blue so it differs from the cache."""

    def __init__(self) -> None:
        self.settings_seen: list[dict[str, object]] = []

    def generate_image(
        self, settings: Mapping[str, object], device_config: object
    ) -> Image.Image | None:
        self.settings_seen.append(dict(settings))
        return Image.new("RGB", (8, 8), "blue")


def _next_turn(flask_app: Flask, renderer: _Renderer) -> Image.Image | None:
    """Run the Default playlist's next (scheduled, not forced) turn of it."""
    from refresh_task.actions import PlaylistRefresh

    device_config = flask_app.config["DEVICE_CONFIG"]
    playlist = device_config.get_playlist_manager().get_playlist("Default")
    action = PlaylistRefresh(playlist, _saved_instance(flask_app))
    return action.execute(renderer, device_config, datetime.now(UTC))


def test_save_settings_with_changes_renders_a_new_picture_on_the_next_turn(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_saved_settings_with_cached_picture(flask_app)
    wakes: list[str] = []
    monkeypatch.setattr(
        flask_app.config["REFRESH_TASK"],
        "signal_config_change",
        lambda: wakes.append("wake"),
    )

    resp = _save_settings(client, "Digital Clock")

    assert resp.status_code == 200
    body = resp.get_json()
    # It is already in the Default playlist; nothing is left to add.
    assert "Add to Playlist" not in body["message"]
    assert "Default playlist" in body["message"]
    # The loop re-plans now rather than at the end of its current wait.
    assert wakes == ["wake"]

    renderer = _Renderer()
    image = _next_turn(flask_app, renderer)

    assert renderer.settings_seen == [{"selectedClockFace": "Digital Clock"}]
    assert image is not None and image.getpixel((0, 0)) == (0, 0, 255)

    # The reset was saved, so a restart doesn't bring the old picture back.
    reloaded = type(flask_app.config["DEVICE_CONFIG"])()
    on_disk = reloaded.get_playlist_manager().find_plugin("clock", _SAVED)
    assert on_disk.latest_refresh_time is None


def test_save_settings_with_no_changes_keeps_the_cached_picture(
    client: FlaskClient, flask_app: Flask
) -> None:
    rendered_at = _add_saved_settings_with_cached_picture(flask_app)

    assert _save_settings(client, "Gradient Clock").status_code == 200

    assert _saved_instance(flask_app).latest_refresh_time == rendered_at
    renderer = _Renderer()
    image = _next_turn(flask_app, renderer)
    assert renderer.settings_seen == []
    assert image is not None and image.getpixel((0, 0)) == (255, 0, 0)
