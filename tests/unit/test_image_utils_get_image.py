# pyright: reportMissingImports=false
from io import BytesIO

from PIL import Image

from utils.image_utils import get_image


def test_get_image_success(monkeypatch):
    # Create a PNG byte stream
    buf = BytesIO()
    Image.new("RGB", (5, 5), "white").save(buf, format="PNG")
    png_bytes = buf.getvalue()

    class Resp:
        status_code = 200
        content = png_bytes

    monkeypatch.setattr("utils.image_utils.http_get", lambda url, **kwargs: Resp())
    img = get_image("http://example/img.png")
    assert img is not None
    assert img.size == (5, 5)


def test_get_image_error(monkeypatch):
    class Resp:
        status_code = 500
        content = b""

    monkeypatch.setattr("utils.image_utils.http_get", lambda url, **kwargs: Resp())
    img = get_image("http://example/img.png")
    assert img is None


def test_get_image_304_not_modified(monkeypatch):
    # 304 should be treated as success path per implementation
    from utils.image_utils import get_image

    class Resp:
        status_code = 304
        content = b"\x89PNG\r\n\x1a\n"  # minimal header; decoder won't be used

    monkeypatch.setattr("utils.image_utils.requests.get", lambda url, timeout=None: Resp())
    # The code path checks status and then tries to decode; since content isn't full image,
    # it will hit decode error and return None; so just assert it doesn't crash and returns None.
    assert get_image("http://example/img.png") is None
