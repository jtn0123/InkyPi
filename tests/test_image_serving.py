"""Tests for utils.image_serving — WebP on-the-fly encoding helper."""

from __future__ import annotations

import io
import os
import time
from pathlib import Path

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(tmp_path: Path, name: str = "test.png") -> Path:
    """Write a small PNG file and return its path."""
    p = tmp_path / name
    img = Image.new("RGB", (4, 4), color=(10, 20, 30))
    img.save(p, format="PNG")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_webp_returned_when_header_present(tmp_path: Path) -> None:
    """Client sending Accept: image/webp receives WebP bytes."""
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    _make_png(tmp_path)
    app = Flask(__name__)
    with app.test_request_context("/"):
        resp = maybe_serve_webp(tmp_path, "test.png", "image/webp,*/*;q=0.8")

    assert resp.content_type == "image/webp"
    # Verify the bytes are valid WebP (RIFF….WEBP header)
    data = resp.get_data()
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WEBP"


def test_png_returned_when_header_absent(tmp_path: Path) -> None:
    """Client without Accept: image/webp gets the original PNG."""
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    _make_png(tmp_path)
    app = Flask(__name__)
    with app.test_request_context("/"):
        resp = maybe_serve_webp(tmp_path, "test.png", None)

    assert resp.mimetype == "image/png"


def test_png_returned_when_header_no_webp(tmp_path: Path) -> None:
    """Client sending only image/png in Accept header gets PNG."""
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    _make_png(tmp_path)
    app = Flask(__name__)
    with app.test_request_context("/"):
        resp = maybe_serve_webp(tmp_path, "test.png", "image/png,*/*")

    assert resp.mimetype == "image/png"


def test_etag_present_for_webp_response(tmp_path: Path) -> None:
    """WebP response includes an ETag header."""
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    _make_png(tmp_path)
    app = Flask(__name__)
    with app.test_request_context("/"):
        resp = maybe_serve_webp(tmp_path, "test.png", "image/webp")

    assert "ETag" in resp.headers
    assert resp.headers["ETag"]  # non-empty


def test_etag_changes_when_mtime_changes(tmp_path: Path) -> None:
    """ETag must differ after the file is updated (mtime changes)."""
    from flask import Flask

    from utils.image_serving import _encode_webp, maybe_serve_webp

    png = _make_png(tmp_path)
    app = Flask(__name__)

    # First response
    with app.test_request_context("/"):
        resp1 = maybe_serve_webp(tmp_path, "test.png", "image/webp")
    etag1 = resp1.headers["ETag"]

    # Overwrite the file with a new image (different mtime)
    time.sleep(0.01)  # ensure mtime differs on fast filesystems
    img2 = Image.new("RGB", (4, 4), color=(50, 60, 70))
    img2.save(png, format="PNG")
    # Touch mtime explicitly to guarantee change
    new_mtime = int(os.path.getmtime(str(png))) + 1
    os.utime(str(png), (new_mtime, new_mtime))

    # Clear the lru_cache so the new file is re-encoded
    _encode_webp.cache_clear()

    with app.test_request_context("/"):
        resp2 = maybe_serve_webp(tmp_path, "test.png", "image/webp")
    etag2 = resp2.headers["ETag"]

    assert etag1 != etag2


def test_cache_returns_same_bytes_on_repeated_call(tmp_path: Path) -> None:
    """Repeated calls with same mtime hit lru_cache (same object returned)."""
    from flask import Flask

    from utils.image_serving import _encode_webp, maybe_serve_webp

    _make_png(tmp_path)
    app = Flask(__name__)

    _encode_webp.cache_clear()

    with app.test_request_context("/"):
        resp1 = maybe_serve_webp(tmp_path, "test.png", "image/webp")
    with app.test_request_context("/"):
        resp2 = maybe_serve_webp(tmp_path, "test.png", "image/webp")

    assert resp1.get_data() == resp2.get_data()
    # Cache should have exactly 1 entry (second call was a hit)
    info = _encode_webp.cache_info()
    assert info.currsize == 1
    assert info.hits >= 1


def test_path_traversal_rejected(tmp_path: Path) -> None:
    """Filename containing '..' must not escape safe_root."""
    from flask import Flask
    from werkzeug.exceptions import NotFound

    from utils.image_serving import maybe_serve_webp

    # Create a file outside the safe_root
    outside = tmp_path.parent / "outside.png"
    img = Image.new("RGB", (4, 4), color=(0, 0, 0))
    img.save(outside, format="PNG")
    try:
        nested = tmp_path / "nested"
        nested.mkdir()
        app = Flask(__name__)
        with app.test_request_context("/"):
            try:
                maybe_serve_webp(nested, "../../outside.png", "image/webp")
            except NotFound:
                return
            raise AssertionError("Expected NotFound for path traversal attempt")
    finally:
        try:
            outside.unlink()
        except FileNotFoundError:
            pass


def test_equal_size_same_second_overwrite_invalidates_webp(tmp_path: Path) -> None:
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    png = _make_png(tmp_path)
    timestamp = 1_700_000_000_000_000_000
    os.utime(png, ns=(timestamp, timestamp))
    size = png.stat().st_size
    app = Flask(__name__)
    with app.test_request_context("/"):
        first = maybe_serve_webp(tmp_path, "test.png", "image/webp")
    Image.new("RGB", (4, 4), (30, 20, 10)).save(png)
    assert png.stat().st_size == size
    os.utime(png, ns=(timestamp + 100_000, timestamp + 100_000))
    with app.test_request_context("/"):
        second = maybe_serve_webp(tmp_path, "test.png", "image/webp")
    assert first.get_data() != second.get_data()
    assert first.get_etag() != second.get_etag()


def test_conditional_revalidation_is_variant_specific(tmp_path: Path) -> None:
    from flask import Flask, Response, request

    from utils.image_serving import maybe_serve_webp

    _make_png(tmp_path)
    app = Flask(__name__)

    @app.route("/image")
    def image() -> Response:
        return maybe_serve_webp(tmp_path, "test.png", request.headers.get("Accept"))

    client = app.test_client()
    for accept in ("image/png", "image/webp"):
        first = client.get("/image", headers={"Accept": accept})
        assert "Accept" in first.vary
        etag = first.headers["ETag"]
        assert etag.startswith('"') and etag.endswith('"')
        unchanged = client.get(
            "/image", headers={"Accept": accept, "If-None-Match": etag}
        )
        assert unchanged.status_code == 304
        assert unchanged.data == b""
        other_accept = "image/png" if accept == "image/webp" else "image/webp"
        other = client.get(
            "/image", headers={"Accept": other_accept, "If-None-Match": etag}
        )
        assert other.status_code == 200
        assert other.headers["ETag"] != etag


def test_matching_webp_revalidation_skips_the_encode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A still-valid ETag is answered 304 before any WebP encoding happens."""
    from flask import Flask, Response, request

    import utils.image_serving as image_serving

    _make_png(tmp_path)
    app = Flask(__name__)

    @app.route("/image")
    def image() -> Response:
        return image_serving.maybe_serve_webp(
            tmp_path, "test.png", request.headers.get("Accept")
        )

    client = app.test_client()
    etag = client.get("/image", headers={"Accept": "image/webp"}).headers["ETag"]

    real_encode = image_serving._encode_webp
    calls: list[tuple[str, int, int]] = []

    def _counting_encode(path: str, mtime: int, size: int) -> bytes:
        calls.append((path, mtime, size))
        return real_encode(path, mtime, size)

    monkeypatch.setattr(image_serving, "_encode_webp", _counting_encode)
    unchanged = client.get(
        "/image", headers={"Accept": "image/webp", "If-None-Match": etag}
    )
    assert unchanged.status_code == 304
    assert unchanged.data == b""
    assert unchanged.headers["ETag"] == etag
    assert "Accept" in unchanged.vary
    assert unchanged.headers["Cache-Control"] == "no-cache"
    assert calls == []

    stale = client.get(
        "/image", headers={"Accept": "image/webp", "If-None-Match": '"stale"'}
    )
    assert stale.status_code == 200
    assert stale.data[8:12] == b"WEBP"
    assert len(calls) == 1


def test_thumbnail_scales_down_with_its_own_etag(tmp_path: Path) -> None:
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    Image.new("RGB", (800, 480), (10, 20, 30)).save(tmp_path / "big.png")
    app = Flask(__name__)
    with app.test_request_context("/"):
        full = maybe_serve_webp(tmp_path, "big.png", "image/webp")
        thumb = maybe_serve_webp(tmp_path, "big.png", "image/webp", width=480)

    with Image.open(io.BytesIO(thumb.get_data())) as img:
        assert img.format == "WEBP"
        assert img.size == (480, 288)
    assert full.get_etag() != thumb.get_etag()


def test_thumbnail_never_upscales(tmp_path: Path) -> None:
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    _make_png(tmp_path)  # 4x4
    app = Flask(__name__)
    with app.test_request_context("/"):
        thumb = maybe_serve_webp(tmp_path, "test.png", "image/webp", width=480)
    with Image.open(io.BytesIO(thumb.get_data())) as img:
        assert img.size == (4, 4)


def test_palette_thumbnail_is_resampled_not_nearest(tmp_path: Path) -> None:
    """A two-colour stripe pattern must average to grey, not alias to one colour."""
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    stripes = Image.new("P", (960, 10))
    stripes.putpalette([0, 0, 0, 255, 255, 255])
    stripes.putdata([x % 2 for _ in range(10) for x in range(960)])
    stripes.save(tmp_path / "stripes.png")
    app = Flask(__name__)
    with app.test_request_context("/"):
        thumb = maybe_serve_webp(tmp_path, "stripes.png", "image/webp", width=480)
    with Image.open(io.BytesIO(thumb.get_data())) as img:
        assert img.size == (480, 5)
        mid = img.convert("L").getpixel((240, 2))
    assert isinstance(mid, int | float)
    assert 64 < mid < 192, f"expected an averaged grey, got {mid}"


def test_thumbnail_rejects_unlisted_widths(tmp_path: Path) -> None:
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    _make_png(tmp_path)
    app = Flask(__name__)
    with app.test_request_context("/"), pytest.raises(ValueError):
        maybe_serve_webp(tmp_path, "test.png", "image/webp", width=123)


def test_matching_thumbnail_revalidation_skips_the_encode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flask import Flask, Response, request

    import utils.image_serving as image_serving

    Image.new("RGB", (800, 480), (10, 20, 30)).save(tmp_path / "big.png")
    app = Flask(__name__)

    @app.route("/image")
    def image() -> Response:
        return image_serving.maybe_serve_webp(
            tmp_path, "big.png", request.headers.get("Accept"), width=480
        )

    client = app.test_client()
    etag = client.get("/image", headers={"Accept": "image/webp"}).headers["ETag"]

    def _fail(*_args: object) -> bytes:
        raise AssertionError("a matching revalidation must not encode")

    monkeypatch.setattr(image_serving, "_encode_webp_thumbnail", _fail)
    monkeypatch.setattr(image_serving, "_encode_webp", _fail)
    unchanged = client.get(
        "/image", headers={"Accept": "image/webp", "If-None-Match": etag}
    )
    assert unchanged.status_code == 304
