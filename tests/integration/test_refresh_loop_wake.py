"""Changes to what the frame shows wake the refresh loop.

The loop sleeps for a wait worked out from the playlists and the device
interval, up to 24 hours. A change that is saved but never signalled only
takes effect when that sleep runs out, so every route that changes the
schedule must wake the loop once it has saved, and must not wake it when
the change was refused.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient


@pytest.fixture
def wakes(flask_app: Flask, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(
        flask_app.config["REFRESH_TASK"],
        "signal_config_change",
        lambda: calls.append("wake"),
    )
    return calls


def _create(client: FlaskClient, name: str, start: str, end: str) -> Any:
    return client.post(
        "/create_playlist",
        json={"playlist_name": name, "start_time": start, "end_time": end},
    )


def _add_clock(client: FlaskClient, instance_name: str) -> Any:
    return client.post(
        "/add_plugin",
        data={
            "plugin_id": "clock",
            "refresh_settings": json.dumps(
                {
                    "playlist": "Default",
                    "instance_name": instance_name,
                    "refreshType": "interval",
                    "unit": "minute",
                    "interval": 10,
                }
            ),
        },
    )


def _import_payload(plugin_id: str) -> dict[str, Any]:
    return {
        "version": 1,
        "exported_at": "2026-01-01T00:00:00+00:00",
        "instances": [{"plugin_id": plugin_id, "name": "Imported", "settings": {}}],
    }


def test_creating_a_playlist_wakes_the_loop(
    client: FlaskClient, wakes: list[str]
) -> None:
    assert _create(client, "Evening", "18:00", "22:00").status_code == 200
    assert wakes == ["wake"]


def test_a_refused_playlist_does_not_wake_the_loop(
    client: FlaskClient, wakes: list[str]
) -> None:
    assert _create(client, "Evening", "18:00", "22:00").status_code == 200
    wakes.clear()

    assert _create(client, "Evening", "06:00", "08:00").status_code == 400
    assert wakes == []


def test_updating_a_playlist_wakes_the_loop(
    client: FlaskClient, wakes: list[str]
) -> None:
    assert _create(client, "Evening", "18:00", "22:00").status_code == 200
    wakes.clear()

    resp = client.put(
        "/update_playlist/Evening",
        json={"new_name": "Night", "start_time": "20:00", "end_time": "23:00"},
    )
    assert resp.status_code == 200
    assert wakes == ["wake"]


def test_updating_a_missing_playlist_does_not_wake_the_loop(
    client: FlaskClient, wakes: list[str]
) -> None:
    resp = client.put(
        "/update_playlist/NoSuch",
        json={"new_name": "Other", "start_time": "01:00", "end_time": "02:00"},
    )
    assert resp.status_code == 400
    assert wakes == []


def test_deleting_a_playlist_wakes_the_loop(
    client: FlaskClient, wakes: list[str]
) -> None:
    assert _create(client, "Evening", "18:00", "22:00").status_code == 200
    wakes.clear()

    assert client.delete("/delete_playlist/Evening").status_code == 200
    assert wakes == ["wake"]


def test_deleting_a_missing_playlist_does_not_wake_the_loop(
    client: FlaskClient, wakes: list[str]
) -> None:
    assert client.delete("/delete_playlist/NoSuch").status_code == 404
    assert wakes == []


def test_adding_a_plugin_to_a_playlist_wakes_the_loop(
    client: FlaskClient, wakes: list[str]
) -> None:
    assert _add_clock(client, "Kitchen Clock").status_code == 200
    assert wakes == ["wake"]


def test_a_refused_plugin_does_not_wake_the_loop(
    client: FlaskClient, wakes: list[str]
) -> None:
    assert _add_clock(client, "Kitchen Clock").status_code == 200
    wakes.clear()

    assert _add_clock(client, "Kitchen Clock").status_code == 400
    assert wakes == []


def test_importing_plugins_wakes_the_loop(
    client: FlaskClient, wakes: list[str]
) -> None:
    resp = client.post("/api/plugins/import", json=_import_payload("clock"))
    assert resp.status_code == 200
    assert resp.get_json()["imported"] == 1
    assert wakes == ["wake"]


def test_an_import_that_adds_nothing_does_not_wake_the_loop(
    client: FlaskClient, wakes: list[str]
) -> None:
    resp = client.post(
        "/api/plugins/import", json=_import_payload("nonexistent_plugin_xyz")
    )
    assert resp.status_code == 200
    assert resp.get_json()["imported"] == 0
    assert wakes == []


_SETTINGS_FORM = {
    "deviceName": "Frame",
    "orientation": "horizontal",
    "invertImage": "",
    "logSystemStats": "",
    "timezoneName": "UTC",
    "timeFormat": "24h",
    "interval": "15",
    "unit": "minute",
    "saturation": "1.0",
    "brightness": "1.0",
    "sharpness": "1.0",
    "contrast": "1.0",
}


def test_changing_the_timezone_wakes_the_loop(
    client: FlaskClient, flask_app: Flask, wakes: list[str]
) -> None:
    """Playlist windows are in device time, so a new timezone moves them."""
    assert client.post("/save_settings", data=_SETTINGS_FORM).status_code == 200
    wakes.clear()

    form = dict(_SETTINGS_FORM, timezoneName="America/Los_Angeles")
    assert client.post("/save_settings", data=form).status_code == 200
    assert wakes == ["wake"]


def test_saving_unchanged_timing_does_not_wake_the_loop(
    client: FlaskClient, wakes: list[str]
) -> None:
    assert client.post("/save_settings", data=_SETTINGS_FORM).status_code == 200
    wakes.clear()

    form = dict(_SETTINGS_FORM, deviceName="Hallway")
    assert client.post("/save_settings", data=form).status_code == 200
    assert wakes == []


def test_a_failed_wake_still_reports_the_saved_change(
    client: FlaskClient,
    flask_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The change is on disk; only its timing is late, so say so in the log."""

    def broken_wake() -> None:
        raise RuntimeError("loop is gone")

    monkeypatch.setattr(
        flask_app.config["REFRESH_TASK"], "signal_config_change", broken_wake
    )
    with caplog.at_level(logging.ERROR, logger="blueprints._refresh_loop"):
        resp = _create(client, "Evening", "18:00", "22:00")

    assert resp.status_code == 200
    pm = flask_app.config["DEVICE_CONFIG"].get_playlist_manager()
    assert pm.get_playlist("Evening") is not None
    assert "Could not wake the refresh loop after creating a playlist" in caplog.text


def test_settings_save_survives_a_failed_wake(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new interval is saved even when the loop cannot be woken."""

    def broken_wake() -> None:
        raise RuntimeError("loop is gone")

    monkeypatch.setattr(
        flask_app.config["REFRESH_TASK"], "signal_config_change", broken_wake
    )
    form = dict(_SETTINGS_FORM, interval="45")
    assert client.post("/save_settings", data=form).status_code == 200
    device_config = flask_app.config["DEVICE_CONFIG"]
    assert device_config.get_config("plugin_cycle_interval_seconds") == 45 * 60
