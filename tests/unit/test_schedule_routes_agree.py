"""The dashboard and the playlist pages predict the refresh the loop will make (A1).

Both used to add the cycle to the last *successful* refresh. After a failed
or skipped turn the loop waits a cycle from that attempt, so the pages showed
"Due now" for a whole cycle while nothing happened.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import Flask
from flask.testing import FlaskClient

from blueprints.playlist._schedule import _playlist_next_due, _safe_until_next_min
from model import Playlist, RefreshInfo
from utils.time_utils import now_device_tz

NOW = datetime.fromisoformat("2026-11-15T08:00:00+00:00")


def _pl(name: str = "Default") -> Any:
    return type("Pl", (), {"name": name})()


def test_next_due_counts_a_later_failed_attempt() -> None:
    due = _playlist_next_due(
        _pl(),
        last_refresh=NOW - timedelta(minutes=20),
        last_refresh_playlist="Default",
        last_attempt=NOW - timedelta(minutes=5),
        cycle_seconds=900,
        now=NOW,
    )

    assert due == NOW + timedelta(minutes=10)
    assert _safe_until_next_min(due, 15, NOW) == 10


def test_only_the_last_refreshed_playlist_has_a_due_time() -> None:
    due = _playlist_next_due(
        _pl("Evening"),
        last_refresh=NOW,
        last_refresh_playlist="Default",
        last_attempt=None,
        cycle_seconds=900,
        now=NOW,
    )

    assert due is None
    assert _safe_until_next_min(None, 15, NOW) == 15


def test_routes_show_the_loops_next_refresh_after_a_failed_turn(
    flask_app: Flask, client: FlaskClient
) -> None:
    device_config = flask_app.config["DEVICE_CONFIG"]
    playlist = Playlist(
        "Focus",
        "00:00",
        "24:00",
        plugins=[
            {"plugin_id": "clock", "name": name, "plugin_settings": {}, "refresh": {}}
            for name in ("Clock A", "Clock B")
        ],
        cycle_interval_seconds=600,
    )
    device_config.get_playlist_manager().playlists.append(playlist)
    cycle = 600.0
    now = now_device_tz(device_config)
    # Refreshed 1.5 cycles ago; the turn a cycle later failed, so the loop
    # next acts half a cycle from now, not "Due now".
    refreshed = now - timedelta(seconds=1.5 * cycle)
    device_config.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id=playlist.plugins[0].plugin_id,
        refresh_time=refreshed.isoformat(),
        image_hash=None,
        playlist=playlist.name,
        plugin_instance=playlist.plugins[0].name,
    )
    flask_app.config["REFRESH_TASK"].scheduler.last_attempt = refreshed + timedelta(
        seconds=cycle
    )
    expected = refreshed + timedelta(seconds=2 * cycle)

    info = client.get("/refresh-info").get_json()
    eta = client.get(f"/playlist/eta/{playlist.name}").get_json()["eta"]

    assert datetime.fromisoformat(info["next_refresh_time"]) == expected
    assert info["next_refresh_relative"] != "Due now"
    soonest = min(entry["minutes"] for entry in eta.values())
    assert abs(soonest - (expected - now).total_seconds() // 60) <= 1
