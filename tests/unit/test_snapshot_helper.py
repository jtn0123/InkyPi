"""Tests for the snapshot helper's failure-artifact behaviour.

Verifies that ``assert_image_snapshot`` saves the actual PNG to
``tests/snapshots/actual/<plugin>/<case>.png`` when a snapshot mismatch
is detected, so CI can upload the file as a GitHub Actions artifact.
"""

from __future__ import annotations

import pytest
from PIL import Image
from tests.snapshots.snapshot_helper import (
    _image_sha256,
    assert_image_snapshot,
    save_snapshot,
)


@pytest.fixture()
def _snapshot_sandbox(tmp_path, monkeypatch):
    """Redirect snapshot roots to a temp directory for isolation."""
    monkeypatch.setattr("tests.snapshots.snapshot_helper._SNAPSHOTS_ROOT", tmp_path)
    monkeypatch.setattr(
        "tests.snapshots.snapshot_helper._ACTUAL_ROOT", tmp_path / "actual"
    )
    return tmp_path


def _make_image(color: tuple[int, int, int] = (255, 0, 0)) -> Image.Image:
    """Create a small solid-colour test image."""
    return Image.new("RGB", (10, 10), color)


class TestSnapshotMismatchSavesActual:
    """assert_image_snapshot must persist the actual PNG on mismatch."""

    def test_actual_png_and_diff_written_on_mismatch(self, _snapshot_sandbox):
        sandbox = _snapshot_sandbox
        plugin, case = "test_plugin", "my_case"

        # Create a baseline from a red image.
        baseline = _make_image((255, 0, 0))
        save_snapshot(baseline, plugin, case)

        # Now assert with a different (green) image — should fail.
        actual = _make_image((0, 255, 0))
        with pytest.raises(AssertionError, match="Snapshot mismatch"):
            assert_image_snapshot(actual, plugin, case)

        # The actual PNG must have been saved.
        actual_png = sandbox / "actual" / plugin / f"{case}.png"
        assert actual_png.exists(), f"Expected actual PNG at {actual_png}"
        diff_png = sandbox / "actual" / plugin / f"{case}.diff.png"
        assert diff_png.exists(), f"Expected diff PNG at {diff_png}"
        diff_stats = sandbox / "actual" / plugin / f"{case}.diff.json"
        assert diff_stats.exists(), f"Expected diff stats JSON at {diff_stats}"

        # Verify the saved image matches the actual image.
        saved = Image.open(actual_png)
        assert _image_sha256(saved) == _image_sha256(actual)

    def test_error_message_mentions_artifact(self, _snapshot_sandbox):
        plugin, case = "test_plugin", "hint_case"

        baseline = _make_image((255, 0, 0))
        save_snapshot(baseline, plugin, case)

        actual = _make_image((0, 0, 255))
        with pytest.raises(AssertionError, match="snapshot-failures") as exc_info:
            assert_image_snapshot(actual, plugin, case)

        # Also verify the hint about the CI artifact.
        assert "'snapshot-failures' artifact" in str(exc_info.value)

    def test_small_delta_within_tolerance_passes(self, _snapshot_sandbox, monkeypatch):
        plugin, case = "test_plugin", "threshold_case"
        monkeypatch.setenv("SNAPSHOT_CHANNEL_THRESHOLD", "10")
        monkeypatch.setenv("SNAPSHOT_MAX_CHANGED_PCT", "0.5")

        baseline = _make_image((100, 100, 100))
        save_snapshot(baseline, plugin, case)

        # One-channel delta = 2 at every pixel; below threshold=10.
        actual = _make_image((102, 100, 100))
        assert_image_snapshot(actual, plugin, case)

    def test_no_actual_png_on_match(self, _snapshot_sandbox):
        sandbox = _snapshot_sandbox
        plugin, case = "test_plugin", "match_case"

        img = _make_image((128, 128, 128))
        save_snapshot(img, plugin, case)

        # Same image — should pass without saving anything to actual/.
        assert_image_snapshot(img, plugin, case)

        actual_dir = sandbox / "actual"
        assert not actual_dir.exists() or not any(actual_dir.rglob("*.png"))
