"""Editing an instance's settings retires the picture drawn with the old ones.

Playlist turns reuse an instance's cached picture until its own refresh
interval (up to a day) runs out. A settings change must make the next turn
render a new picture; saving the same settings again must not, since that
can cost a paid API call (AI image, AI text).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Flask
from flask.testing import FlaskClient

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
