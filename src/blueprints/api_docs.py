"""API documentation blueprint — Swagger UI and OpenAPI spec endpoints."""

from __future__ import annotations

import json
import os

from flask import Blueprint, Response

api_docs_bp = Blueprint("api_docs", __name__)

# Resolved at import time — always relative to this module's location.
_SPEC_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "static", "openapi.json")
)


@api_docs_bp.route("/api/docs", methods=["GET"])
def swagger_ui() -> Response:
    """Serve the Swagger UI HTML page pointing at /api/openapi.json."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>InkyPi API Docs</title>
  <link rel="stylesheet"
        href="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui.css" />
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: "/api/openapi.json",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: "BaseLayout",
      deepLinking: true
    });
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
