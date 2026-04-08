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

from flask import Response, send_from_directory
from PIL import Image
from werkzeug.exceptions import NotFound

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
    safe_root: Path | str,
    filename: str,
    accept_header: str | None,
) -> Response:
    """Return a WebP response if the client accepts it, otherwise the original PNG.

    Parameters
    ----------
    safe_root:
        Trusted directory the file lives in. Must be a path the application
        controls (not user-supplied).
    filename:
        Name of the PNG file inside *safe_root*. May contain user-controlled
        data; sanitization is delegated to ``flask.send_from_directory`` which
        rejects path-traversal attempts.
    accept_header:
        Value of the ``Accept`` request header (may be *None*).

    Returns
    -------
    flask.Response
        Either a WebP response (``Content-Type: image/webp``) with an ETag, or
        the result of ``flask.send_from_directory`` for the original PNG.

    Raises
    ------
    werkzeug.exceptions.NotFound
        If the resolved file does not exist or escapes *safe_root*.
    """
    root_str = str(safe_root)

    if not _client_accepts_webp(accept_header):
        # send_from_directory performs path-traversal validation internally;
        # this is the recognized sanitization sink.
        return send_from_directory(root_str, filename, mimetype="image/png")

    # For the WebP path we still need an absolute filesystem path. Re-use
    # send_from_directory's validation by calling it once to resolve, then
    # falling back to a direct read of the same validated path. The simplest
    # way is to reconstruct the path via safe_join semantics: any traversal
    # attempt on filename would have already raised in the PNG branch above
    # for unfetched callers, but we re-validate here defensively.
    safe_path = _safe_join(root_str, filename)

    stat = os.stat(safe_path)
    mtime = int(stat.st_mtime)
    size = stat.st_size

    webp_bytes = _encode_webp(safe_path, mtime, size)

    etag = _make_etag(safe_path, mtime)
    response = Response(webp_bytes, mimetype="image/webp")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return response


def _safe_join(root: str, filename: str) -> str:
    """Resolve *filename* under *root* with path-traversal protection.

    Returns an absolute filesystem path. Raises :class:`NotFound` if the
    resolved path escapes *root* or does not exist — mirroring the behavior of
    ``send_from_directory`` so callers see consistent error semantics.
    """
    base = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(base, filename))
    if os.path.commonpath([base, candidate]) != base:
        raise NotFound()
    if not os.path.isfile(candidate):
        raise NotFound()
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
