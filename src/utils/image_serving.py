"""WebP on-the-fly encoding for image-serving routes.

Browsers that send ``Accept: image/webp`` receive a WebP-encoded version of
the PNG file.  The encoded bytes are cached in-process (keyed on path, mtime,
and file size) so repeated requests within a server lifetime are essentially
free.  Browsers that do not advertise WebP support receive the original PNG via
a standard ``flask.send_file`` call.
"""

from __future__ import annotations

import hashlib
import io
import os
from functools import lru_cache
from pathlib import Path

from flask import Response, send_file
from PIL import Image

# ---------------------------------------------------------------------------
# Internal cache
# ---------------------------------------------------------------------------

_WEBP_QUALITY = 85
_WEBP_METHOD = 4
_CACHE_MAX = 32  # maximum number of distinct (path, mtime, size) entries


@lru_cache(maxsize=_CACHE_MAX)
def _encode_webp(
    path: str, mtime: int, size: int
) -> bytes:  # noqa: ARG001 (size is cache key)
    """Return WebP-encoded bytes for *path*.

    The *mtime* and *size* parameters are only used as cache-key components;
    they ensure the cache is invalidated automatically when the file changes.
    """
    with Image.open(path) as img:
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=_WEBP_QUALITY, method=_WEBP_METHOD)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def maybe_serve_webp(image_path: Path, accept_header: str | None) -> Response:
    """Return a WebP response if the client accepts it, otherwise the original PNG.

    Parameters
    ----------
    image_path:
        Absolute path to the PNG file on disk.
    accept_header:
        Value of the ``Accept`` request header (may be *None*).

    Returns
    -------
    flask.Response
        Either a WebP response (``Content-Type: image/webp``) with an ETag, or
        the result of ``flask.send_file`` for the original PNG.
    """
    path_str = str(image_path)

    if not _client_accepts_webp(accept_header):
        return send_file(path_str, mimetype="image/png", conditional=True)

    stat = os.stat(path_str)
    mtime = int(stat.st_mtime)
    size = stat.st_size

    webp_bytes = _encode_webp(path_str, mtime, size)

    etag = _make_etag(path_str, mtime)
    response = Response(webp_bytes, mimetype="image/webp")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return response


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _client_accepts_webp(accept_header: str | None) -> bool:
    """Return *True* when *accept_header* explicitly lists ``image/webp``."""
    if not accept_header:
        return False
    return "image/webp" in accept_header


def _make_etag(path: str, mtime: int) -> str:
    """Produce a stable ETag string from *path*, *mtime*, and the literal ``"webp"``."""
    raw = f"{path}:{mtime}:webp"
    return hashlib.sha1(raw.encode()).hexdigest()  # noqa: S324 — not security-sensitive
