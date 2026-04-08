"""Tests for src/utils/history_cleanup.py (JTN-361)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

from utils.history_cleanup import CleanupResult, cleanup_history

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(directory: Path, name: str, age_seconds: float = 0) -> Path:
    """Create a dummy PNG file with an mtime offset from now."""
    path = directory / name
    path.write_bytes(b"\x00" * 1024)  # 1 KB
    mtime = time.time() - age_seconds
    os.utime(path, (mtime, mtime))
    return path


def _make_pair(directory: Path, stem: str, age_seconds: float = 0) -> tuple[Path, Path]:
    """Create a PNG + sidecar JSON pair."""
    png = _make_png(directory, f"{stem}.png", age_seconds)
    sidecar = directory / f"{stem}.json"
    sidecar.write_text("{}", encoding="utf-8")
    mtime = time.time() - age_seconds
    os.utime(sidecar, (mtime, mtime))
    return png, sidecar


# ---------------------------------------------------------------------------
# Empty directory is a no-op
# ---------------------------------------------------------------------------


def test_empty_dir_is_noop(tmp_path):
    result = cleanup_history(str(tmp_path))
    assert result.deleted_count == 0
    assert result.freed_bytes == 0
    assert result.remaining_count == 0


def test_nonexistent_dir_returns_empty_result(tmp_path):
    result = cleanup_history(str(tmp_path / "nonexistent"))
    assert result.deleted_count == 0


# ---------------------------------------------------------------------------
# max_age_days
# ---------------------------------------------------------------------------


def test_max_age_deletes_old_files(tmp_path):
    """Files older than max_age_days should be removed."""
    _make_png(tmp_path, "old.png", age_seconds=31 * 86400)  # 31 days old
    _make_png(tmp_path, "new.png", age_seconds=1 * 86400)  # 1 day old

    result = cleanup_history(
        str(tmp_path), max_age_days=30, max_count=0, min_free_bytes=0
    )

    assert result.deleted_count == 1
    assert not (tmp_path / "old.png").exists()
    assert (tmp_path / "new.png").exists()
    assert result.remaining_count == 1


def test_max_age_deletes_sidecar_too(tmp_path):
    """When an old PNG is deleted its JSON sidecar must go too."""
    png, sidecar = _make_pair(
        tmp_path, "display_20200101_000000", age_seconds=40 * 86400
    )

    result = cleanup_history(
        str(tmp_path), max_age_days=30, max_count=0, min_free_bytes=0
    )

    assert result.deleted_count == 1
    assert not png.exists()
    assert not sidecar.exists()


def test_max_age_zero_disables_age_check(tmp_path):
    """max_age_days=0 should leave all files untouched."""
    _make_png(tmp_path, "ancient.png", age_seconds=365 * 86400)

    result = cleanup_history(
        str(tmp_path), max_age_days=0, max_count=0, min_free_bytes=0
    )

    assert result.deleted_count == 0
    assert (tmp_path / "ancient.png").exists()


# ---------------------------------------------------------------------------
# max_count
# ---------------------------------------------------------------------------


def test_max_count_keeps_newest(tmp_path):
    """When over the limit, oldest files should be deleted first."""
    for i in range(5):
        _make_png(tmp_path, f"img_{i:02d}.png", age_seconds=(5 - i) * 3600)

    # Keep only the 3 newest
    result = cleanup_history(
        str(tmp_path), max_age_days=0, max_count=3, min_free_bytes=0
    )

    assert result.deleted_count == 2
    assert result.remaining_count == 3
    # The 2 oldest (largest age_seconds) should be gone
    assert not (tmp_path / "img_00.png").exists()
    assert not (tmp_path / "img_01.png").exists()
    # The 3 newest should remain
    assert (tmp_path / "img_02.png").exists()
    assert (tmp_path / "img_03.png").exists()
    assert (tmp_path / "img_04.png").exists()


def test_max_count_zero_disables_count_check(tmp_path):
    """max_count=0 should leave all files untouched."""
    for i in range(10):
        _make_png(tmp_path, f"img_{i}.png")

    result = cleanup_history(
        str(tmp_path), max_age_days=0, max_count=0, min_free_bytes=0
    )

    assert result.deleted_count == 0
    assert result.remaining_count == 10


def test_max_count_under_limit_is_noop(tmp_path):
    """If file count <= max_count, nothing should be deleted."""
    for i in range(3):
        _make_png(tmp_path, f"img_{i}.png")

    result = cleanup_history(
        str(tmp_path), max_age_days=0, max_count=10, min_free_bytes=0
    )

    assert result.deleted_count == 0
    assert result.remaining_count == 3


# ---------------------------------------------------------------------------
# min_free_bytes
# ---------------------------------------------------------------------------


def test_min_free_bytes_triggers_when_disk_full(tmp_path):
    """When free space is below the threshold, oldest files should be evicted."""
    # Create 5 files, 1 KB each; oldest first
    for i in range(5):
        _make_png(tmp_path, f"img_{i:02d}.png", age_seconds=(5 - i) * 3600)

    # Simulate near-full disk: free=100 bytes, threshold=500 MB
    fake_usage = type("DiskUsage", (), {"total": 10**9, "used": 10**9, "free": 100})()

    with patch("utils.history_cleanup.shutil.disk_usage", return_value=fake_usage):
        result = cleanup_history(
            str(tmp_path), max_age_days=0, max_count=0, min_free_bytes=500_000_000
        )

    # All 5 files should have been deleted (still under threshold, but no more files)
    assert result.deleted_count == 5


def test_min_free_bytes_zero_disables_space_check(tmp_path):
    """min_free_bytes=0 should disable the free-space eviction pass."""
    _make_png(tmp_path, "img.png")
    fake_usage = type("DiskUsage", (), {"total": 10**9, "used": 10**9, "free": 0})()

    with patch("utils.history_cleanup.shutil.disk_usage", return_value=fake_usage):
        result = cleanup_history(
            str(tmp_path), max_age_days=0, max_count=0, min_free_bytes=0
        )

    assert result.deleted_count == 0


def test_min_free_bytes_not_triggered_when_space_ok(tmp_path):
    """If free space is already above the threshold, no files should be deleted."""
    for i in range(5):
        _make_png(tmp_path, f"img_{i}.png")

    # Plenty of free space
    fake_usage = type(
        "DiskUsage", (), {"total": 10**10, "used": 1000, "free": 10**10}
    )()

    with patch("utils.history_cleanup.shutil.disk_usage", return_value=fake_usage):
        result = cleanup_history(
            str(tmp_path), max_age_days=0, max_count=0, min_free_bytes=500_000_000
        )

    assert result.deleted_count == 0
    assert result.remaining_count == 5


# ---------------------------------------------------------------------------
# Symlink safety
# ---------------------------------------------------------------------------


def test_symlinks_are_skipped(tmp_path):
    """Symlinks inside history_dir must never be followed or deleted."""
    # Create a real file outside the history dir
    outside = tmp_path / "secret.txt"
    outside.write_text("sensitive data", encoding="utf-8")

    history_dir = tmp_path / "history"
    history_dir.mkdir()

    # Create a symlink pointing outside
    link = history_dir / "evil.png"
    link.symlink_to(outside)

    result = cleanup_history(
        str(history_dir),
        max_age_days=1,
        max_count=1,
        min_free_bytes=0,
    )

    assert result.skipped_symlinks == 1
    assert result.deleted_count == 0
    assert outside.exists(), "Real file outside history dir must not be removed"


# ---------------------------------------------------------------------------
# Files outside history_dir are untouched
# ---------------------------------------------------------------------------


def test_no_files_outside_history_dir_deleted(tmp_path):
    """The cleanup must never touch files that aren't inside history_dir."""
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    other_dir = tmp_path / "other"
    other_dir.mkdir()

    # File inside history (old enough to be evicted)
    _make_png(history_dir, "old.png", age_seconds=60 * 86400)
    # File outside history with a .png name
    external = other_dir / "external.png"
    external.write_bytes(b"\x00" * 1024)

    result = cleanup_history(
        str(history_dir), max_age_days=30, max_count=0, min_free_bytes=0
    )

    assert result.deleted_count == 1
    assert external.exists(), "External file must not be deleted"


# ---------------------------------------------------------------------------
# CleanupResult dataclass defaults
# ---------------------------------------------------------------------------


def test_cleanup_result_defaults():
    r = CleanupResult()
    assert r.deleted_count == 0
    assert r.freed_bytes == 0
    assert r.remaining_count == 0
    assert r.skipped_symlinks == 0
    assert r.errors == []
