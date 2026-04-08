"""Tests for utils.image_serving — WebP on-the-fly encoding helper."""

from __future__ import annotations

import os
import time
from pathlib import Path

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


def test_webp_returned_when_header_present(tmp_path):
    """Client sending Accept: image/webp receives WebP bytes."""
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    png = _make_png(tmp_path)
    app = Flask(__name__)
    with app.test_request_context("/"):
        resp = maybe_serve_webp(png, "image/webp,*/*;q=0.8", safe_root=tmp_path)

    assert resp.content_type == "image/webp"
    # Verify the bytes are valid WebP (RIFF….WEBP header)
    data = resp.get_data()
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WEBP"


def test_png_returned_when_header_absent(tmp_path):
    """Client without Accept: image/webp gets the original PNG."""
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    png = _make_png(tmp_path)
    app = Flask(__name__)
    with app.test_request_context("/"):
        resp = maybe_serve_webp(png, None, safe_root=tmp_path)

    assert resp.content_type == "image/png"


def test_png_returned_when_header_no_webp(tmp_path):
    """Client sending only image/png in Accept header gets PNG."""
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    png = _make_png(tmp_path)
    app = Flask(__name__)
    with app.test_request_context("/"):
        resp = maybe_serve_webp(png, "image/png,*/*", safe_root=tmp_path)

    assert resp.content_type == "image/png"


def test_etag_present_for_webp_response(tmp_path):
    """WebP response includes an ETag header."""
    from flask import Flask

    from utils.image_serving import maybe_serve_webp

    png = _make_png(tmp_path)
    app = Flask(__name__)
    with app.test_request_context("/"):
        resp = maybe_serve_webp(png, "image/webp", safe_root=tmp_path)

    assert "ETag" in resp.headers
    assert resp.headers["ETag"]  # non-empty


def test_etag_changes_when_mtime_changes(tmp_path):
    """ETag must differ after the file is updated (mtime changes)."""
    from flask import Flask

    from utils.image_serving import _encode_webp, maybe_serve_webp

    png = _make_png(tmp_path)
    app = Flask(__name__)

    # First response
    with app.test_request_context("/"):
        resp1 = maybe_serve_webp(png, "image/webp", safe_root=tmp_path)
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
        resp2 = maybe_serve_webp(png, "image/webp", safe_root=tmp_path)
    etag2 = resp2.headers["ETag"]

    assert etag1 != etag2


def test_cache_returns_same_bytes_on_repeated_call(tmp_path):
    """Repeated calls with same mtime hit lru_cache (same object returned)."""
    from flask import Flask

    from utils.image_serving import _encode_webp, maybe_serve_webp

    png = _make_png(tmp_path)
    app = Flask(__name__)

    _encode_webp.cache_clear()

    with app.test_request_context("/"):
        resp1 = maybe_serve_webp(png, "image/webp", safe_root=tmp_path)
    with app.test_request_context("/"):
        resp2 = maybe_serve_webp(png, "image/webp", safe_root=tmp_path)

    assert resp1.get_data() == resp2.get_data()
    # Cache should have exactly 1 entry (second call was a hit)
    info = _encode_webp.cache_info()
    assert info.currsize == 1
    assert info.hits >= 1
