# pyright: reportMissingImports=false
"""Tests for the /api/docs and /api/openapi.json endpoints (JTN-285)."""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# GET /api/docs — Swagger UI HTML page
# ---------------------------------------------------------------------------


def test_api_docs_returns_200(client):
    """GET /api/docs should return 200 OK."""
    resp = client.get("/api/docs")
    assert resp.status_code == 200


def test_api_docs_content_type_is_html(client):
    """GET /api/docs should serve an HTML response."""
    resp = client.get("/api/docs")
    assert "text/html" in resp.content_type


def test_api_docs_contains_swagger_ui(client):
    """GET /api/docs HTML must reference swagger-ui so the browser loads the explorer."""
    resp = client.get("/api/docs")
    body = resp.data.decode("utf-8")
    assert "swagger-ui" in body.lower()


def test_api_docs_points_to_openapi_spec(client):
    """Swagger UI page must reference /api/openapi.json as its spec URL."""
    resp = client.get("/api/docs")
    body = resp.data.decode("utf-8")
    assert "/api/openapi.json" in body


# ---------------------------------------------------------------------------
# GET /api/openapi.json — OpenAPI spec
# ---------------------------------------------------------------------------


def test_openapi_json_returns_200(client):
    """GET /api/openapi.json should return 200 OK."""
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200


def test_openapi_json_content_type(client):
    """GET /api/openapi.json must set Content-Type: application/json."""
    resp = client.get("/api/openapi.json")
    assert "application/json" in resp.content_type


def test_openapi_json_is_valid_json(client):
    """Response body must parse as JSON without error."""
    resp = client.get("/api/openapi.json")
    spec = json.loads(resp.data)
    assert isinstance(spec, dict)


def test_openapi_spec_has_required_fields(client):
    """Spec must contain openapi, info, paths keys (OpenAPI 3.0 minimum)."""
    resp = client.get("/api/openapi.json")
    spec = json.loads(resp.data)
    assert "openapi" in spec
    assert spec["openapi"].startswith("3.")
    assert "info" in spec
    assert "paths" in spec


def test_openapi_spec_info_title(client):
    """info.title must be 'InkyPi API'."""
    resp = client.get("/api/openapi.json")
    spec = json.loads(resp.data)
    assert spec["info"]["title"] == "InkyPi API"


def test_openapi_spec_info_has_version(client):
    """info.version must be a non-empty string."""
    resp = client.get("/api/openapi.json")
    spec = json.loads(resp.data)
    assert isinstance(spec["info"].get("version"), str)
    assert spec["info"]["version"]


# ---------------------------------------------------------------------------
# Spec drift guard — every documented path must exist in the Flask url_map
# ---------------------------------------------------------------------------


def test_openapi_paths_exist_in_url_map(client, flask_app):
    """Every path in the OpenAPI spec must correspond to a real route in the app.

    This test prevents the spec from documenting endpoints that were removed or
    renamed without updating the spec.

    OpenAPI uses {param} style; Flask uses <param> style.  We normalise both to
    a common placeholder before comparing.
    """
    import re

    resp = client.get("/api/openapi.json")
    spec = json.loads(resp.data)

    def _normalise(path: str) -> str:
        # Replace {anything} or <anything> with a common token
        return re.sub(r"[{<][^}>]+[}>]", "{p}", path)

    # Build the set of normalised Flask routes
    flask_paths: set[str] = set()
    for rule in flask_app.url_map.iter_rules():
        flask_paths.add(_normalise(rule.rule))

    missing: list[str] = []
    for path in spec.get("paths", {}):
        normalised = _normalise(path)
        if normalised not in flask_paths:
            missing.append(path)

    assert not missing, (
        f"OpenAPI spec documents paths not registered in Flask url_map: {missing}\n"
        "Update the spec or register the missing routes."
    )


# ---------------------------------------------------------------------------
# Minimum endpoint count guard
# ---------------------------------------------------------------------------


def test_openapi_spec_has_at_least_six_endpoints(client):
    """Spec must document at least 6 distinct paths (MVP requirement)."""
    resp = client.get("/api/openapi.json")
    spec = json.loads(resp.data)
    paths = spec.get("paths", {})
    assert (
        len(paths) >= 6
    ), f"Expected at least 6 documented paths, got {len(paths)}: {list(paths.keys())}"
