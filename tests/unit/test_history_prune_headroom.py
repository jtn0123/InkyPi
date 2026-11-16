"""A history scan at the cap prunes below it, so the next saves skip the scan (G8).

Once history reached ``max_count``, pruning kept exactly ``max_count`` entries.
Every later save then put it one over the cap again and listed and stat'ed
the whole folder (about 130 ms on the Pi) to delete a single file.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import display.display_manager as display_manager_mod
from display.display_manager import DisplayManager
from utils.history_cleanup import CleanupResult, cleanup_history


def _fill(history_dir: Path, count: int, start: int = 0) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    for i in range(start, start + count):
        png = history_dir / f"display_{i:05d}.png"
        png.write_bytes(b"img")
        os.utime(png, (1_000_000 + i, 1_000_000 + i))


def _png_names(history_dir: Path) -> list[str]:
    return sorted(name for name in os.listdir(history_dir) if name.endswith(".png"))


@pytest.fixture(autouse=True)
def _fresh_estimate() -> Iterator[None]:
    DisplayManager._history_count_estimate = None
    DisplayManager._history_increment_count = 0
    yield
    DisplayManager._history_count_estimate = None
    DisplayManager._history_increment_count = 0


@pytest.fixture
def scans(monkeypatch: pytest.MonkeyPatch) -> list[CleanupResult]:
    """Record every folder scan the display manager runs."""
    seen: list[CleanupResult] = []

    def counting_cleanup(*args: Any, **kwargs: Any) -> CleanupResult:
        result = cleanup_history(*args, **kwargs)
        seen.append(result)
        return result

    monkeypatch.setattr(display_manager_mod, "cleanup_history", counting_cleanup)
    return seen


def test_a_scan_at_the_cap_leaves_room_for_the_next_25_saves(
    device_config_dev: Any, tmp_path: Path, scans: list[CleanupResult]
) -> None:
    device_config_dev.update_value("history_cleanup", {"max_count": 500})
    history_dir = tmp_path / "prune"
    _fill(history_dir, 501)
    dm = DisplayManager(device_config_dev)

    dm._prune_history(str(history_dir))

    assert len(scans) == 1
    names = _png_names(history_dir)
    assert len(names) == 475
    # The oldest are the ones removed.
    assert names[0] == "display_00026.png"

    # The next 25 saves fill the room back up to the cap without a scan...
    for i in range(25):
        _fill(history_dir, 1, start=501 + i)
        dm._prune_history(str(history_dir))
    assert len(scans) == 1
    assert len(_png_names(history_dir)) == 500

    # ...and the save after them, the first one over the cap, scans again.
    _fill(history_dir, 1, start=526)
    dm._prune_history(str(history_dir))
    assert len(scans) == 2
    assert len(_png_names(history_dir)) == 475


@pytest.mark.parametrize(("max_count", "kept"), [(100, 90), (9, 9), (1, 1)])
def test_a_small_cap_keeps_at_most_a_tenth_of_room(
    device_config_dev: Any,
    tmp_path: Path,
    scans: list[CleanupResult],
    max_count: int,
    kept: int,
) -> None:
    device_config_dev.update_value("history_cleanup", {"max_count": max_count})
    history_dir = tmp_path / "prune"
    _fill(history_dir, max_count + 5)

    DisplayManager(device_config_dev)._prune_history(str(history_dir))

    names = _png_names(history_dir)
    assert len(names) == kept
    # The newest entry, the one just saved, is always kept.
    assert names[-1] == f"display_{max_count + 4:05d}.png"


def test_history_under_the_cap_is_not_trimmed(
    device_config_dev: Any, tmp_path: Path, scans: list[CleanupResult]
) -> None:
    device_config_dev.update_value("history_cleanup", {"max_count": 500})
    history_dir = tmp_path / "prune"
    _fill(history_dir, 500)

    DisplayManager(device_config_dev)._prune_history(str(history_dir))

    assert len(scans) == 1
    assert len(_png_names(history_dir)) == 500


@pytest.mark.parametrize(("trim_to", "kept"), [(2, 2), (10, 5), (-3, 0), (None, 5)])
def test_cleanup_trim_to_is_clamped_to_the_cap(
    tmp_path: Path, trim_to: int | None, kept: int
) -> None:
    history_dir = tmp_path / "history"
    _fill(history_dir, 8)

    result = cleanup_history(
        str(history_dir),
        max_age_days=0,
        max_count=5,
        min_free_bytes=0,
        trim_to=trim_to,
    )

    assert result.remaining_count == kept
    assert len(_png_names(history_dir)) == kept


def test_cleanup_trim_to_does_nothing_at_or_under_the_cap(tmp_path: Path) -> None:
    history_dir = tmp_path / "history"
    _fill(history_dir, 5)

    result = cleanup_history(
        str(history_dir), max_age_days=0, max_count=5, min_free_bytes=0, trim_to=2
    )

    assert result.deleted_count == 0
    assert len(_png_names(history_dir)) == 5
