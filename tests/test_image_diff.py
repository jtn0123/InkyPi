"""Tests for scripts/image_diff.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------


def _load_script(script_name: str):
    """Load a scripts/ module by file path, avoiding sys.path pollution."""
    scripts_dir = Path(__file__).parent.parent / "scripts"
    spec = importlib.util.spec_from_file_location(
        script_name, scripts_dir / f"{script_name}.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def imdiff():
    """Return the image_diff module."""
    return _load_script("image_diff")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _solid_image(color: tuple, size: tuple = (10, 10)) -> Image.Image:
    """Create a solid-color RGBA image."""
    img = Image.new("RGBA", size, color)
    return img


def _save_image(img: Image.Image, path: Path) -> Path:
    """Save PIL image to path and return path as str-compatible."""
    img.save(path)
    return path


# ---------------------------------------------------------------------------
# Unit-level tests (compute_diff, build_diff_image, resize_to_match)
# ---------------------------------------------------------------------------


class TestComputeDiff:
    def test_identical_images_zero_changed(self, imdiff):
        img = _solid_image((100, 150, 200, 255))
        total, changed, max_delta = imdiff.compute_diff(img, img, threshold=5)
        assert changed == 0
        assert total == 100  # 10x10
        assert max_delta == 0

    def test_completely_different_images(self, imdiff):
        img_a = _solid_image((0, 0, 0, 255))
        img_b = _solid_image((255, 255, 255, 255))
        total, changed, max_delta = imdiff.compute_diff(img_a, img_b, threshold=5)
        assert changed == total
        assert max_delta == 255

    def test_single_pixel_changed(self, imdiff):
        size = (5, 5)
        img_a = _solid_image((100, 100, 100, 255), size)
        # Create img_b with one pixel changed significantly
        img_b = img_a.copy()
        pixels = img_b.load()
        pixels[2, 2] = (200, 100, 100, 255)  # channel delta = 100 > threshold 5
        total, changed, max_delta = imdiff.compute_diff(img_a, img_b, threshold=5)
        assert changed == 1
        assert total == 25
        assert max_delta == 100

    def test_below_threshold_treated_as_unchanged(self, imdiff):
        img_a = _solid_image((100, 100, 100, 255))
        img_b = _solid_image((103, 100, 100, 255))  # delta = 3, threshold = 5
        total, changed, max_delta = imdiff.compute_diff(img_a, img_b, threshold=5)
        assert changed == 0
        assert max_delta == 3

    def test_exactly_at_threshold_treated_as_unchanged(self, imdiff):
        img_a = _solid_image((100, 100, 100, 255))
        img_b = _solid_image((105, 100, 100, 255))  # delta = 5, threshold = 5
        _total, changed, _max_delta = imdiff.compute_diff(img_a, img_b, threshold=5)
        assert changed == 0

    def test_one_above_threshold_treated_as_changed(self, imdiff):
        img_a = _solid_image((100, 100, 100, 255))
        img_b = _solid_image((106, 100, 100, 255))  # delta = 6 > threshold 5
        _total, changed, _max_delta = imdiff.compute_diff(img_a, img_b, threshold=5)
        assert changed == 100  # all 10x10 pixels changed


class TestResizeToMatch:
    def test_same_size_no_resize(self, imdiff):
        img_a = _solid_image((0, 0, 0, 255), (20, 30))
        img_b = _solid_image((255, 255, 255, 255), (20, 30))
        result = imdiff.resize_to_match(img_a, img_b)
        assert result.size == (20, 30)

    def test_different_size_resizes_b(self, imdiff):
        img_a = _solid_image((0, 0, 0, 255), (20, 30))
        img_b = _solid_image((255, 255, 255, 255), (40, 60))
        result = imdiff.resize_to_match(img_a, img_b)
        assert result.size == img_a.size


class TestBuildDiffImage:
    def test_diff_image_same_size_as_a(self, imdiff):
        img_a = _solid_image((100, 100, 100, 255), (8, 8))
        img_b = _solid_image((200, 100, 100, 255), (8, 8))  # all pixels differ
        diff = imdiff.build_diff_image(img_a, img_b, threshold=5)
        assert isinstance(diff, Image.Image)
        assert diff.size == img_a.size

    def test_identical_images_diff_matches_original(self, imdiff):
        img_a = _solid_image((100, 150, 200, 255), (6, 6))
        diff = imdiff.build_diff_image(img_a, img_a, threshold=5)
        # No changed pixels — diff should look the same as img_a
        assert diff.tobytes() == img_a.tobytes()

    def test_changed_pixels_get_red_tint(self, imdiff):
        img_a = _solid_image((0, 0, 0, 255), (4, 4))
        img_b = _solid_image((255, 255, 255, 255), (4, 4))
        diff = imdiff.build_diff_image(img_a, img_b, threshold=5)
        pixels = diff.load()
        r, g, b, _a = pixels[0, 0]
        # Red channel should be elevated (50% blend of 0 + 255 = ~127)
        assert r > 100
        # Green and blue should be low (50% blend of 0 + 0)
        assert g == 0
        assert b == 0


# ---------------------------------------------------------------------------
# Integration tests via run()
# ---------------------------------------------------------------------------


class TestRun:
    def test_identical_images_zero_percent(self, imdiff, tmp_path):
        img = _solid_image((128, 64, 32, 255), (10, 10))
        path_a = str(_save_image(img, tmp_path / "a.png"))
        path_b = str(_save_image(img, tmp_path / "b.png"))

        stats = imdiff.run([path_a, path_b, "--summary-only"])
        assert stats["changed_pixels"] == 0
        assert stats["change_percentage"] == 0.0

    def test_single_pixel_changed_count_one(self, imdiff, tmp_path):
        size = (5, 5)
        img_a = _solid_image((50, 50, 50, 255), size)
        img_b = img_a.copy()
        px = img_b.load()
        px[0, 0] = (200, 50, 50, 255)  # big change at one pixel

        path_a = str(_save_image(img_a, tmp_path / "a.png"))
        path_b = str(_save_image(img_b, tmp_path / "b.png"))

        stats = imdiff.run([path_a, path_b, "--summary-only"])
        assert stats["changed_pixels"] == 1
        assert stats["total_pixels"] == 25

    def test_below_threshold_no_change(self, imdiff, tmp_path):
        img_a = _solid_image((100, 100, 100, 255))
        img_b = _solid_image((102, 100, 100, 255))  # delta=2 < threshold=5
        path_a = str(_save_image(img_a, tmp_path / "a.png"))
        path_b = str(_save_image(img_b, tmp_path / "b.png"))

        stats = imdiff.run([path_a, path_b, "--summary-only"])
        assert stats["changed_pixels"] == 0

    def test_resize_handling(self, imdiff, tmp_path):
        img_a = _solid_image((0, 0, 0, 255), (10, 10))
        img_b = _solid_image((0, 0, 0, 255), (20, 20))  # different size
        path_a = str(_save_image(img_a, tmp_path / "a.png"))
        path_b = str(_save_image(img_b, tmp_path / "b.png"))

        stats = imdiff.run([path_a, path_b, "--summary-only"])
        assert stats["total_pixels"] == 100  # resized to 10x10

    def test_diff_png_output_is_valid(self, imdiff, tmp_path):
        img_a = _solid_image((10, 20, 30, 255), (8, 8))
        img_b = _solid_image((200, 20, 30, 255), (8, 8))
        path_a = str(_save_image(img_a, tmp_path / "a.png"))
        path_b = str(_save_image(img_b, tmp_path / "b.png"))
        out = str(tmp_path / "diff.png")

        stats = imdiff.run([path_a, path_b, "--output", out])
        assert Path(out).exists()
        diff_img = Image.open(out)
        assert diff_img.size == (8, 8)
        assert stats["diff_output"] == out

    def test_summary_only_skips_png_write(self, imdiff, tmp_path):
        img = _solid_image((0, 0, 0, 255))
        path = str(_save_image(img, tmp_path / "img.png"))
        out = str(tmp_path / "should_not_exist.png")

        stats = imdiff.run([path, path, "--output", out, "--summary-only"])
        assert not Path(out).exists()
        assert stats["diff_output"] is None

    def test_json_output_format(self, imdiff, tmp_path, capsys):
        img = _solid_image((10, 10, 10, 255))
        path = str(_save_image(img, tmp_path / "img.png"))

        stats = imdiff.run([path, path, "--summary-only", "--json"])
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        assert "total_pixels" in parsed
        assert "changed_pixels" in parsed
        assert "change_percentage" in parsed
        assert "max_channel_delta" in parsed
        assert "threshold" in parsed
        assert parsed["changed_pixels"] == 0
        # Returned dict should match printed JSON
        assert parsed["total_pixels"] == stats["total_pixels"]

    def test_custom_threshold_applied(self, imdiff, tmp_path):
        img_a = _solid_image((100, 100, 100, 255))
        img_b = _solid_image((110, 100, 100, 255))  # delta=10
        path_a = str(_save_image(img_a, tmp_path / "a.png"))
        path_b = str(_save_image(img_b, tmp_path / "b.png"))

        # With threshold=5: delta 10 > 5 → all pixels changed
        stats_low = imdiff.run([path_a, path_b, "--threshold", "5", "--summary-only"])
        assert stats_low["changed_pixels"] == 100

        # With threshold=15: delta 10 <= 15 → no pixels changed
        stats_high = imdiff.run([path_a, path_b, "--threshold", "15", "--summary-only"])
        assert stats_high["changed_pixels"] == 0
