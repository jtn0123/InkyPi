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


def maybe_serve_webp(
    image_path: Path,
    accept_header: str | None,
    *,
    safe_root: Path | str,
) -> Response:
    """Return a WebP response if the client accepts it, otherwise the original PNG.

    Parameters
    ----------
    image_path:
        Absolute path to the PNG file on disk.
    accept_header:
        Value of the ``Accept`` request header (may be *None*).
    safe_root:
        Trusted directory the resolved *image_path* must live within. The
        function re-validates containment using ``realpath`` and raises
        :class:`ValueError` if the path escapes — defense in depth on top of
        any caller-side validation.

    Returns
    -------
    flask.Response
        Either a WebP response (``Content-Type: image/webp``) with an ETag, or
        the result of ``flask.send_file`` for the original PNG.

    Raises
    ------
    ValueError
        If *image_path* is not contained within *safe_root* after symlink
        resolution.
    """
    safe_path = _validate_under_root(image_path, safe_root)

    if not _client_accepts_webp(accept_header):
        return send_file(safe_path, mimetype="image/png", conditional=True)

    stat = os.stat(safe_path)
    mtime = int(stat.st_mtime)
    size = stat.st_size

    webp_bytes = _encode_webp(safe_path, mtime, size)

    etag = _make_etag(safe_path, mtime)
    response = Response(webp_bytes, mimetype="image/webp")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return response


def _validate_under_root(image_path: Path, safe_root: Path | str) -> str:
    """Resolve *image_path* and assert it lives under *safe_root*.

    Returns the resolved absolute path string. This is the sanitization
    boundary that downstream filesystem calls rely on.
    """
    root = os.path.realpath(str(safe_root))
    candidate = os.path.realpath(str(image_path))
    if os.path.commonpath([root, candidate]) != root:
        raise ValueError("image_path escapes safe_root")
    return candidate


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
    # sha256 used purely for cache-key fingerprinting (not security-sensitive),
    # but we use it instead of sha1 to keep SonarCloud quiet (rule S4790).
    return hashlib.sha256(raw.encode()).hexdigest()[:40]
