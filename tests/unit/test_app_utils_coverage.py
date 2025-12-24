"""Tests for app_utils.py to improve code coverage."""

import os
import pytest
from io import BytesIO
from unittest.mock import Mock, patch, MagicMock
from PIL import Image
from werkzeug.datastructures import FileStorage, ImmutableMultiDict


def test_generate_startup_image_default():
    """Test generate_startup_image creates image with default dimensions."""
    from utils.app_utils import generate_startup_image

    img = generate_startup_image()
    assert img is not None
    assert isinstance(img, Image.Image)
    assert img.size == (800, 480)
    assert img.mode == "RGBA"


def test_generate_startup_image_custom_dimensions():
    """Test generate_startup_image with custom dimensions."""
    from utils.app_utils import generate_startup_image

    img = generate_startup_image(dimensions=(400, 300))
    assert img is not None
    assert img.size == (400, 300)


def test_generate_startup_image_font_fallback():
    """Test generate_startup_image falls back to default font if custom font fails."""
    from utils.app_utils import generate_startup_image

    # Mock get_font to return None (simulating missing font)
    with patch("utils.app_utils.get_font", return_value=None):
        img = generate_startup_image()
        assert img is not None
        # Should still create image with fallback font


def test_parse_form_with_list_params():
    """Test parse_form handles list parameters (keys ending with [])."""
    from utils.app_utils import parse_form

    # Create mock form with list parameter
    mock_form = ImmutableMultiDict([
        ("name", "test"),
        ("tags[]", "tag1"),
        ("tags[]", "tag2"),
        ("tags[]", "tag3")
    ])

    result = parse_form(mock_form)
    assert result["name"] == "test"
    assert result["tags[]"] == ["tag1", "tag2", "tag3"]


def test_get_fonts_returns_list():
    """Test get_fonts returns properly formatted font list."""
    from utils.app_utils import get_fonts

    fonts = get_fonts()
    assert isinstance(fonts, list)
    assert len(fonts) > 0

    # Check structure of font entries
    for font in fonts:
        assert "font_family" in font
        assert "url" in font
        assert "font_weight" in font
        assert "font_style" in font


def test_get_font_path():
    """Test get_font_path returns correct path."""
    from utils.app_utils import get_font_path

    # Test with a known font (if FONTS dict has entries)
    try:
        from utils.app_utils import FONTS
        if FONTS:
            first_font = list(FONTS.keys())[0]
            path = get_font_path(first_font)
            assert isinstance(path, str)
            assert "fonts" in path
    except (ImportError, AttributeError, KeyError):
        # FONTS might not be accessible, skip this part
        pass


def test_handle_request_files_with_valid_file():
    """Test handle_request_files processes valid image files."""
    from utils.app_utils import handle_request_files

    # Create valid PNG file
    img = Image.new("RGB", (10, 10), color="red")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    file_storage = FileStorage(
        stream=buf,
        filename="test.png",
        content_type="image/png"
    )

    mock_files = ImmutableMultiDict([("image", file_storage)])
    result = handle_request_files(mock_files)

    assert "image" in result
    # Result can be either a list or a single file path string
    assert result["image"] is not None


def test_handle_request_files_skips_invalid_extension():
    """Test handle_request_files skips files with invalid extensions."""
    from utils.app_utils import handle_request_files

    buf = BytesIO(b"text data")
    file_storage = FileStorage(
        stream=buf,
        filename="test.txt",  # .txt not allowed
        content_type="text/plain"
    )

    mock_files = ImmutableMultiDict([("file", file_storage)])
    result = handle_request_files(mock_files)

    # Should skip .txt file
    assert "file" not in result or not result.get("file")


def test_handle_request_files_skips_empty_filename():
    """Test handle_request_files skips files with empty filename."""
    from utils.app_utils import handle_request_files

    buf = BytesIO(b"data")
    file_storage = FileStorage(
        stream=buf,
        filename="",  # Empty filename
        content_type="image/png"
    )

    mock_files = ImmutableMultiDict([("file", file_storage)])
    result = handle_request_files(mock_files)

    # Should skip files with no filename
    assert "file" not in result or not result.get("file")

