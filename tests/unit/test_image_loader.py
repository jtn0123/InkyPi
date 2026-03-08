# pyright: reportMissingImports=false
"""Tests for utils/image_loader.py — AdaptiveImageLoader."""
import gc
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


def _png_bytes(size=(200, 150), color="red"):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _make_session_response(content, status_code=200):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.content = content
    resp.status_code = status_code
    resp.iter_content = MagicMock(return_value=[content])
    return resp


# ---- _is_low_resource_device ----

def test_is_low_resource_device_low_ram():
    from utils.image_loader import _is_low_resource_device

    mock_mem = MagicMock()
    mock_mem.total = 512 * 1024 * 1024  # 512 MB
    with patch("utils.image_loader.psutil.virtual_memory", return_value=mock_mem):
        assert _is_low_resource_device() is True


def test_is_low_resource_device_high_ram():
    from utils.image_loader import _is_low_resource_device

    mock_mem = MagicMock()
    mock_mem.total = 4 * 1024 ** 3  # 4 GB
    with patch("utils.image_loader.psutil.virtual_memory", return_value=mock_mem):
        assert _is_low_resource_device() is False


def test_is_low_resource_device_error():
    from utils.image_loader import _is_low_resource_device

    with patch("utils.image_loader.psutil.virtual_memory", side_effect=RuntimeError("fail")):
        assert _is_low_resource_device() is True


# ---- from_url (fast path) ----

def test_from_url_fast_success():
    from utils.image_loader import AdaptiveImageLoader

    img_bytes = _png_bytes()
    session = MagicMock()
    session.get.return_value = _make_session_response(img_bytes)

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            result = loader.from_url("http://example.com/img.png", (100, 75))
    assert isinstance(result, Image.Image)
    assert result.size == (100, 75)


def test_from_url_fast_request_error():
    import requests
    from utils.image_loader import AdaptiveImageLoader

    session = MagicMock()
    session.get.side_effect = requests.exceptions.RequestException("timeout")

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            result = loader.from_url("http://fail.com/img.png", (100, 75))
    assert result is None


def test_from_url_fast_no_resize():
    from utils.image_loader import AdaptiveImageLoader

    img_bytes = _png_bytes((200, 150))
    session = MagicMock()
    session.get.return_value = _make_session_response(img_bytes)

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            result = loader.from_url("http://example.com/img.png", (100, 75), resize=False)
    assert isinstance(result, Image.Image)
    # Should keep original size (EXIF transpose may change it, but our test image has none)
    assert result.size == (200, 150)


def test_from_url_fast_custom_headers():
    from utils.image_loader import AdaptiveImageLoader

    img_bytes = _png_bytes()
    session = MagicMock()
    session.get.return_value = _make_session_response(img_bytes)

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            loader.from_url("http://example.com/img.png", (100, 75), headers={"x-api-key": "test"})
    call_kwargs = session.get.call_args[1]
    assert "x-api-key" in call_kwargs["headers"]


# ---- from_url (low-mem path) ----

def test_from_url_lowmem_success(tmp_path):
    from utils.image_loader import AdaptiveImageLoader

    img_bytes = _png_bytes()
    session = MagicMock()
    session.get.return_value = _make_session_response(img_bytes)

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            result = loader.from_url("http://example.com/img.png", (100, 75))
    assert isinstance(result, Image.Image)


def test_from_url_lowmem_request_error():
    import requests
    from utils.image_loader import AdaptiveImageLoader

    session = MagicMock()
    session.get.side_effect = requests.exceptions.RequestException("timeout")

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            result = loader.from_url("http://fail.com/img.png", (100, 75))
    assert result is None


# ---- from_file ----

def test_from_file_fast_success(tmp_path):
    from utils.image_loader import AdaptiveImageLoader

    img_path = tmp_path / "test.png"
    Image.new("RGB", (200, 150), "green").save(str(img_path))

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_file(str(img_path), (100, 75))
    assert isinstance(result, Image.Image)
    assert result.size == (100, 75)


def test_from_file_not_found():
    from utils.image_loader import AdaptiveImageLoader

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_file("/nonexistent/path.png", (100, 75))
    assert result is None


def test_from_file_error(tmp_path):
    from utils.image_loader import AdaptiveImageLoader

    bad_file = tmp_path / "bad.png"
    bad_file.write_text("not an image")

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_file(str(bad_file), (100, 75))
    assert result is None


def test_from_file_lowmem_success(tmp_path):
    from utils.image_loader import AdaptiveImageLoader

    img_path = tmp_path / "test.png"
    Image.new("RGB", (200, 150), "blue").save(str(img_path))

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        loader = AdaptiveImageLoader()
        result = loader.from_file(str(img_path), (100, 75))
    assert isinstance(result, Image.Image)


def test_from_file_lowmem_memory_error(tmp_path):
    from utils.image_loader import AdaptiveImageLoader

    img_path = tmp_path / "test.png"
    Image.new("RGB", (200, 150), "blue").save(str(img_path))

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        loader = AdaptiveImageLoader()
        with patch("PIL.Image.open", side_effect=MemoryError("OOM")):
            result = loader.from_file(str(img_path), (100, 75))
    assert result is None


# ---- from_bytesio ----

def test_from_bytesio_success():
    from utils.image_loader import AdaptiveImageLoader

    buf = BytesIO()
    Image.new("RGB", (200, 150), "yellow").save(buf, format="PNG")
    buf.seek(0)

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_bytesio(buf, (100, 75))
    assert isinstance(result, Image.Image)
    assert result.size == (100, 75)


def test_from_bytesio_no_resize():
    from utils.image_loader import AdaptiveImageLoader

    buf = BytesIO()
    Image.new("RGB", (200, 150), "yellow").save(buf, format="PNG")
    buf.seek(0)

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_bytesio(buf, (100, 75), resize=False)
    assert isinstance(result, Image.Image)
    assert result.size == (200, 150)


def test_from_bytesio_error():
    from utils.image_loader import AdaptiveImageLoader

    buf = BytesIO(b"not an image")

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_bytesio(buf, (100, 75))
    assert result is None


# ---- _process_and_resize ----

def test_process_and_resize_rgba():
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("RGBA", (200, 150), (255, 0, 0, 128))

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader._process_and_resize(img, (100, 75), img.size)
    assert result.mode == "RGB"
    assert result.size == (100, 75)


def test_process_and_resize_la():
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("LA", (200, 150))

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader._process_and_resize(img, (100, 75), img.size)
    assert result.mode == "RGB"


def test_process_and_resize_p():
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("P", (200, 150))

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader._process_and_resize(img, (100, 75), img.size)
    assert result.mode == "RGB"


# ---- resize strategies ----

def test_resize_low_resource_two_stage():
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("RGB", (2000, 1500), "green")

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        loader = AdaptiveImageLoader()
        result = loader._resize_low_resource(img, (100, 75))
    assert result.size == (100, 75)


def test_resize_low_resource_direct():
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("RGB", (150, 100), "green")

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        loader = AdaptiveImageLoader()
        result = loader._resize_low_resource(img, (100, 75))
    assert result.size == (100, 75)


def test_resize_high_performance():
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("RGB", (2000, 1500), "green")

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader._resize_high_performance(img, (100, 75))
    assert result.size == (100, 75)
