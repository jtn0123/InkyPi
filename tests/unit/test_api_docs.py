# pyright: reportMissingImports=false
"""Tests for the /api/docs and /api/openapi.json endpoints (JTN-285)."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import pytest
from flask import Flask
from flask.testing import FlaskClient

# ---------------------------------------------------------------------------
# GET /api/docs — Swagger UI HTML page
# ---------------------------------------------------------------------------


def test_api_docs_returns_200(client: FlaskClient) -> None:
    """GET /api/docs should return 200 OK."""
    resp = client.get("/api/docs")
    assert resp.status_code == 200


def test_api_docs_content_type_is_html(client: FlaskClient) -> None:
    """GET /api/docs should serve an HTML response."""
    resp = client.get("/api/docs")
    assert "text/html" in resp.content_type


def test_api_docs_contains_swagger_ui(client: FlaskClient) -> None:
    """GET /api/docs HTML must reference swagger-ui so the browser loads the explorer."""
    resp = client.get("/api/docs")
    body = resp.data.decode("utf-8")
    assert "swagger-ui" in body.lower()


def test_api_docs_points_to_openapi_spec(client: FlaskClient) -> None:
    """Swagger UI page must reference /api/openapi.json as its spec URL."""
    resp = client.get("/api/docs")
    body = resp.data.decode("utf-8")
    assert "/api/openapi.json" in body


def _csp(resp: Any) -> dict[str, list[str]]:
    header = resp.headers.get("Content-Security-Policy") or resp.headers.get(
        "Content-Security-Policy-Report-Only", ""
    )
    directives: dict[str, list[str]] = {}
    for part in header.split(";"):
        name, *sources = part.split()
        directives[name] = sources
    return directives


class _Tags(HTMLParser):
    """Collect <script> attributes and stylesheet links from a page."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str]] = []
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "script":
            self.scripts.append(values)
        elif tag == "link" and values.get("rel") == "stylesheet":
            self.stylesheets.append(values["href"])


def test_api_docs_page_is_allowed_by_its_own_csp(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The default CSP blocked Swagger UI from unpkg and the inline start-up
    # script, so the page was blank on the Pi (dev mode only reports).
    monkeypatch.delenv("INKYPI_CSP", raising=False)
    resp = client.get("/api/docs")
    body = resp.data.decode("utf-8")
    csp = _csp(resp)

    def origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    page = _Tags()
    page.feed(body)
    scripts = [a["src"] for a in page.scripts if a.get("src")]
    inline = [a for a in page.scripts if not a.get("src")]
    assert scripts and inline and page.stylesheets
    for url in scripts:
        assert origin(url) in csp["script-src"]
    for url in page.stylesheets:
        assert origin(url) in csp["style-src"]
    for attrs in inline:
        assert attrs.get("nonce") and f"'nonce-{attrs['nonce']}'" in csp["script-src"]


def test_api_docs_sources_do_not_leak_to_other_pages(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INKYPI_CSP", raising=False)
    client.get("/api/docs")
    other = _csp(client.get("/api/openapi.json"))
    assert other["script-src"][0] == "'self'"
    assert not any("unpkg" in s for s in other["script-src"] + other["style-src"])


# ---------------------------------------------------------------------------
# GET /api/openapi.json — OpenAPI spec
# ---------------------------------------------------------------------------


def test_openapi_json_returns_200(client: FlaskClient) -> None:
    """GET /api/openapi.json should return 200 OK."""
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200


def test_openapi_json_content_type(client: FlaskClient) -> None:
    """GET /api/openapi.json must set Content-Type: application/json."""
    resp = client.get("/api/openapi.json")
    assert "application/json" in resp.content_type


def test_openapi_json_is_valid_json(client: FlaskClient) -> None:
    """Response body must parse as JSON without error."""
    resp = client.get("/api/openapi.json")
    spec = json.loads(resp.data)
    assert isinstance(spec, dict)


def test_openapi_spec_has_required_fields(client: FlaskClient) -> None:
    """Spec must contain openapi, info, paths keys (OpenAPI 3.0 minimum)."""
    resp = client.get("/api/openapi.json")
    spec = json.loads(resp.data)
    assert "openapi" in spec
    assert spec["openapi"].startswith("3.")
    assert "info" in spec
    assert "paths" in spec


def test_openapi_spec_info_title(client: FlaskClient) -> None:
    """info.title must be 'InkyPi API'."""
    resp = client.get("/api/openapi.json")
    spec = json.loads(resp.data)
    assert spec["info"]["title"] == "InkyPi API"


def test_openapi_spec_info_has_version(client: FlaskClient) -> None:
    """info.version must be a non-empty string."""
    resp = client.get("/api/openapi.json")
    spec = json.loads(resp.data)
    assert isinstance(spec["info"].get("version"), str)
    assert spec["info"]["version"]


# ---------------------------------------------------------------------------
# Spec drift guard — every documented path must exist in the Flask url_map
# ---------------------------------------------------------------------------


def test_openapi_paths_exist_in_url_map(client: FlaskClient, flask_app: Flask) -> Any:
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


def test_openapi_spec_has_at_least_six_endpoints(client: FlaskClient) -> None:
    """Spec must document at least 6 distinct paths (MVP requirement)."""
    resp = client.get("/api/openapi.json")
    spec = json.loads(resp.data)
    paths = spec.get("paths", {})
    assert (
        len(paths) >= 6
    ), f"Expected at least 6 documented paths, got {len(paths)}: {list(paths.keys())}"
