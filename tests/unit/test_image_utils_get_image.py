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

    monkeypatch.setattr("utils.http_utils.http_get", lambda url, timeout=None: Resp())
    img = get_image("http://example/img.png")
    assert img is not None
    assert img.size == (5, 5)


def test_get_image_error(monkeypatch):
    class Resp:
        status_code = 500
        content = b""

    monkeypatch.setattr("utils.http_utils.http_get", lambda url, timeout=None: Resp())
    img = get_image("http://example/img.png")
    assert img is None
