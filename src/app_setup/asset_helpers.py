"""Asset bundling helpers for InkyPi (JTN-287).

Provides the ``bundled_asset`` Jinja2 global function and a Flask setup
helper that registers it on the application.

The function reads ``src/static/dist/manifest.json`` (written by
``scripts/build_assets.py``) and returns the versioned filename for a given
logical asset name (e.g. ``"common.js"`` → ``"common.bundle.abc12345.min.js"``).

Graceful degradation: if the manifest does not exist (e.g. in local dev
without running build_assets.py), the function returns an empty string and
the template ``{% if bundled_assets_enabled %}`` guard suppresses the tags.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from flask import Flask

logger = logging.getLogger(__name__)

_MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent / "static" / "dist" / "manifest.json"
)

# Module-level cache so we parse the file once per process.
_manifest_cache: dict[str, str] | None = None
_manifest_loaded: bool = False


def _load_manifest() -> dict[str, str]:
    """Return the asset manifest dict, loading from disk on first call."""
    global _manifest_cache, _manifest_loaded
    if _manifest_loaded:
        return _manifest_cache or {}
    _manifest_loaded = True
    if _MANIFEST_PATH.is_file():
        try:
            _manifest_cache = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
            logger.debug("Loaded asset manifest from %s", _MANIFEST_PATH)
        except Exception as exc:  # pragma: no cover — I/O edge case
            logger.warning("Failed to parse asset manifest: %s", exc)
            _manifest_cache = {}
    else:
        logger.debug("Asset manifest not found at %s (dev mode?)", _MANIFEST_PATH)
        _manifest_cache = {}
    return _manifest_cache


def bundled_asset(name: str) -> str:
    """Return the versioned filename for *name*, or empty string if absent."""
    return _load_manifest().get(name, "")


def reload_manifest() -> None:
    """Force a fresh read of manifest.json on the next call.

    Useful in tests that write a temporary manifest.
    """
    global _manifest_cache, _manifest_loaded
    _manifest_cache = None
    _manifest_loaded = False


def setup_asset_helpers(app: Flask) -> None:
    """Register asset helpers as Jinja2 globals on *app*.

    Adds:
    - ``bundled_asset(name)`` — returns the versioned dist filename
    - ``bundled_assets_enabled`` — True when the manifest exists and is non-empty
    """
    manifest = _load_manifest()
    enabled = bool(manifest)

    app.jinja_env.globals["bundled_asset"] = bundled_asset
    app.jinja_env.globals["bundled_assets_enabled"] = enabled

    if enabled:
        logger.debug(
            "Asset bundling enabled; manifest contains %d entries", len(manifest)
        )
    else:
        logger.debug(
            "Asset bundling disabled (manifest missing or empty); "
            "serving individual script/style tags"
        )


def _override_manifest_path_for_tests(path: str | os.PathLike) -> None:
    """Redirect manifest reads to *path* (test helper only)."""
    global _MANIFEST_PATH
    _MANIFEST_PATH = Path(path)
    reload_manifest()
