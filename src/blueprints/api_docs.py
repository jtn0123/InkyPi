"""API documentation blueprint — Swagger UI and OpenAPI spec endpoints."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, Response, render_template

from utils.sri import compute_sri

api_docs_bp = Blueprint("api_docs", __name__)

# Resolved at import time — always relative to this module's location.
_SPEC_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "static", "openapi.json")
)
_STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"

# Swagger UI is served from this device, so the page fits the app's default
# CSP ('self' plus the nonce for the start-up script) with no exceptions.
# install/update_vendors.sh downloads both files at install and on every
# update, each checked against its pinned sha256; they are git-ignored.
SWAGGER_CSS = "vendor/swagger-ui/swagger-ui.css"
SWAGGER_JS = "vendor/swagger-ui/swagger-ui-bundle.js"


@dataclass(frozen=True)
class SwaggerAssets:
    """The two Swagger UI files, as static paths with their SRI hashes."""

    css: str
    css_integrity: str
    js: str
    js_integrity: str


@lru_cache(maxsize=8)
def _integrity(path: Path, mtime_ns: int) -> str:
    """SRI hash of *path*; *mtime_ns* makes an updated file hash again."""
    return compute_sri(path)


def swagger_assets() -> SwaggerAssets | None:
    """The installed Swagger UI files, or None when either is missing.

    The page is only rendered with both integrity hashes: one it can't hash
    is treated as missing, never served without its integrity attribute.
    """
    hashes = []
    for name in (SWAGGER_CSS, SWAGGER_JS):
        path = _STATIC_ROOT / name
        try:
            hashes.append(_integrity(path, path.stat().st_mtime_ns))
        except OSError:
            return None
    css_integrity, js_integrity = hashes
    return SwaggerAssets(SWAGGER_CSS, css_integrity, SWAGGER_JS, js_integrity)


@api_docs_bp.route("/api/docs", methods=["GET"])
def swagger_ui() -> Response:
    """Serve the Swagger UI page, pointed at /api/openapi.json.

    Without the vendored files the page says how to install them and links
    the raw spec, rather than showing a blank explorer. It still answers 200,
    as pages do whose vendored Chart.js is missing: the page itself works.
    """
    html = render_template("api_docs.html", swagger=swagger_assets())
    return Response(html, mimetype="text/html")


@api_docs_bp.route("/api/openapi.json", methods=["GET"])
def openapi_spec() -> Response:
    """Serve the OpenAPI 3.0 spec as JSON."""
    with open(_SPEC_PATH, encoding="utf-8") as f:
        spec = json.load(f)
    return Response(
        json.dumps(spec, indent=2),
        status=200,
        mimetype="application/json",
    )
