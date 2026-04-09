"""Subresource Integrity (SRI) helpers for InkyPi (JTN-478).

Provides:
- ``compute_sri(file_path)`` — compute sha384-<base64> for an on-disk file
- ``sri_for(static_rel_path)`` — Jinja-friendly; resolves relative to static/,
  caches per process, returns "" + logs on error
- ``cdn_sri(key)`` — looks up a pre-computed hash in cdn_manifest.json
- ``init_sri(app)`` — registers ``sri_for`` and ``cdn_sri`` as Jinja globals
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path

from flask import Flask

logger = logging.getLogger(__name__)

# Resolved at import time so the module can be used without a Flask context.
_STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
_CDN_MANIFEST_PATH = _STATIC_ROOT / "cdn_manifest.json"

# Per-process caches — avoids recomputing hashes on every request.
_sri_cache: dict[str, str] = {}
_cdn_manifest_cache: dict[str, dict] | None = None
_cdn_manifest_loaded: bool = False


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_sri(file_path: str | Path) -> str:
    """Return the ``sha384-<base64>`` SRI hash for *file_path*.

    Raises ``FileNotFoundError`` if the file does not exist.
    """
    path = Path(file_path)
    digest = hashlib.sha384(path.read_bytes()).digest()
    b64 = base64.b64encode(digest).decode("ascii")
    return f"sha384-{b64}"


# ---------------------------------------------------------------------------
# Jinja-friendly helpers with caching + graceful degradation
# ---------------------------------------------------------------------------


def sri_for(static_rel_path: str) -> str:
    """Return the SRI hash for a file relative to ``src/static/``.

    Results are cached for the lifetime of the process.  Returns an empty
    string (and logs a warning) if the file does not exist or cannot be read
    so that a missing vendor file never crashes the page.
    """
    if static_rel_path in _sri_cache:
        return _sri_cache[static_rel_path]

    full_path = _STATIC_ROOT / static_rel_path
    try:
        result = compute_sri(full_path)
    except FileNotFoundError:
        logger.warning(
            "sri_for: static asset not found, SRI will be omitted: %s", full_path
        )
        result = ""
    except Exception as exc:
        logger.warning("sri_for: could not compute SRI for %s: %s", full_path, exc)
        result = ""

    _sri_cache[static_rel_path] = result
    return result


def _load_cdn_manifest() -> dict[str, dict]:
    """Return the CDN manifest dict, loading from disk on first call."""
    global _cdn_manifest_cache, _cdn_manifest_loaded
    if _cdn_manifest_loaded:
        return _cdn_manifest_cache or {}
    _cdn_manifest_loaded = True
    if _CDN_MANIFEST_PATH.is_file():
        try:
            _cdn_manifest_cache = json.loads(
                _CDN_MANIFEST_PATH.read_text(encoding="utf-8")
            )
            logger.debug("Loaded CDN manifest from %s", _CDN_MANIFEST_PATH)
        except Exception as exc:
            logger.warning("Failed to parse CDN manifest: %s", exc)
            _cdn_manifest_cache = {}
    else:
        logger.debug("CDN manifest not found at %s", _CDN_MANIFEST_PATH)
        _cdn_manifest_cache = {}
    return _cdn_manifest_cache or {}


def cdn_sri(key: str) -> str:
    """Return the pre-computed SRI hash for CDN asset *key*.

    The hash is read from ``src/static/cdn_manifest.json`` which is populated
    by ``scripts/update_cdn_sri.py``.  Returns an empty string if the key is
    absent so that missing entries never crash the page.
    """
    manifest = _load_cdn_manifest()
    entry = manifest.get(key, {})
    return entry.get("integrity", "")


# ---------------------------------------------------------------------------
# Flask integration
# ---------------------------------------------------------------------------


def init_sri(app: Flask) -> None:
    """Register ``sri_for`` and ``cdn_sri`` as Jinja2 globals on *app*."""
    app.jinja_env.globals["sri_for"] = sri_for
    app.jinja_env.globals["cdn_sri"] = cdn_sri
    logger.debug("SRI Jinja helpers registered")


# ---------------------------------------------------------------------------
# Test helpers (not part of the public API)
# ---------------------------------------------------------------------------


def _reset_cache_for_tests() -> None:
    """Clear all module-level caches.  For use in tests only."""
    global _sri_cache, _cdn_manifest_cache, _cdn_manifest_loaded
    _sri_cache = {}
    _cdn_manifest_cache = None
    _cdn_manifest_loaded = False


def _override_cdn_manifest_path_for_tests(path: str | Path) -> None:
    """Redirect CDN manifest reads to *path*.  For use in tests only."""
    global _CDN_MANIFEST_PATH
    _CDN_MANIFEST_PATH = Path(path)
    _reset_cache_for_tests()
