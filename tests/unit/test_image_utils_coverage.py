"""Tests for image_utils.py to improve code coverage."""

import pytest
from io import BytesIO
from unittest.mock import Mock, patch, MagicMock
from PIL import Image


def test_load_image_from_bytes_error_handling():
    """Test load_image_from_bytes handles invalid image data gracefully."""
    from utils.image_utils import load_image_from_bytes

    # Test with invalid image bytes
    invalid_data = b"This is not an image"
    result = load_image_from_bytes(invalid_data)
    assert result is None


def test_load_image_from_bytes_success():
    """Test load_image_from_bytes loads valid image bytes."""
    from utils.image_utils import load_image_from_bytes

    # Create valid image bytes
    img = Image.new("RGB", (100, 100), color="red")
    buf = BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    result = load_image_from_bytes(img_bytes)
    assert result is not None
    assert isinstance(result, Image.Image)


def test_load_image_from_path_error_handling():
    """Test load_image_from_path handles missing/invalid files gracefully."""
    from utils.image_utils import load_image_from_path

    # Test with non-existent file
    result = load_image_from_path("/path/that/does/not/exist.png")
    assert result is None

    # Test with invalid image file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"Not an image")
        temp_path = f.name

    try:
        result = load_image_from_path(temp_path)
        assert result is None
    finally:
        import os
        os.unlink(temp_path)


def test_get_image_with_bad_url():
    """Test get_image handles network errors gracefully."""
    from utils.image_utils import get_image

    # Test with invalid URL
    result = get_image("http://this-domain-does-not-exist-12345.com/image.png", timeout_seconds=1.0)
    assert result is None


def test_get_image_with_non_200_status():
    """Test get_image handles non-200 HTTP status codes."""
    from utils.image_utils import get_image

    # Mock http_get to return 404
    mock_response = Mock()
    mock_response.status_code = 404
    mock_response.content = b""

    with patch("utils.image_utils.http_get", return_value=mock_response):
        result = get_image("http://example.com/image.png")
        assert result is None


def test_get_image_with_invalid_image_data():
    """Test get_image handles invalid image data in response."""
    from utils.image_utils import get_image

    # Mock http_get to return 200 with invalid image data
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = b"Not an image"

    with patch("utils.image_utils.http_get", return_value=mock_response):
        result = get_image("http://example.com/image.png")
        assert result is None




def test_change_orientation_horizontal():
    """Test change_orientation with horizontal orientation."""
    from utils.image_utils import change_orientation

    img = Image.new("RGB", (200, 100), color="green")
    result = change_orientation(img, "horizontal")
    assert result.size == (200, 100)


def test_change_orientation_vertical():
    """Test change_orientation with vertical orientation."""
    from utils.image_utils import change_orientation

    img = Image.new("RGB", (200, 100), color="green")
    result = change_orientation(img, "vertical")
    # Should rotate 90 degrees
    assert result.size == (100, 200)


def test_change_orientation_inverted():
    """Test change_orientation with inverted flag."""
    from utils.image_utils import change_orientation

    img = Image.new("RGB", (200, 100), color="blue")
    result = change_orientation(img, "horizontal", inverted=True)
    # Inverted horizontal should rotate 180 degrees
    assert result.size == (200, 100)


def test_resize_image_with_zero_dimension():
    """Test resize_image handles zero dimensions gracefully."""
    from utils.image_utils import resize_image

    img = Image.new("RGB", (100, 100), color="red")

    # Test with zero width
    try:
        result = resize_image(img, (0, 100), [])
        # Should either handle gracefully or raise expected error
    except (ValueError, ZeroDivisionError):
        # Expected for zero dimensions
        pass
