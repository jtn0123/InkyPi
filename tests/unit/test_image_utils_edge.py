# pyright: reportMissingImports=false
import importlib
from io import BytesIO

from PIL import Image


def _png_bytes(size=(5, 5), color="white"):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_get_image_timeout_fallback_success(monkeypatch):
    import utils.image_utils as image_utils

    calls = {"n": 0}

    png = _png_bytes()

    class Resp:
        status_code = 200
        content = png

    def fake_get(url, timeout=None, stream=False):
        if calls["n"] == 0:
            calls["n"] += 1
            raise TypeError("timeout arg not supported")
        return Resp()

    monkeypatch.setattr("utils.http_utils.http_get", fake_get)
    img = image_utils.get_image("http://example/img.png")
    assert img is not None
    assert img.size == (5, 5)


def test_get_image_timeout_fallback_failure(monkeypatch):
    import utils.image_utils as image_utils

    calls = {"n": 0}

    def fake_get(url, timeout=None, stream=False):
        if calls["n"] == 0:
            calls["n"] += 1
            raise TypeError("timeout arg not supported")
        raise RuntimeError("network broke")

    monkeypatch.setattr("utils.http_utils.http_get", fake_get)
    img = image_utils.get_image("http://example/img.png")
    assert img is None


def test_get_image_decode_error(monkeypatch):
    import utils.image_utils as image_utils

    class Resp:
        status_code = 200
        content = b"not an image"

    monkeypatch.setattr("utils.http_utils.http_get", lambda url, timeout=None: Resp())
    img = image_utils.get_image("http://example/img.png")
    assert img is None


def test_take_screenshot_html_success(monkeypatch):
    import utils.image_utils as image_utils

    # Reload to restore real functions after autouse fixture monkeypatch
    image_utils = importlib.reload(image_utils)

    class Result:
        returncode = 0
        stderr = b""

    monkeypatch.setattr("utils.image_utils.subprocess.run", lambda *a, **k: Result())
    monkeypatch.setattr("utils.image_utils.os.path.exists", lambda p: True)
    monkeypatch.setattr("utils.image_utils.os.remove", lambda p: None)

    class _Ctx:
        def __init__(self, size=(10, 6)):
            self._img = Image.new("RGB", size, "white")

        def __enter__(self):
            return self._img

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("utils.image_utils.Image.open", lambda p: _Ctx())

    out = image_utils.take_screenshot_html("<html></html>", (8, 4))
    assert out is not None
    assert out.size == (10, 6)


def test_take_screenshot_html_failure(monkeypatch):
    import utils.image_utils as image_utils

    # Reload to restore real functions after autouse fixture monkeypatch
    image_utils = importlib.reload(image_utils)

    class Result:
        returncode = 1
        stderr = b"boom"

    monkeypatch.setattr("utils.image_utils.subprocess.run", lambda *a, **k: Result())
    monkeypatch.setattr("utils.image_utils.os.path.exists", lambda p: False)

    out = image_utils.take_screenshot_html("<html></html>", (8, 4))
    assert out is None
