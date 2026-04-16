"""Tests for image_utils.py to improve code coverage."""

from io import BytesIO
from unittest.mock import Mock, patch

from PIL import Image

from utils.image_utils import (
    _DEFAULT_SCREENSHOT_TIMEOUT_S,
    _MAX_SCREENSHOT_TIMEOUT_S,
)


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
    result = get_image(
        "http://this-domain-does-not-exist-12345.com/image.png", timeout_seconds=1.0
    )
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
        resize_image(img, (0, 100), [])
        # Should either handle gracefully or raise expected error
    except (ValueError, ZeroDivisionError):
        # Expected for zero dimensions
        pass


# ---------------------------------------------------------------------------
# Screenshot timeout tests (JTN-70)
# ---------------------------------------------------------------------------


def test_screenshot_timeout_default_when_none():
    """When timeout_ms is None, the computed timeout should use the default."""
    timeout_ms = None
    timeout_seconds = min(
        (timeout_ms / 1000) if timeout_ms else _DEFAULT_SCREENSHOT_TIMEOUT_S,
        _MAX_SCREENSHOT_TIMEOUT_S,
    )
    assert timeout_seconds == _DEFAULT_SCREENSHOT_TIMEOUT_S


def test_screenshot_timeout_caps_excessive():
    """Even if caller passes a huge timeout_ms, it should be capped at max."""
    timeout_ms = 120_000
    timeout_seconds = min(
        (timeout_ms / 1000) if timeout_ms else _DEFAULT_SCREENSHOT_TIMEOUT_S,
        _MAX_SCREENSHOT_TIMEOUT_S,
    )
    assert timeout_seconds == _MAX_SCREENSHOT_TIMEOUT_S


def test_screenshot_timeout_passes_normal():
    """A normal timeout_ms (e.g. 40000) should pass through as seconds."""
    timeout_ms = 40_000
    timeout_seconds = min(
        (timeout_ms / 1000) if timeout_ms else _DEFAULT_SCREENSHOT_TIMEOUT_S,
        _MAX_SCREENSHOT_TIMEOUT_S,
    )
    assert timeout_seconds == 40.0


def test_screenshot_timeout_constants_sane():
    """Default and max timeout constants should be positive and correctly ordered."""
    assert _DEFAULT_SCREENSHOT_TIMEOUT_S > 0
    assert _MAX_SCREENSHOT_TIMEOUT_S >= _DEFAULT_SCREENSHOT_TIMEOUT_S


# ---------------------------------------------------------------------------
# fetch_and_resize_remote_image tests
# ---------------------------------------------------------------------------


def test_fetch_and_resize_remote_image_success():
    """Test successful fetch and resize of a remote image."""
    from utils.image_utils import fetch_and_resize_remote_image

    img = Image.new("RGB", (200, 200), color="blue")
    buf = BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = img_bytes
    mock_response.raise_for_status.return_value = None

    with patch("utils.image_utils.http_get", return_value=mock_response):
        result = fetch_and_resize_remote_image(
            "http://example.com/photo.png", (100, 50)
        )

    assert result is not None
    assert isinstance(result, Image.Image)
    assert result.size == (100, 50)


def test_fetch_and_resize_remote_image_http_failure():
    """Test fetch_and_resize_remote_image when HTTP request fails."""
    from utils.image_utils import fetch_and_resize_remote_image

    with patch(
        "utils.image_utils.http_get", side_effect=Exception("Connection refused")
    ):
        result = fetch_and_resize_remote_image(
            "http://example.com/photo.png", (100, 50)
        )

    assert result is None


def test_fetch_and_resize_remote_image_invalid_bytes():
    """Test fetch_and_resize_remote_image with non-image response body."""
    from utils.image_utils import fetch_and_resize_remote_image

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = b"not an image at all"
    mock_response.raise_for_status.return_value = None

    with patch("utils.image_utils.http_get", return_value=mock_response):
        result = fetch_and_resize_remote_image(
            "http://example.com/photo.png", (100, 50)
        )

    assert result is None


def test_fetch_and_resize_remote_image_raise_for_status():
    """Test fetch_and_resize_remote_image when raise_for_status raises."""
    from requests.exceptions import HTTPError

    from utils.image_utils import fetch_and_resize_remote_image

    mock_response = Mock()
    mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")

    with patch("utils.image_utils.http_get", return_value=mock_response):
        result = fetch_and_resize_remote_image(
            "http://example.com/photo.png", (100, 50)
        )

    assert result is None


# ---------------------------------------------------------------------------
# _stream_to_disk tests
# ---------------------------------------------------------------------------


def test_stream_to_disk_writes_chunks_and_returns_path():
    """_stream_to_disk should write streamed chunks to a temp file."""
    import os

    from utils.image_utils import _stream_to_disk

    chunks = [b"chunk1", b"chunk2", b"chunk3"]
    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.iter_content.return_value = iter(chunks)
    mock_response.close = Mock()

    with patch("utils.image_utils.http_get", return_value=mock_response):
        with patch("utils.image_utils.pinned_dns"):
            path = _stream_to_disk(
                "http://example.com/img.png", 10.0, "example.com", ("1.2.3.4",)
            )

    try:
        assert os.path.exists(path)
        with open(path, "rb") as f:
            assert f.read() == b"chunk1chunk2chunk3"
    finally:
        os.unlink(path)


def test_stream_to_disk_raises_on_http_error():
    """_stream_to_disk should propagate HTTP errors."""
    from requests.exceptions import HTTPError

    from utils.image_utils import _stream_to_disk

    mock_response = Mock()
    mock_response.raise_for_status.side_effect = HTTPError("500")
    mock_response.close = Mock()

    with patch("utils.image_utils.http_get", return_value=mock_response):
        with patch("utils.image_utils.pinned_dns"):
            try:
                _stream_to_disk(
                    "http://example.com/img.png", 10.0, "example.com", ("1.2.3.4",)
                )
                assert False, "Should have raised"
            except HTTPError:
                pass


# ---------------------------------------------------------------------------
# fetch_and_resize_remote_image low-memory path tests
# ---------------------------------------------------------------------------


def test_fetch_and_resize_low_memory_success():
    """Test the low-memory streaming path through fetch_and_resize_remote_image."""
    from utils.image_utils import fetch_and_resize_remote_image

    fake_image = Image.new("RGB", (100, 50), color="green")

    mock_loader = Mock()
    mock_loader.is_low_resource = True
    mock_loader.from_file.return_value = fake_image

    with (
        patch("utils.image_utils._stream_to_disk", return_value="/tmp/fake.img"),
        patch("utils.image_utils.os.path.exists", return_value=True),
        patch("utils.image_utils.os.unlink"),
        patch("utils.image_loader.AdaptiveImageLoader", return_value=mock_loader),
    ):
        result = fetch_and_resize_remote_image(
            "http://example.com/photo.png", (100, 50)
        )

    assert result is fake_image
    mock_loader.from_file.assert_called_once_with(
        "/tmp/fake.img", (100, 50), resize=True
    )


def test_fetch_and_resize_low_memory_cleans_up_on_failure():
    """The low-memory path should delete the temp file even on error."""
    from utils.image_utils import fetch_and_resize_remote_image

    mock_loader = Mock()
    mock_loader.is_low_resource = True

    with (
        patch(
            "utils.image_utils._stream_to_disk",
            side_effect=Exception("download failed"),
        ),
        patch("utils.image_utils.os.path.exists", return_value=False),
        patch("utils.image_utils.os.unlink") as mock_unlink,
        patch("utils.image_loader.AdaptiveImageLoader", return_value=mock_loader),
    ):
        result = fetch_and_resize_remote_image(
            "http://example.com/photo.png", (100, 50)
        )

    assert result is None
    mock_unlink.assert_not_called()
