"""
Tests for image utilities and display manager.
"""

import io
import os
import threading

import pytest
from PIL import Image

from display.display_manager import DisplayManager
from utils.image_utils import (
    apply_image_enhancement,
    change_orientation,
    compute_image_hash,
    load_image_from_bytes,
    load_image_from_path,
    pad_image_blur,
    process_image_from_bytes,
    resize_image,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_image(width=800, height=480, color="red"):
    """Return a simple RGB PIL Image."""
    return Image.new("RGB", (width, height), color)


def image_to_png_bytes(img):
    """Serialize a PIL Image to PNG bytes."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# change_orientation
# ---------------------------------------------------------------------------


class TestChangeOrientation:
    def test_horizontal_keeps_landscape_size(self):
        img = make_image(800, 480)
        result = change_orientation(img, "horizontal")
        assert result.size == (800, 480)

    def test_vertical_rotates_90(self):
        img = make_image(800, 480)
        result = change_orientation(img, "vertical")
        assert result.size == (480, 800)

    def test_horizontal_inverted_stays_same_size(self):
        img = make_image(800, 480)
        result = change_orientation(img, "horizontal", inverted=True)
        # 180-degree rotation preserves dimensions
        assert result.size == (800, 480)

    def test_vertical_inverted_is_270_degrees(self):
        img = make_image(800, 480)
        result = change_orientation(img, "vertical", inverted=True)
        # 270 degrees still swaps width/height
        assert result.size == (480, 800)

    def test_invalid_orientation_raises_value_error(self):
        img = make_image(800, 480)
        with pytest.raises(ValueError):
            change_orientation(img, "diagonal")


# ---------------------------------------------------------------------------
# resize_image
# ---------------------------------------------------------------------------


class TestResizeImage:
    def test_wider_image_resized_to_target(self):
        img = make_image(1600, 800)
        result = resize_image(img, (800, 480))
        assert result.size == (800, 480)

    def test_taller_image_resized_to_target(self):
        img = make_image(400, 800)
        result = resize_image(img, (800, 480))
        assert result.size == (800, 480)

    def test_exact_size_no_change(self):
        img = make_image(800, 480)
        result = resize_image(img, (800, 480))
        assert result.size == (800, 480)

    def test_keep_width_setting(self):
        img = make_image(800, 480)
        result = resize_image(img, (800, 480), image_settings=["keep-width"])
        assert result.size == (800, 480)

    def test_zero_height_raises_value_error(self):
        img = make_image(800, 480)
        with pytest.raises(ValueError):
            resize_image(img, (800, 0))


# ---------------------------------------------------------------------------
# apply_image_enhancement
# ---------------------------------------------------------------------------


class TestApplyImageEnhancement:
    def test_no_settings_returns_image(self):
        img = make_image()
        result = apply_image_enhancement(img)
        assert isinstance(result, Image.Image)

    def test_empty_dict_returns_image(self):
        img = make_image()
        result = apply_image_enhancement(img, image_settings={})
        assert isinstance(result, Image.Image)

    def test_custom_settings_returns_image(self):
        img = make_image()
        settings = {
            "brightness": 1.5,
            "contrast": 0.8,
            "saturation": 1.2,
            "sharpness": 0.5,
        }
        result = apply_image_enhancement(img, image_settings=settings)
        assert isinstance(result, Image.Image)

    def test_none_settings_uses_defaults(self):
        img = make_image()
        result = apply_image_enhancement(img, image_settings=None)
        assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# compute_image_hash
# ---------------------------------------------------------------------------


class TestComputeImageHash:
    def test_same_image_same_hash(self):
        img1 = make_image(800, 480, "red")
        img2 = make_image(800, 480, "red")
        assert compute_image_hash(img1) == compute_image_hash(img2)

    def test_different_images_different_hash(self):
        img1 = make_image(800, 480, "red")
        img2 = make_image(800, 480, "blue")
        assert compute_image_hash(img1) != compute_image_hash(img2)

    def test_none_raises_value_error(self):
        with pytest.raises(ValueError):
            compute_image_hash(None)


# ---------------------------------------------------------------------------
# load_image_from_bytes
# ---------------------------------------------------------------------------


class TestLoadImageFromBytes:
    def test_valid_bytes_returns_image(self):
        png_bytes = image_to_png_bytes(make_image())
        result = load_image_from_bytes(png_bytes)
        assert isinstance(result, Image.Image)

    def test_invalid_bytes_returns_none(self):
        result = load_image_from_bytes(b"not an image")
        assert result is None


# ---------------------------------------------------------------------------
# load_image_from_path
# ---------------------------------------------------------------------------


class TestLoadImageFromPath:
    def test_valid_path_returns_image(self, tmp_path):
        img = make_image()
        path = str(tmp_path / "test.png")
        img.save(path)
        result = load_image_from_path(path)
        assert isinstance(result, Image.Image)

    def test_nonexistent_path_returns_none(self):
        result = load_image_from_path("/nonexistent/path/image.png")
        assert result is None


# ---------------------------------------------------------------------------
# process_image_from_bytes
# ---------------------------------------------------------------------------


class TestProcessImageFromBytes:
    def test_processor_receives_image_and_result_returned(self):
        png_bytes = image_to_png_bytes(make_image())
        received = []

        def processor(img):
            received.append(img)
            return "processed"

        result = process_image_from_bytes(png_bytes, processor)
        assert result == "processed"
        assert len(received) == 1
        assert isinstance(received[0], Image.Image)

    def test_bad_bytes_returns_none(self):
        def processor(img):
            return "should not be called"

        result = process_image_from_bytes(b"garbage", processor)
        assert result is None


# ---------------------------------------------------------------------------
# pad_image_blur
# ---------------------------------------------------------------------------


class TestPadImageBlur:
    def test_small_image_padded_to_target_dimensions(self):
        small = make_image(400, 240, "green")
        dimensions = (800, 480)
        result = pad_image_blur(small, dimensions)
        assert result.size == dimensions


# ---------------------------------------------------------------------------
# DisplayManager
# ---------------------------------------------------------------------------


class TestDisplayManager:
    def test_hash_lock_exists_and_is_lock(self, device_config_dev, tmp_path):
        dm = DisplayManager(device_config_dev)
        assert hasattr(dm, "_hash_lock")
        assert isinstance(dm._hash_lock, type(threading.Lock()))

    def test_history_count_estimate_resets_after_recount_interval(
        self, device_config_dev, tmp_path
    ):
        dm = DisplayManager(device_config_dev)
        recount_interval = dm._RECOUNT_INTERVAL
        # Seed the estimate so the fast-path is taken
        dm._history_count_estimate = 0
        # Drive the increment counter to the threshold
        for _ in range(recount_interval):
            dm._history_count_estimate += 1
            dm._history_increment_count += 1
            if dm._history_increment_count >= recount_interval:
                dm._history_increment_count = 0
        assert dm._history_increment_count == 0

    def test_display_image_skip_duplicate(self, device_config_dev, tmp_path):
        dm = DisplayManager(device_config_dev)
        img = make_image(800, 480, "red")

        dm.display_image(img)
        result2 = dm.display_image(img)

        # Second call with the same image should skip display
        assert result2.get("display_ms") == 0

    def test_prune_history_removes_excess(self, device_config_dev, tmp_path):
        dm = DisplayManager(device_config_dev)
        history_dir = device_config_dev.history_image_dir

        # Create 510 PNG files with distinct modification times
        os.makedirs(history_dir, exist_ok=True)
        for i in range(510):
            path = os.path.join(history_dir, f"img_{i:04d}.png")
            make_image(10, 10, "white").save(path)
            # Spread mtime so oldest are clearly distinguishable
            os.utime(path, (i, i))

        dm._prune_history(history_dir)

        remaining = sorted(os.listdir(history_dir))
        assert len(remaining) <= 500
        # The oldest files (lowest mtime) should have been removed
        for name in remaining:
            index = int(name.replace("img_", "").replace(".png", ""))
            assert index >= 10
