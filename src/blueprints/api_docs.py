"""API documentation blueprint — Swagger UI and OpenAPI spec endpoints."""

from __future__ import annotations

import json
import os

from flask import Blueprint, Response, g

from app_setup.security_middleware import allow_extra_csp_sources
from utils.sri import cdn_sri

api_docs_bp = Blueprint("api_docs", __name__)

# Resolved at import time — always relative to this module's location.
_SPEC_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "static", "openapi.json")
)

_SWAGGER_ORIGIN = "https://unpkg.com"
_SWAGGER_CSS_URL = f"{_SWAGGER_ORIGIN}/swagger-ui-dist@5.35.0/swagger-ui.css"
_SWAGGER_JS_URL = f"{_SWAGGER_ORIGIN}/swagger-ui-dist@5.35.0/swagger-ui-bundle.js"


@api_docs_bp.route("/api/docs", methods=["GET"])
def swagger_ui() -> Response:
    """Serve the Swagger UI HTML page pointing at /api/openapi.json."""
    # The app's CSP only allows this server's own scripts and styles, so
    # without these the page stayed blank on the Pi. Dev mode only reports
    # CSP violations, which is how it went unnoticed. The two files are
    # pinned by their integrity hashes below.
    allow_extra_csp_sources("script-src", _SWAGGER_ORIGIN)
    allow_extra_csp_sources("style-src", _SWAGGER_ORIGIN)
    nonce = getattr(g, "csp_nonce", "")
    css_integrity = cdn_sri("swagger-ui-css")
    js_integrity = cdn_sri("swagger-ui-bundle")

    css_integrity_attr = (
        f' integrity="{css_integrity}" crossorigin="anonymous"' if css_integrity else ""
    )
    js_integrity_attr = (
        f' integrity="{js_integrity}" crossorigin="anonymous"' if js_integrity else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>InkyPi API Docs</title>
  <link rel="stylesheet"
        href="{_SWAGGER_CSS_URL}"{css_integrity_attr} />
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="{_SWAGGER_JS_URL}"{js_integrity_attr}></script>
  <script nonce="{nonce}">
    SwaggerUIBundle({{
      url: "/api/openapi.json",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: "BaseLayout",
      deepLinking: true
    }});
  </script>
</body>
</html>"""
    return Response(html, status=200, mimetype="text/html")


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
