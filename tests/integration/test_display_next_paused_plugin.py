""" "Display next" shows what "Next up" named, even with a plugin paused.

"Next up" and the refresh loop skip an instance the circuit breaker has
paused (until its retry is due), but both "Display next" routes took the
next eligible instance without that rule. The dashboard named one plugin,
the button showed the paused one, it failed again, and an error card went on
the panel. All of them now choose with ``PluginHealthTracker.skip_resting``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from refresh_task.health import PluginHealthTracker

_SHOWN, _PAUSED, _NEXT = "Clock shown", "Clock paused", "Clock next"


def _seed(device_config_dev: Any, *, paused_minutes_ago: float) -> None:
    """Default playlist: the shown clock, then a paused one, then a healthy one."""
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    playlist = pm.get_playlist("Default")
    for name in (_SHOWN, _PAUSED, _NEXT):
        playlist.add_plugin(
            {
                "plugin_id": "clock",
                "name": name,
                "plugin_settings": {},
                "refresh": {"interval": 300},
            }
        )
    paused = playlist.find_plugin("clock", _PAUSED)
    paused.paused = True
    paused.consecutive_failure_count = 5
    paused.disabled_reason = "Paused after 5 consecutive failures"
    paused.paused_at = (
        datetime.now(UTC) - timedelta(minutes=paused_minutes_ago)
    ).isoformat()
    playlist.current_plugin_index = 0  # the shown clock was on last
    device_config_dev.write_config()


def _next_up(client: FlaskClient) -> str:
    body = client.get("/next-up").get_json()
    assert body, "Next up should name a plugin"
    name = body["plugin_instance"]
    assert isinstance(name, str)
    return name


def _queue_on_a_running_loop(
    flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    """Run the loop path, recording which instance each request asks for."""
    refresh_task = flask_app.config["REFRESH_TASK"]
    monkeypatch.setattr(refresh_task, "running", True)
    asked: list[str] = []

    def manual_update(action: Any) -> dict[str, Any]:
        asked.append(action.plugin_instance.name)
        return {}

    monkeypatch.setattr(refresh_task, "manual_update", manual_update)
    return asked


@pytest.mark.parametrize(
    "request_display_next",
    [
        lambda c: c.post("/display-next"),
        lambda c: c.post(
            "/display_next_in_playlist", json={"playlist_name": "Default"}
        ),
    ],
    ids=["display-next", "display_next_in_playlist"],
)
def test_display_next_skips_a_paused_plugin_like_next_up(
    client: FlaskClient,
    flask_app: Flask,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
    request_display_next: Any,
) -> None:
    import blueprints.main as main

    _seed(device_config_dev, paused_minutes_ago=5)
    asked = _queue_on_a_running_loop(flask_app, monkeypatch)
    main._reset_display_next_cooldown()

    named = _next_up(client)
    resp = request_display_next(client)
    main._reset_display_next_cooldown()

    assert resp.status_code == 200, resp.get_json()
    assert named == _NEXT
    assert asked == [named]


def test_display_next_without_the_loop_skips_a_paused_plugin_like_next_up(
    client: FlaskClient,
    flask_app: Flask,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blueprints.main as main
    from plugins import plugin_registry

    flask_app.config["REFRESH_TASK"].running = False
    _seed(device_config_dev, paused_minutes_ago=5)

    class Plugin:
        def generate_image(self, settings: object, config: object) -> Image.Image:
            return Image.new("RGB", (8, 8), "white")

    monkeypatch.setattr(plugin_registry, "get_plugin_instance", lambda c: Plugin())
    monkeypatch.setattr(
        flask_app.config["DISPLAY_MANAGER"], "display_image", lambda *a, **k: None
    )
    main._reset_display_next_cooldown()

    named = _next_up(client)
    resp = client.post("/display-next")
    main._reset_display_next_cooldown()

    assert resp.status_code == 200, resp.get_json()
    assert named == _NEXT
    assert device_config_dev.get_refresh_info().plugin_instance == named


def test_a_paused_plugin_due_its_retry_is_next_everywhere(
    client: FlaskClient,
    flask_app: Flask,
    device_config_dev: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the cooldown has run out, the paused plugin's turn is its retry,
    for "Next up" and "Display next" alike."""
    import blueprints.main as main

    cooldown_min = (PluginHealthTracker.pause_cooldown_seconds() or 0) / 60
    _seed(device_config_dev, paused_minutes_ago=cooldown_min + 1)
    asked = _queue_on_a_running_loop(flask_app, monkeypatch)
    main._reset_display_next_cooldown()

    named = _next_up(client)
    resp = client.post("/display-next")
    main._reset_display_next_cooldown()

    assert resp.status_code == 200, resp.get_json()
    assert named == _PAUSED
    assert asked == [named]
