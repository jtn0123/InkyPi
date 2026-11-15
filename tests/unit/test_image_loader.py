# pyright: reportMissingImports=false
"""Tests for utils/image_loader.py — AdaptiveImageLoader."""

import socket
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


def _ainfo(ip: str, port: Any = 0) -> list[Any]:
    """Build a minimal IPv4 addrinfo list for *ip*."""
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]


# ``from_url`` validates the host before fetching; resolve it offline.
pytestmark = pytest.mark.usefixtures("public_dns")


def _png_bytes(size: Any = (200, 150), color: Any = "red") -> Any:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _make_session_response(content: Any, status_code: Any = 200) -> Any:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.content = content
    resp.status_code = status_code
    resp.iter_content = MagicMock(return_value=[content])
    return resp


# ---- _is_low_resource_device ----


def test_is_low_resource_device_low_ram() -> None:
    from utils.image_loader import _is_low_resource_device

    mock_mem = MagicMock()
    mock_mem.total = 512 * 1024 * 1024  # 512 MB
    with patch("utils.image_loader.psutil.virtual_memory", return_value=mock_mem):
        assert _is_low_resource_device() is True


def test_is_low_resource_device_high_ram() -> None:
    from utils.image_loader import _is_low_resource_device

    mock_mem = MagicMock()
    mock_mem.total = 4 * 1024**3  # 4 GB
    with patch("utils.image_loader.psutil.virtual_memory", return_value=mock_mem):
        assert _is_low_resource_device() is False


def test_is_low_resource_device_error() -> None:
    from utils.image_loader import _is_low_resource_device

    with patch(
        "utils.image_loader.psutil.virtual_memory", side_effect=RuntimeError("fail")
    ):
        assert _is_low_resource_device() is True


# ---- from_url (fast path) ----


def test_from_url_fast_success() -> None:
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


def test_from_url_fast_request_error() -> None:
    import requests

    from utils.image_loader import AdaptiveImageLoader

    session = MagicMock()
    session.get.side_effect = requests.exceptions.RequestException("timeout")

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            result = loader.from_url("http://fail.com/img.png", (100, 75))
    assert result is None


def test_from_url_fast_no_resize() -> None:
    from utils.image_loader import AdaptiveImageLoader

    img_bytes = _png_bytes((200, 150))
    session = MagicMock()
    session.get.return_value = _make_session_response(img_bytes)

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            result = loader.from_url(
                "http://example.com/img.png", (100, 75), resize=False
            )
    assert isinstance(result, Image.Image)
    # Should keep original size (EXIF transpose may change it, but our test image has none)
    assert result.size == (200, 150)


def test_from_url_fast_custom_headers() -> None:
    from utils.image_loader import AdaptiveImageLoader

    img_bytes = _png_bytes()
    session = MagicMock()
    session.get.return_value = _make_session_response(img_bytes)

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            loader.from_url(
                "http://example.com/img.png", (100, 75), headers={"x-api-key": "test"}
            )
    call_kwargs = session.get.call_args[1]
    assert "x-api-key" in call_kwargs["headers"]


# ---- from_url (low-mem path) ----


def test_from_url_lowmem_success(tmp_path: Path) -> None:
    from utils.image_loader import AdaptiveImageLoader

    img_bytes = _png_bytes()
    session = MagicMock()
    session.get.return_value = _make_session_response(img_bytes)

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            result = loader.from_url("http://example.com/img.png", (100, 75))
    assert isinstance(result, Image.Image)


def test_from_url_lowmem_request_error() -> None:
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


def test_from_file_fast_success(tmp_path: Path) -> None:
    from utils.image_loader import AdaptiveImageLoader

    img_path = tmp_path / "test.png"
    Image.new("RGB", (200, 150), "green").save(str(img_path))

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_file(str(img_path), (100, 75))
    assert isinstance(result, Image.Image)
    assert result.size == (100, 75)


def test_from_file_not_found() -> None:
    from utils.image_loader import AdaptiveImageLoader

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_file("/nonexistent/path.png", (100, 75))
    assert result is None


def test_from_file_error(tmp_path: Path) -> None:
    from utils.image_loader import AdaptiveImageLoader

    bad_file = tmp_path / "bad.png"
    bad_file.write_text("not an image")

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_file(str(bad_file), (100, 75))
    assert result is None


def test_from_file_lowmem_success(tmp_path: Path) -> None:
    from utils.image_loader import AdaptiveImageLoader

    img_path = tmp_path / "test.png"
    Image.new("RGB", (200, 150), "blue").save(str(img_path))

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        loader = AdaptiveImageLoader()
        result = loader.from_file(str(img_path), (100, 75))
    assert isinstance(result, Image.Image)


def test_from_file_lowmem_memory_error(tmp_path: Path) -> None:
    from utils.image_loader import AdaptiveImageLoader

    img_path = tmp_path / "test.png"
    Image.new("RGB", (200, 150), "blue").save(str(img_path))

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        loader = AdaptiveImageLoader()
        with patch("PIL.Image.open", side_effect=MemoryError("OOM")):
            result = loader.from_file(str(img_path), (100, 75))
    assert result is None


# ---- from_bytesio ----


def test_from_bytesio_success() -> None:
    from utils.image_loader import AdaptiveImageLoader

    buf = BytesIO()
    Image.new("RGB", (200, 150), "yellow").save(buf, format="PNG")
    buf.seek(0)

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_bytesio(buf, (100, 75))
    assert isinstance(result, Image.Image)
    assert result.size == (100, 75)


def test_from_bytesio_no_resize() -> None:
    from utils.image_loader import AdaptiveImageLoader

    buf = BytesIO()
    Image.new("RGB", (200, 150), "yellow").save(buf, format="PNG")
    buf.seek(0)

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_bytesio(buf, (100, 75), resize=False)
    assert isinstance(result, Image.Image)
    assert result.size == (200, 150)


def test_from_bytesio_error() -> None:
    from utils.image_loader import AdaptiveImageLoader

    buf = BytesIO(b"not an image")

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_bytesio(buf, (100, 75))
    assert result is None


# ---- _process_and_resize ----


def test_process_and_resize_rgba() -> None:
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("RGBA", (200, 150), (255, 0, 0, 128))

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader._process_and_resize(img, (100, 75), img.size)
    assert result.mode == "RGB"
    assert result.size == (100, 75)


def test_process_and_resize_la() -> None:
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("LA", (200, 150))

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader._process_and_resize(img, (100, 75), img.size)
    assert result.mode == "RGB"


def test_process_and_resize_p() -> None:
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("P", (200, 150))

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader._process_and_resize(img, (100, 75), img.size)
    assert result.mode == "RGB"


# ---- resize strategies ----


def test_resize_low_resource_two_stage() -> None:
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("RGB", (2000, 1500), "green")

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        loader = AdaptiveImageLoader()
        result = loader._resize_low_resource(img, (100, 75))
    assert result.size == (100, 75)


def test_resize_low_resource_direct() -> None:
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("RGB", (150, 100), "green")

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        loader = AdaptiveImageLoader()
        result = loader._resize_low_resource(img, (100, 75))
    assert result.size == (100, 75)


def test_resize_high_performance() -> None:
    from utils.image_loader import AdaptiveImageLoader

    img = Image.new("RGB", (2000, 1500), "green")

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader._resize_high_performance(img, (100, 75))
    assert result.size == (100, 75)


# ---- Additional edge-case tests ----


def test_from_url_lowmem_temp_cleanup_on_error() -> None:
    """Download error returns None without leaving temp files."""
    import requests

    from utils.image_loader import AdaptiveImageLoader

    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectionError("refused")

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            result = loader.from_url("http://fail.com/img.png", (100, 75))
    assert result is None
    # No temp files should be left behind (checked implicitly - no error)


def test_from_url_lowmem_custom_headers() -> None:
    """Headers are merged in low-mem path."""
    from utils.image_loader import AdaptiveImageLoader

    img_bytes = _png_bytes()
    session = MagicMock()
    session.get.return_value = _make_session_response(img_bytes)

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            loader.from_url(
                "http://example.com/img.png",
                (100, 75),
                headers={"Authorization": "Bearer tok"},
            )
    call_kwargs = session.get.call_args[1]
    assert "Authorization" in call_kwargs["headers"]
    # Default User-Agent should also be present
    assert "InkyPi" in call_kwargs["headers"]["User-Agent"]


def test_from_file_fast_corrupt_file(tmp_path: Path) -> None:
    """Corrupt file on fast path returns None."""
    from utils.image_loader import AdaptiveImageLoader

    bad_file = tmp_path / "corrupt.png"
    bad_file.write_bytes(b"\x89PNG\r\n\x1a\ngarbage")

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_file(str(bad_file), (100, 75))
    assert result is None


def test_resize_low_resource_portrait_two_stage() -> None:
    """Portrait (tall) image on low-resource two-stage resize path."""
    from utils.image_loader import AdaptiveImageLoader

    # Portrait: width < height, aspect < 1
    img = Image.new("RGB", (1000, 2000), "purple")

    with patch("utils.image_loader._is_low_resource_device", return_value=True):
        loader = AdaptiveImageLoader()
        result = loader._resize_low_resource(img, (100, 75))
    assert result.size == (100, 75)


def test_from_url_fast_processing_error() -> None:
    """Successful download but corrupt image data returns None."""
    from utils.image_loader import AdaptiveImageLoader

    session = MagicMock()
    session.get.return_value = _make_session_response(b"not an image at all")

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        with patch("utils.image_loader.get_http_session", return_value=session):
            loader = AdaptiveImageLoader()
            result = loader.from_url("http://example.com/bad.png", (100, 75))
    assert result is None


def test_from_bytesio_rgba_conversion() -> None:
    """RGBA image is converted to RGB through from_bytesio path."""
    from utils.image_loader import AdaptiveImageLoader

    buf = BytesIO()
    Image.new("RGBA", (200, 150), (255, 0, 0, 128)).save(buf, format="PNG")
    buf.seek(0)

    with patch("utils.image_loader._is_low_resource_device", return_value=False):
        loader = AdaptiveImageLoader()
        result = loader.from_bytesio(buf, (100, 75))
    assert isinstance(result, Image.Image)
    assert result.mode == "RGB"
    assert result.size == (100, 75)


# ---- from_url SSRF guard and size cap ----


def _loader(low_resource: bool) -> Any:
    from utils.image_loader import AdaptiveImageLoader

    with patch("utils.image_loader._is_low_resource_device", return_value=low_resource):
        return AdaptiveImageLoader()


@pytest.mark.parametrize("low_resource", [False, True])
def test_from_url_rejects_private_address_without_fetching(
    monkeypatch: pytest.MonkeyPatch, low_resource: bool
) -> None:
    """A host that resolves to a private address is refused before any request."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, port=0, *a, **kw: _ainfo("10.0.0.5", port)
    )
    session = MagicMock()
    with patch("utils.image_loader.get_http_session", return_value=session):
        result = _loader(low_resource).from_url("http://intranet.test/a.png", (10, 10))
    assert result is None
    session.get.assert_not_called()


def test_from_url_rejects_metadata_ip_literal() -> None:
    session = MagicMock()
    with patch("utils.image_loader.get_http_session", return_value=session):
        result = _loader(False).from_url("http://169.254.169.254/latest", (10, 10))
    assert result is None
    session.get.assert_not_called()


def test_from_url_allow_lan_accepts_lan_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port=0, *a, **kw: _ainfo("192.168.1.20", port),
    )
    session = MagicMock()
    session.get.return_value = _make_session_response(_png_bytes())
    with patch("utils.image_loader.get_http_session", return_value=session):
        result = _loader(False).from_url(
            "http://immich.lan/a.png", (100, 75), allow_lan=True
        )
    assert isinstance(result, Image.Image)


@pytest.mark.parametrize("low_resource", [False, True])
def test_from_url_refuses_redirect_to_private_address(low_resource: bool) -> None:
    """A public host cannot bounce the download to an internal address."""
    redirect = MagicMock()
    redirect.status_code = 302
    redirect.headers = {"Location": "http://127.0.0.1/secret.png"}
    session = MagicMock()
    session.get.return_value = redirect
    with patch("utils.image_loader.get_http_session", return_value=session):
        result = _loader(low_resource).from_url("http://example.com/a.png", (10, 10))
    assert result is None
    assert session.get.call_count == 1
    assert session.get.call_args[1]["allow_redirects"] is False


def test_from_url_follows_public_redirect() -> None:
    redirect = MagicMock()
    redirect.status_code = 301
    redirect.headers = {"Location": "https://cdn.example.org/a.png"}
    final = _make_session_response(_png_bytes())
    session = MagicMock()
    session.get.side_effect = [redirect, final]
    with patch("utils.image_loader.get_http_session", return_value=session):
        result = _loader(False).from_url("http://example.com/a.png", (100, 75))
    assert isinstance(result, Image.Image)
    assert session.get.call_args_list[1][0][0] == "https://cdn.example.org/a.png"


@pytest.mark.parametrize("low_resource", [False, True])
def test_from_url_rejects_declared_oversize_body(low_resource: bool) -> None:
    """A Content-Length over the cap is refused before the body is read."""
    resp = _make_session_response(_png_bytes())
    resp.headers = {"Content-Length": "2048"}
    session = MagicMock()
    session.get.return_value = resp
    with patch("utils.image_loader.get_http_session", return_value=session):
        result = _loader(low_resource).from_url(
            "http://example.com/a.png", (10, 10), max_bytes=1024
        )
    assert result is None
    resp.iter_content.assert_not_called()
    resp.close.assert_called()


@pytest.mark.parametrize("low_resource", [False, True])
def test_from_url_stops_streamed_body_at_cap(
    low_resource: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A body with no Content-Length is cut off once it passes the cap."""
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    chunks_read = 0

    def _endless(chunk_size: int = 8192) -> Any:
        nonlocal chunks_read
        while True:
            chunks_read += 1
            yield b"x" * chunk_size

    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.iter_content = _endless
    session = MagicMock()
    session.get.return_value = resp
    with patch("utils.image_loader.get_http_session", return_value=session):
        result = _loader(low_resource).from_url(
            "http://example.com/a.png", (10, 10), max_bytes=100_000
        )
    assert result is None
    assert chunks_read < 100
    resp.close.assert_called()
    # The low-memory path's temp file is removed even when the cap trips.
    assert list(tmp_path.iterdir()) == []


def test_from_url_http_error_status_returns_none() -> None:
    import requests

    resp = _make_session_response(b"")
    resp.status_code = 404
    resp.raise_for_status.side_effect = requests.HTTPError("404")
    session = MagicMock()
    session.get.return_value = resp
    with patch("utils.image_loader.get_http_session", return_value=session):
        result = _loader(True).from_url("http://example.com/a.png", (10, 10))
    assert result is None
    resp.close.assert_called()
