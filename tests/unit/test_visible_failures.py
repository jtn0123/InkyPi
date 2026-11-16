"""Failures that used to be swallowed now show up, or stop doing harm.

- One playlist with an unreadable stored time window switched the overlap
  check off for every playlist, so overlapping playlists could be saved.
- A broken benchmark DB silently stopped recording benchmarks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from benchmarks import benchmark_storage


def _add_broken_then_morning(device_config: Any) -> None:
    pm = device_config.get_playlist_manager()
    pm.add_playlist("Broken", "06:00", "07:00")
    # Unreadable, and before "Morning". Only in memory: a config write refuses
    # such a time and the loader sets one aside, so this tests the overlap
    # check's own guard.
    pm.get_playlist("Broken").start_time = "25:99"
    pm.add_playlist("Morning", "08:00", "12:00")


def test_create_still_refuses_an_overlap_past_an_unreadable_playlist(
    client: FlaskClient, device_config_dev: Any, caplog: pytest.LogCaptureFixture
) -> None:
    _add_broken_then_morning(device_config_dev)

    with caplog.at_level(logging.WARNING):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": "Late", "start_time": "10:00", "end_time": "14:00"},
        )

    assert resp.status_code == 400
    assert "overlap" in resp.get_json()["error"].lower()
    assert "'Broken' has an unreadable time window" in caplog.text


def test_update_still_refuses_an_overlap_past_an_unreadable_playlist(
    client: FlaskClient, device_config_dev: Any
) -> None:
    _add_broken_then_morning(device_config_dev)
    device_config_dev.get_playlist_manager().add_playlist("Evening", "18:00", "20:00")

    resp = client.put(
        "/update_playlist/Evening",
        json={"new_name": "Evening", "start_time": "11:00", "end_time": "13:00"},
    )

    assert resp.status_code == 400
    assert "overlap" in resp.get_json()["error"].lower()


def test_an_unreadable_playlist_does_not_block_a_free_window(
    flask_app: Flask, client: FlaskClient, device_config_dev: Any
) -> None:
    # device.json edited by hand, then the service restarted.
    path = Path(device_config_dev.config_file)
    data = json.loads(path.read_text())
    data["playlist_config"]["playlists"] = [
        {"name": "Broken", "start_time": "25:99", "end_time": "07:00", "plugins": []},
        {"name": "Morning", "start_time": "08:00", "end_time": "12:00", "plugins": []},
    ]
    path.write_text(json.dumps(data))
    flask_app.config["DEVICE_CONFIG"] = type(device_config_dev)()

    free = client.post(
        "/create_playlist",
        json={"playlist_name": "Late", "start_time": "13:00", "end_time": "15:00"},
    )
    overlapping = client.post(
        "/create_playlist",
        json={"playlist_name": "Brunch", "start_time": "10:00", "end_time": "14:00"},
    )

    assert free.status_code == 200
    assert overlapping.status_code == 400


class _Config:
    def __init__(self, db_path: Path) -> None:
        self.BASE_DIR = str(db_path.parent)
        self._db_path = str(db_path)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._db_path if key == "benchmarks_db_path" else default


_EVENT = {"refresh_id": "r1", "plugin_id": "clock", "instance": "Clock"}


def test_a_broken_benchmark_db_is_reported_once_until_it_works_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(benchmark_storage._save_failures, "failing", False)
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("a file where the DB directory should be")
    broken = _Config(blocker / "benchmarks.db")
    working = _Config(tmp_path / "ok" / "benchmarks.db")
    caplog.set_level(logging.DEBUG, logger=benchmark_storage.__name__)

    benchmark_storage.save_refresh_event(broken, _EVENT)
    benchmark_storage.save_stage_event(broken, "r1", "generate_image", 12)
    benchmark_storage.save_stage_event(working, "r1", "generate_image", 12)

    levels = [(r.levelname, r.getMessage()) for r in caplog.records]
    assert levels[0][0] == "WARNING"
    assert levels[0][1].startswith("Could not save a refresh benchmark")
    assert levels[1][0] == "DEBUG"
    assert levels[1][1].startswith("Could not save the generate_image stage")
    assert levels[2] == ("INFO", "Benchmarks are being saved again")
    assert benchmark_storage._save_failures.failing is False
