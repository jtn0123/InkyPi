"""The history sidecar index re-reads only what changed (G8)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from utils import history_index

_HOUR_NS = 3600 * 1_000_000_000


@pytest.fixture(autouse=True)
def _fresh_index() -> Iterator[None]:
    history_index.clear()
    yield
    history_index.clear()


@pytest.fixture
def parses(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every sidecar the index actually opens."""
    seen: list[str] = []
    real_parse = history_index._parse

    def _counting(path: str, name: str) -> history_index.HistoryEntry | None:
        seen.append(name)
        return real_parse(path, name)

    monkeypatch.setattr(history_index, "_parse", _counting)
    return seen


def _sidecar(folder: Path, stamp: str, **meta: object) -> Path:
    path = folder / f"display_{stamp}.json"
    path.write_text(json.dumps(meta), encoding="utf-8")
    return path


def _settle(folder: Path) -> None:
    """Backdate the folder so a snapshot of it is outside the racy window."""
    stat = folder.stat()
    os.utime(folder, ns=(stat.st_atime_ns - _HOUR_NS, stat.st_mtime_ns - _HOUR_NS))


def test_entries_are_newest_first_and_skip_unreadable_files(tmp_path: Path) -> None:
    _sidecar(tmp_path, "20261115_080000", plugin_id="clock", refresh_time="t1")
    _sidecar(tmp_path, "20261115_090000", plugin_id="apod", plugin_instance="NASA")
    (tmp_path / "display_20261115_100000.json").write_text("{not json")
    (tmp_path / "display_20261115_110000.json").write_text("[1, 2]")
    (tmp_path / "display_20261115_090000.png").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("ignored")

    found = history_index.entries(str(tmp_path))

    assert [e.name for e in found] == [
        "display_20261115_090000.json",
        "display_20261115_080000.json",
    ]
    assert found[0].plugin_instance == "NASA"
    assert found[0].image_name == "display_20261115_090000.png"
    assert found[1].refresh_time == "t1"


def test_an_unchanged_folder_is_not_read_again(
    tmp_path: Path, parses: list[str]
) -> None:
    _sidecar(tmp_path, "20261115_080000", plugin_id="clock")
    _settle(tmp_path)

    first = history_index.entries(str(tmp_path))
    second = history_index.entries(str(tmp_path))

    assert second is first
    assert parses == ["display_20261115_080000.json"]


def test_a_new_sidecar_is_the_only_file_parsed(
    tmp_path: Path, parses: list[str]
) -> None:
    _sidecar(tmp_path, "20261115_080000", plugin_id="clock")
    _settle(tmp_path)
    history_index.entries(str(tmp_path))
    parses.clear()

    _sidecar(tmp_path, "20261115_090000", plugin_id="apod")
    found = history_index.entries(str(tmp_path))

    assert parses == ["display_20261115_090000.json"]
    assert [e.plugin_id for e in found] == ["apod", "clock"]


def test_a_sidecar_rewritten_in_place_is_read_again(tmp_path: Path) -> None:
    path = _sidecar(tmp_path, "20261115_080000", plugin_id="clock")
    history_index.entries(str(tmp_path))

    path.write_text(json.dumps({"plugin_id": "weather", "pad": "x" * 10}))
    found = history_index.entries(str(tmp_path))

    assert [e.plugin_id for e in found] == ["weather"]


def test_a_sidecar_read_mid_write_appears_once_written(tmp_path: Path) -> None:
    # The display manager creates the file, then writes it. Creating it
    # changes the folder; writing it does not.
    path = tmp_path / "display_20261115_080000.json"
    path.write_text("")
    assert history_index.entries(str(tmp_path)) == ()

    path.write_text(json.dumps({"plugin_id": "clock"}))

    assert [e.plugin_id for e in history_index.entries(str(tmp_path))] == ["clock"]


def test_a_snapshot_taken_just_after_a_change_is_rechecked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sidecar(tmp_path, "20261115_080000", plugin_id="clock")
    scans: list[str] = []
    real_scan = history_index._scan

    def _counting_scan(
        history_dir: str,
        folder_mtime_ns: int,
        previous: history_index._Snapshot | None,
    ) -> history_index._Snapshot:
        scans.append("scan")
        return real_scan(history_dir, folder_mtime_ns, previous)

    monkeypatch.setattr(history_index, "_scan", _counting_scan)

    history_index.entries(str(tmp_path))
    history_index.entries(str(tmp_path))

    assert scans == ["scan", "scan"]


def test_a_missing_folder_has_no_entries(tmp_path: Path) -> None:
    assert history_index.entries(str(tmp_path / "absent")) == ()


def test_only_a_few_folders_are_remembered(tmp_path: Path) -> None:
    for index in range(history_index._MAX_FOLDERS + 2):
        folder = tmp_path / str(index)
        folder.mkdir()
        history_index.entries(str(folder))

    assert len(history_index._snapshots) == history_index._MAX_FOLDERS
    assert str(tmp_path / "0") not in history_index._snapshots
