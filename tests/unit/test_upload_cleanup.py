"""Uploaded files that no setting refers to are deleted after a day (G2)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import refresh_task.housekeeping as housekeeping
from refresh_task.housekeeping import RefreshHousekeeper
from utils.upload_cleanup import UNREFERENCED_GRACE_S, prune_unreferenced_uploads

NOW = 2_000_000_000.0
OLD = NOW - UNREFERENCED_GRACE_S - 60


def _upload(folder: Path, name: str, mtime: float = OLD) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"x")
    os.utime(path, (mtime, mtime))
    return path


def test_deletes_only_old_files_nothing_refers_to(tmp_path: Path) -> None:
    saved = tmp_path / "saved"
    used = _upload(saved, "1_used.jpg")
    unused = _upload(saved, "2_unused.jpg")
    fresh = _upload(saved, "3_fresh.jpg", mtime=NOW - 60)
    (saved / "subdir").mkdir()
    # Stored under another install root: the name alone counts as a reference.
    settings = {
        "playlist_config": {
            "playlists": [
                {
                    "plugins": [
                        {"plugin_settings": {"imageFiles[]": ["/old/src/1_used.jpg"]}}
                    ]
                }
            ]
        }
    }

    removed = prune_unreferenced_uploads(str(saved), [settings], now=NOW)

    assert removed == 1
    assert used.exists()
    assert not unused.exists()
    assert fresh.exists()
    assert (saved / "subdir").is_dir()


def test_missing_upload_folder_is_not_an_error(tmp_path: Path) -> None:
    assert prune_unreferenced_uploads(str(tmp_path / "nope"), [{}], now=NOW) == 0


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    saved = tmp_path / "saved"
    monkeypatch.setattr(housekeeping, "get_upload_dir", lambda: str(saved))
    return saved


def test_housekeeper_keeps_files_named_by_unsaved_playlist_changes(
    device_config_dev: Any, upload_dir: Path
) -> None:
    kept = _upload(upload_dir, "1_kept.jpg", mtime=1.0)
    dropped = _upload(upload_dir, "2_dropped.jpg", mtime=1.0)
    manager = device_config_dev.get_playlist_manager()
    manager.add_playlist("Photos")
    assert manager.add_plugin_to_playlist(
        "Photos",
        {
            "plugin_id": "image_upload",
            "name": "Album",
            "plugin_settings": {"imageFiles[]": [str(kept)]},
            "refresh": {"interval": 300},
        },
    )

    RefreshHousekeeper(device_config_dev, MagicMock()).maybe_prune_uploads(
        tick_count=10, cleanup_interval_ticks=10
    )

    assert kept.exists()
    assert not dropped.exists()


def test_housekeeper_waits_for_the_cleanup_tick(
    device_config_dev: Any, upload_dir: Path
) -> None:
    unused = _upload(upload_dir, "1_unused.jpg", mtime=1.0)
    RefreshHousekeeper(device_config_dev, MagicMock()).maybe_prune_uploads(
        tick_count=7, cleanup_interval_ticks=10
    )
    assert unused.exists()


def test_housekeeper_deletes_nothing_when_references_cannot_be_read(
    upload_dir: Path,
) -> None:
    unused = _upload(upload_dir, "1_unused.jpg", mtime=1.0)
    config = MagicMock()
    config.get_config.return_value = {}
    config.get_playlist_manager.side_effect = RuntimeError("mid-edit")

    RefreshHousekeeper(config, MagicMock()).maybe_prune_uploads(
        tick_count=10, cleanup_interval_ticks=10
    )

    assert unused.exists()


def test_refresh_loop_prunes_uploads_with_history_cleanup() -> None:
    from refresh_task.loop_scheduling import SchedulingMixin

    task: Any = SchedulingMixin.__new__(SchedulingMixin)
    task.housekeeper = MagicMock()
    task._tick_count = 20

    task._maybe_run_history_cleanup()

    task.housekeeper.maybe_prune_uploads.assert_called_once_with(
        tick_count=20, cleanup_interval_ticks=10
    )
