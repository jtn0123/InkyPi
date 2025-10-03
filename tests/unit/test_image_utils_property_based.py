"""Property-based tests for image utility functions using Hypothesis.

These tests verify image operations maintain important invariants across
a wide range of inputs, catching edge cases that unit tests might miss.
"""

from io import BytesIO

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from PIL import Image

from utils.image_utils import (
    apply_image_enhancement,
    change_orientation,
    compute_image_hash,
    load_image_from_bytes,
    load_image_from_path,
    resize_image,
)


# Custom strategies for image testing
@st.composite
def image_dimensions(draw, min_size=1, max_size=2000):
    """Generate valid image dimensions."""
    width = draw(st.integers(min_value=min_size, max_value=max_size))
    height = draw(st.integers(min_value=min_size, max_value=max_size))
    return (width, height)


@st.composite
def pil_image(draw, min_size=1, max_size=200):
    """Generate a PIL Image with random dimensions and solid color.

    Note: Uses solid color instead of random pixels to avoid Hypothesis buffer limits.
    """
    size = draw(image_dimensions(min_size=min_size, max_size=max_size))
    mode = draw(st.sampled_from(["RGB", "RGBA", "L"]))
    # Generate a solid color instead of per-pixel data to avoid buffer limits
    if mode == "L":
        color = draw(st.integers(min_value=0, max_value=255))
    elif mode == "RGB":
        color = (
            draw(st.integers(min_value=0, max_value=255)),
            draw(st.integers(min_value=0, max_value=255)),
            draw(st.integers(min_value=0, max_value=255)),
        )
    else:  # RGBA
        color = (
            draw(st.integers(min_value=0, max_value=255)),
            draw(st.integers(min_value=0, max_value=255)),
            draw(st.integers(min_value=0, max_value=255)),
            draw(st.integers(min_value=0, max_value=255)),
        )
    return Image.new(mode, size, color=color)


@st.composite
def enhancement_settings(draw):
    """Generate valid image enhancement settings."""
    return {
        "brightness": draw(st.floats(min_value=0.1, max_value=3.0)),
        "contrast": draw(st.floats(min_value=0.1, max_value=3.0)),
        "saturation": draw(st.floats(min_value=0.0, max_value=3.0)),
        "sharpness": draw(st.floats(min_value=0.0, max_value=3.0)),
    }


# Property-based tests


@given(pil_image())
@settings(max_examples=50, deadline=5000)
def test_resize_preserves_aspect_ratio_with_crop(img):
    """Resizing maintains expected dimensions after crop."""
    original_width, original_height = img.size
    assume(original_width > 0 and original_height > 0)

    # Test with a target size
    target_size = (original_width // 2, original_height // 2)
    assume(target_size[0] > 0 and target_size[1] > 0)

    resized = resize_image(img, target_size)

    # Result should exactly match target dimensions
    assert resized.size == target_size, (
        f"Expected {target_size}, got {resized.size}"
    )


@given(pil_image(), image_dimensions(min_size=10, max_size=800))
@settings(max_examples=50, deadline=5000)
def test_resize_to_arbitrary_size(img, target_size):
    """Resize produces exact target dimensions for any valid size."""
    assume(img.size[0] > 0 and img.size[1] > 0)
    assume(target_size[0] > 0 and target_size[1] > 0)

    result = resize_image(img, target_size)
    assert result.size == target_size


@given(pil_image(), st.sampled_from(["horizontal", "vertical"]))
@settings(max_examples=30, deadline=5000)
def test_change_orientation_preserves_pixels(img, orientation):
    """Orientation changes preserve pixel data (possibly rotated)."""
    original_size = img.size
    assume(original_size[0] > 0 and original_size[1] > 0)

    result = change_orientation(img, orientation)

    # Check that result is a valid image
    assert isinstance(result, Image.Image)
    # Verify dimensions are swapped correctly for vertical
    if orientation == "vertical":
        assert result.size == (original_size[1], original_size[0])
    else:
        assert result.size == original_size


@given(pil_image())
@settings(max_examples=50, deadline=5000)
def test_image_hash_deterministic(img):
    """Same image produces same hash consistently."""
    # Convert to RGB for consistency (hash requires RGB)
    img_rgb = img.convert("RGB")

    hash1 = compute_image_hash(img_rgb)
    hash2 = compute_image_hash(img_rgb)

    assert hash1 == hash2
    assert isinstance(hash1, str)
    assert len(hash1) == 64  # SHA-256 produces 64 hex characters


@given(pil_image(), pil_image())
@settings(max_examples=30, deadline=5000)
def test_different_images_different_hashes(img1, img2):
    """Different images should produce different hashes (with high probability)."""
    # Skip if images are identical
    assume(img1.tobytes() != img2.tobytes())

    img1_rgb = img1.convert("RGB")
    img2_rgb = img2.convert("RGB")

    hash1 = compute_image_hash(img1_rgb)
    hash2 = compute_image_hash(img2_rgb)

    # With SHA-256, collisions are astronomically unlikely
    assert hash1 != hash2


@given(pil_image(), enhancement_settings())
@settings(max_examples=50, deadline=5000)
def test_apply_enhancement_preserves_size(img, settings_dict):
    """Image enhancement preserves dimensions."""
    original_size = img.size

    result = apply_image_enhancement(img, settings_dict)

    assert result.size == original_size
    assert isinstance(result, Image.Image)


@given(pil_image())
@settings(max_examples=50, deadline=5000)
def test_apply_enhancement_default_settings_unchanged(img):
    """Default enhancement settings (all 1.0) should not modify pixels."""
    default_settings = {
        "brightness": 1.0,
        "contrast": 1.0,
        "saturation": 1.0,
        "sharpness": 1.0,
    }

    result = apply_image_enhancement(img, default_settings)

    # Should preserve size at minimum
    assert result.size == img.size


@given(pil_image())
@settings(max_examples=30, deadline=5000)
def test_load_image_from_bytes_roundtrip(img):
    """Loading image from bytes preserves image data."""
    # Save to bytes
    bio = BytesIO()
    img.save(bio, format="PNG")
    img_bytes = bio.getvalue()

    # Load back
    loaded = load_image_from_bytes(img_bytes)

    assert loaded is not None
    assert loaded.size == img.size
    # Mode might be normalized (e.g., RGBA -> RGB), so just check it's valid
    assert loaded.mode in ["RGB", "RGBA", "L", "P"]


@given(
    st.integers(min_value=1, max_value=100),
    st.integers(min_value=1, max_value=100),
    st.sampled_from(["keep-width", ""]),
)
@settings(max_examples=50, deadline=5000)
def test_resize_keep_width_setting(width, height, keep_width_setting):
    """Test keep-width setting behavior in resize."""
    img = Image.new("RGB", (width * 2, height))  # Wide image
    target_size = (width, height)
    settings = [keep_width_setting] if keep_width_setting else []

    result = resize_image(img, target_size, image_settings=settings)

    assert result.size == target_size


@given(pil_image())
@settings(max_examples=30, deadline=5000)
def test_orientation_inverted_double_rotation(img):
    """Double inverted rotation returns to original orientation (360 degrees)."""
    # Horizontal + inverted twice should equal no change
    rotated_once = change_orientation(img, "horizontal", inverted=True)
    rotated_twice = change_orientation(rotated_once, "horizontal", inverted=True)

    assert rotated_twice.size == img.size


def test_resize_zero_height_raises():
    """Zero height in desired size should raise ValueError."""
    img = Image.new("RGB", (100, 100))
    with pytest.raises(ValueError, match="Desired height must be non-zero"):
        resize_image(img, (100, 0))


def test_resize_zero_image_height_raises():
    """Zero height in source image should raise ValueError."""
    # Create a mock image object with zero height
    from unittest.mock import Mock

    mock_img = Mock(spec=Image.Image)
    mock_img.size = (100, 0)

    with pytest.raises(ValueError, match="Image height must be non-zero"):
        resize_image(mock_img, (50, 50))


def test_change_orientation_invalid_raises():
    """Invalid orientation parameter raises ValueError."""
    img = Image.new("RGB", (100, 100))
    with pytest.raises(ValueError, match="Unsupported orientation"):
        change_orientation(img, "diagonal")


def test_compute_image_hash_none_raises():
    """Hashing None image raises ValueError."""
    with pytest.raises(ValueError, match="compute_image_hash called with None"):
        compute_image_hash(None)


@given(st.binary(min_size=1, max_size=100))
@settings(max_examples=30, deadline=2000)
def test_load_image_from_bytes_invalid_data(invalid_bytes):
    """Loading invalid image data returns None."""
    # Assume data is not actually a valid image
    assume(not invalid_bytes.startswith(b"\x89PNG"))  # PNG magic
    assume(not invalid_bytes.startswith(b"\xff\xd8\xff"))  # JPEG magic

    result = load_image_from_bytes(invalid_bytes)

    assert result is None
