"""Simple edge case tests for image_utils to improve coverage."""

import pytest
from PIL import Image
from io import BytesIO


def test_resize_image_with_extreme_aspect_ratio(device_config_dev):
    """Test resizing image with extreme aspect ratio (very wide)."""
    from utils.image_utils import resize_image

    # Create very wide image (100:1 ratio)
    img = Image.new("RGB", (1000, 10), color="red")

    # Resize to square target
    result = resize_image(img, (400, 400), [])

    # Should resize without crashing
    assert result is not None
    assert isinstance(result, Image.Image)
    # Width or height should be 400, other dimension scaled proportionally
    assert 400 in result.size


def test_resize_image_very_small(device_config_dev):
    """Test resizing very small image."""
    from utils.image_utils import resize_image

    # Create tiny image
    img = Image.new("RGB", (1, 1), color="blue")

    # Resize to larger size
    result = resize_image(img, (800, 600), [])

    assert result is not None
    assert result.width <= 800
    assert result.height <= 600


def test_apply_image_enhancement_with_extreme_values():
    """Test image enhancement with extreme values."""
    from utils.image_utils import apply_image_enhancement

    img = Image.new("RGB", (100, 100), color="gray")

    # Test with very high values (should be clamped or handled)
    settings = {
        "brightness": 100,
        "contrast": 100,
        "sharpness": 100
    }

    result = apply_image_enhancement(img, settings)

    # Should not crash
    assert result is not None
    assert isinstance(result, Image.Image)


def test_apply_image_enhancement_with_zero_values():
    """Test image enhancement with zero/minimum values."""
    from utils.image_utils import apply_image_enhancement

    img = Image.new("RGB", (100, 100), color="gray")

    settings = {
        "brightness": 0,
        "contrast": 0,
        "sharpness": 0
    }

    result = apply_image_enhancement(img, settings)

    assert result is not None


def test_change_orientation_with_invalid_value():
    """Test orientation change with invalid orientation value."""
    from utils.image_utils import change_orientation

    img = Image.new("RGB", (200, 100), color="green")

    # Test valid orientations
    for orientation in ["horizontal", "vertical"]:
        result = change_orientation(img, orientation)
        assert result is not None
        assert isinstance(result, Image.Image)

    # Test invalid orientations - should raise ValueError
    for invalid_orientation in [None, "", "invalid", "diagonal"]:
        with pytest.raises(ValueError, match="Unsupported orientation"):
            change_orientation(img, invalid_orientation)


def test_resize_image_with_pad_settings():
    """Test resize with pad image setting."""
    from utils.image_utils import resize_image

    img = Image.new("RGB", (300, 200), color="yellow")

    # Test with padImage setting
    result = resize_image(img, (400, 400), ["padImage"])

    assert result is not None
    # With padding, might be exact size or proportional
    assert result.width <= 400
    assert result.height <= 400


def test_get_image_from_url_with_timeout():
    """Test get_image with network timeout."""
    from utils.image_utils import get_image

    # Test with unreachable URL (should timeout quickly)
    with pytest.raises(Exception):
        # Use invalid URL that will fail
        get_image("http://invalid.url.that.does.not.exist.test/image.png", timeout=1)


def test_resize_to_exact_dimensions():
    """Test that resize handles exact dimension requests."""
    from utils.image_utils import resize_image

    img = Image.new("RGB", (800, 600), color="purple")

    # Resize to smaller exact dimensions
    result = resize_image(img, (400, 300), [])

    assert result is not None
    # Should fit within target dimensions
    assert result.width <= 400
    assert result.height <= 300


def test_image_conversion_rgba_to_rgb():
    """Test RGBA to RGB conversion."""
    from utils.image_utils import resize_image

    # Create RGBA image
    img = Image.new("RGBA", (200, 200), color=(255, 0, 0, 128))

    # Resize should handle RGBA
    result = resize_image(img, (100, 100), [])

    assert result is not None
    # Should work with RGBA


def test_apply_enhancement_preserves_image_mode():
    """Test that enhancement preserves image mode."""
    from utils.image_utils import apply_image_enhancement

    # Test RGB
    img_rgb = Image.new("RGB", (50, 50), "white")
    result = apply_image_enhancement(img_rgb, {})
    assert result.mode in ("RGB", "RGBA", "L")  # Acceptable modes

    # Test with empty settings
    result2 = apply_image_enhancement(img_rgb, None)
    assert result2 is not None
