"""A backup with a playlist that breaks the playlist rules is refused whole.

Restoring a backup whose playlist started at ``25:00`` used to succeed; the
refresh loop then failed every time it chose the active playlist, so the
screen silently stopped changing. The import now checks every playlist with
the device config schema's rules, the ones device.json loads by, and refuses
the backup with a message naming the playlist before anything is written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient


def _playlist(name: str, start: str, end: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "start_time": start,
        "end_time": end,
        "plugins": [
            {
                "plugin_id": "clock",
                "name": "Clock",
                "plugin_settings": {},
                "refresh": {"interval": 300},
            }
        ],
        **extra,
    }


def _backup(*playlists: dict[str, Any]) -> dict[str, Any]:
    return {
        "config": {
            "name": "Restored",
            "playlist_config": {
                "playlists": list(playlists),
                "active_playlist": None,
            },
        },
        "env_keys": {"NASA_SECRET": "from-the-backup"},
    }


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("25:00", "23:00", "start time '25:00' is not a time from 00:00 to 24:00"),
        ("06:00", "24:30", "end time '24:30' is not a time from 00:00 to 24:00"),
        ("6:00", "08:00", "start time '6:00' is not a time from 00:00 to 24:00"),
    ],
)
def test_a_backup_with_a_bad_playlist_time_is_refused_before_saving(
    client: FlaskClient, device_config_dev: Any, start: str, end: str, message: str
) -> None:
    config_file = Path(device_config_dev.config_file)
    before_file = config_file.read_text()
    before_playlists = device_config_dev.get_playlist_manager().to_dict()

    resp = client.post(
        "/settings/import",
        json=_backup(
            _playlist("Day", "06:00", "22:00"), _playlist("Evening", start, end)
        ),
    )

    assert resp.status_code == 400
    error = resp.get_json()["error"]
    assert error == (
        f"Backup has an invalid playlist 'Evening': {message}. Nothing was restored."
    )
    # Nothing was saved: not the settings, the playlists or the API key.
    assert config_file.read_text() == before_file
    assert device_config_dev.get_config("name") != "Restored"
    assert device_config_dev.get_playlist_manager().to_dict() == before_playlists
    assert device_config_dev.load_env_key("NASA_SECRET") is None


def test_a_backup_with_a_broken_plugin_entry_is_refused(
    client: FlaskClient, device_config_dev: Any
) -> None:
    playlist = _playlist("Day", "06:00", "22:00")
    del playlist["plugins"][0]["plugin_settings"]

    resp = client.post("/settings/import", json=_backup(playlist))

    assert resp.status_code == 400
    error = resp.get_json()["error"]
    assert error.startswith("Backup has an invalid playlist 'Day': plugins.0:")
    assert "'plugin_settings' is a required property" in error


def test_a_backup_with_good_playlist_times_restores(
    client: FlaskClient, device_config_dev: Any
) -> None:
    resp = client.post(
        "/settings/import",
        json=_backup(
            _playlist("Night", "22:00", "06:00"), _playlist("Day", "00:00", "24:00")
        ),
    )

    assert resp.status_code == 200, resp.get_json()
    manager = device_config_dev.get_playlist_manager()
    assert manager.get_playlist_names() == ["Night", "Day"]
    saved = json.loads(Path(device_config_dev.config_file).read_text())
    assert [p["start_time"] for p in saved["playlist_config"]["playlists"]] == [
        "22:00",
        "00:00",
    ]
