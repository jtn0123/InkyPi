"""WebP on-the-fly encoding for image-serving routes.

Browsers that send ``Accept: image/webp`` receive a WebP-encoded version of
the PNG file.  The encoded bytes are cached in-process (keyed on path, mtime,
and file size) so repeated requests within a server lifetime are essentially
free.  Browsers that do not advertise WebP support receive the original PNG via
a standard ``flask.send_file`` call.

Callers may also ask for a narrower WebP thumbnail (for example the History
grid), restricted to :data:`THUMBNAIL_WIDTHS` so arbitrary sizes cannot fill
the cache or the CPU.
"""

from __future__ import annotations

import hashlib
import io
import os
from functools import lru_cache
from pathlib import Path

from flask import Response, request, send_from_directory
from PIL import Image
from werkzeug.exceptions import NotFound
from werkzeug.http import is_resource_modified

# `safe_join` lives in werkzeug.security and is only re-exported by
# werkzeug.utils, which does not list it in __all__.
from werkzeug.security import safe_join

from utils.http_utils import content_disposition

# ---------------------------------------------------------------------------
# Internal cache
# ---------------------------------------------------------------------------

_WEBP_QUALITY = 85
_WEBP_METHOD = 4
_CACHE_MAX = 32  # maximum number of distinct (path, mtime, size) entries
# Thumbnails are a few KB each; keep enough for a couple of History pages so
# they don't push full-size images out of the cache above.
_THUMB_CACHE_MAX = 64
#: Widths, in pixels, that callers may request with ``width=``.
THUMBNAIL_WIDTHS = frozenset({480})
_THUMB_MAX_HEIGHT = 10_000  # thumbnail() bounds both axes; only width matters


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


@lru_cache(maxsize=_THUMB_CACHE_MAX)
def _encode_webp_thumbnail(
    path: str, mtime: int, size: int, width: int
) -> bytes:  # noqa: ARG001 (mtime and size are cache keys)
    """Return WebP bytes for *path* scaled down to at most *width* pixels wide.

    Never upscales. Palette and bilevel images are converted first, because
    Pillow resamples those modes with nearest-neighbour only.
    """
    with Image.open(path) as img:
        thumb: Image.Image = img
        if img.mode not in ("RGB", "RGBA", "L"):
            has_alpha = img.mode.endswith("A") or "transparency" in img.info
            thumb = img.convert("RGBA" if has_alpha else "RGB")
        thumb.thumbnail((width, _THUMB_MAX_HEIGHT), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        thumb.save(buf, format="WEBP", quality=_WEBP_QUALITY, method=_WEBP_METHOD)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def maybe_serve_webp(
    safe_root: Path | str,
    filename: str,
    accept_header: str | None,
    width: int | None = None,
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
    width:
        Optional thumbnail width from :data:`THUMBNAIL_WIDTHS`. WebP clients
        get the image scaled down to it; other clients get the original PNG.

    Returns
    -------
    flask.Response
        Either a WebP response (``Content-Type: image/webp``) with an ETag, or
        the result of ``flask.send_from_directory`` for the original PNG.

    Raises
    ------
    werkzeug.exceptions.NotFound
        If the resolved file does not exist or escapes *safe_root*.
    ValueError
        If *width* is not one of :data:`THUMBNAIL_WIDTHS`.
    """
    if width is not None and width not in THUMBNAIL_WIDTHS:
        raise ValueError(f"unsupported thumbnail width: {width}")
    root_str = str(safe_root)

    if not _client_accepts_webp(accept_header):
        # send_from_directory performs path-traversal validation internally;
        # this is the recognized sanitization sink.
        resp = send_from_directory(root_str, filename, mimetype="image/png")
        resp.vary.add("Accept")
        resp.headers["Content-Disposition"] = content_disposition("inline", filename)
        return resp

    # For the WebP path we still need an absolute filesystem path. Re-use
    # send_from_directory's validation by calling it once to resolve, then
    # falling back to a direct read of the same validated path. The simplest
    # way is to reconstruct the path via safe_join semantics: any traversal
    # attempt on filename would have already raised in the PNG branch above
    # for unfetched callers, but we re-validate here defensively.
    safe_path = _safe_join(root_str, filename)

    stat = os.stat(safe_path)
    mtime = stat.st_mtime_ns
    size = stat.st_size

    variant = "webp" if width is None else f"webp-w{width}"
    etag = _make_etag(safe_path, mtime, size, variant)
    response = Response(mimetype="image/webp")
    response.set_etag(etag)
    response.vary.add("Accept")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Content-Disposition"] = content_disposition("inline", filename)
    # The ETag comes from the file's stat, so a revalidation that still
    # matches can be answered 304 without paying for a WebP encode.
    if request.method in ("GET", "HEAD") and not is_resource_modified(
        request.environ, etag=etag
    ):
        response.make_conditional(request)
        return response

    if width is None:
        response.set_data(_encode_webp(safe_path, mtime, size))
    else:
        response.set_data(_encode_webp_thumbnail(safe_path, mtime, size, width))
    response.make_conditional(request)
    return response


def _safe_join(root: str, filename: str) -> str:
    """Resolve *filename* under *root* with path-traversal protection.

    Wraps :func:`werkzeug.utils.safe_join`, which is the Flask-recommended
    sanitizer for joining a trusted base directory with an untrusted filename.
    Raises :class:`NotFound` if traversal is attempted or the file is missing.
    """
    joined = safe_join(root, filename)
    if joined is None or not os.path.isfile(joined):
        raise NotFound
    return joined


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _client_accepts_webp(accept_header: str | None) -> bool:
    """Return *True* when *accept_header* explicitly lists ``image/webp``."""
    if not accept_header:
        return False
    return "image/webp" in accept_header


def _make_etag(path: str, mtime: int, size: int, variant: str = "webp") -> str:
    """Produce a stable ETag string from *path*, *mtime*, *size* and *variant*."""
    raw = f"{path}:{mtime}:{size}:{variant}"
    # sha256 used purely for cache-key fingerprinting (not security-sensitive),
    # but we use it instead of sha1 to keep SonarCloud quiet (rule S4790).
    return hashlib.sha256(raw.encode()).hexdigest()[:40]
