# pyright: reportMissingImports=false
import importlib
from io import BytesIO
from typing import Any

import pytest
from PIL import Image


def _png_bytes(size: Any = (5, 5), color: Any = "white") -> Any:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_get_image_timeout_fallback_success(monkeypatch: pytest.MonkeyPatch) -> Any:
    import socket

    import utils.image_utils as image_utils

    calls = {"n": 0}

    png = _png_bytes()

    class Resp:
        status_code = 200
        content = png

    def fake_get(
        url: Any, timeout: Any = None, stream: Any = False, **kwargs: Any
    ) -> Any:
        if calls["n"] == 0:
            calls["n"] += 1
            raise TypeError("timeout arg not supported")
        return Resp()

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    monkeypatch.setattr("utils.image_utils.http_get", fake_get)
    img = image_utils.get_image("http://example.com/img.png")
    assert img is not None
    assert img.size == (5, 5)


def test_get_image_timeout_fallback_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import utils.image_utils as image_utils

    calls = {"n": 0}

    def fake_get(
        url: Any, timeout: Any = None, stream: Any = False, **kwargs: Any
    ) -> None:
        if calls["n"] == 0:
            calls["n"] += 1
            raise TypeError("timeout arg not supported")
        raise RuntimeError("network broke")

    monkeypatch.setattr("utils.image_utils.http_get", fake_get)
    img = image_utils.get_image("http://example/img.png")
    assert img is None


def test_get_image_decode_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import utils.image_utils as image_utils

    class Resp:
        status_code = 200
        content = b"not an image"

    monkeypatch.setattr("utils.image_utils.http_get", lambda url, **kwargs: Resp())
    img = image_utils.get_image("http://example/img.png")
    assert img is None


def test_take_screenshot_html_success(monkeypatch: pytest.MonkeyPatch) -> Any:
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
        def __init__(self, size: Any = (10, 6)) -> None:
            self._img = Image.new("RGB", size, "white")

        def __enter__(self) -> Any:
            return self._img

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
            return False

    monkeypatch.setattr("utils.image_utils.Image.open", lambda p: _Ctx())

    out = image_utils.take_screenshot_html("<html></html>", (8, 4))
    assert out is not None
    assert out.size == (10, 6)


def test_take_screenshot_html_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import utils.image_utils as image_utils

    # Reload to restore real functions after autouse fixture monkeypatch
    image_utils = importlib.reload(image_utils)

    class Result:
        returncode = 1
        stderr = b"boom"

    # Mock _playwright_screenshot_html to return None so it falls back to subprocess method
    monkeypatch.setattr(
        "utils.image_utils._playwright_screenshot_html", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("utils.image_utils.subprocess.run", lambda *a, **k: Result())
    monkeypatch.setattr("utils.image_utils.os.path.exists", lambda p: False)

    out = image_utils.take_screenshot_html("<html></html>", (8, 4))
    assert out is None
