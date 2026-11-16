# pyright: reportMissingImports=false
"""Tests for the /api/docs and /api/openapi.json endpoints (JTN-285)."""

from __future__ import annotations

import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from flask import Flask
from flask.testing import FlaskClient

import blueprints.api_docs as api_docs
from utils.sri import compute_sri

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# GET /api/docs — Swagger UI HTML page
# ---------------------------------------------------------------------------


@pytest.fixture
def static_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the docs page at an empty static folder."""
    monkeypatch.setattr(api_docs, "_STATIC_ROOT", tmp_path)
    monkeypatch.delenv("INKYPI_CSP", raising=False)
    return tmp_path


@pytest.fixture
def swagger_files(static_root: Path) -> dict[str, Path]:
    """Install stand-in Swagger UI files, as update_vendors.sh would."""
    files: dict[str, Path] = {}
    for name, body in (
        (api_docs.SWAGGER_CSS, "#swagger-ui { margin: 0; }\n"),
        (api_docs.SWAGGER_JS, "window.SwaggerUIBundle = function () {};\n"),
    ):
        path = static_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        files[name] = path
    return files


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
    """Collect <script>, stylesheet <link> and <a> attributes from a page."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str]] = []
        self.stylesheets: list[dict[str, str]] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "script":
            self.scripts.append(values)
        elif tag == "link" and values.get("rel") == "stylesheet":
            self.stylesheets.append(values)
        elif tag == "a":
            self.links.append(values.get("href", ""))


def _page(resp: Any) -> _Tags:
    page = _Tags()
    page.feed(resp.data.decode("utf-8"))
    return page


def test_api_docs_serves_swagger_ui_from_this_device(
    client: FlaskClient, swagger_files: dict[str, Path]
) -> None:
    resp = client.get("/api/docs")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    body = resp.data.decode("utf-8")
    assert 'id="swagger-ui"' in body
    assert "/api/openapi.json" in body

    page = _page(resp)
    loaded = [a for a in page.scripts if a.get("src")] + page.stylesheets
    assert len(loaded) == 2
    for attrs, name in zip(
        loaded, (api_docs.SWAGGER_JS, api_docs.SWAGGER_CSS), strict=True
    ):
        url = urlsplit(attrs.get("src") or attrs["href"])
        # Same origin, from the vendored copy, pinned by its own hash.
        assert not url.scheme and not url.netloc
        assert url.path == f"/static/{name}"
        assert attrs["integrity"] == compute_sri(swagger_files[name])


def test_api_docs_fits_the_default_csp(
    client: FlaskClient, swagger_files: dict[str, Path]
) -> None:
    # The page used to widen script-src and style-src to unpkg.com; now it
    # gets exactly the policy every other page gets.
    resp = client.get("/api/docs")
    csp = _csp(resp)
    other = _csp(client.get("/api/openapi.json"))

    def without_nonce(directives: dict[str, list[str]]) -> dict[str, list[str]]:
        return {
            name: [s for s in sources if not s.startswith("'nonce-")]
            for name, sources in directives.items()
        }

    assert without_nonce(csp) == without_nonce(other)
    assert csp["script-src"][0] == "'self'"
    assert not any(
        re.match(r"https?:", s) for s in csp["script-src"] + csp["style-src"]
    )
    inline = [a for a in _page(resp).scripts if not a.get("src")]
    assert len(inline) == 1
    assert f"'nonce-{inline[0]['nonce']}'" in csp["script-src"]


def test_api_docs_rehashes_an_updated_file(
    client: FlaskClient, swagger_files: dict[str, Path]
) -> None:
    js = swagger_files[api_docs.SWAGGER_JS]
    before = _page(client.get("/api/docs")).scripts[0]["integrity"]
    mtime_ns = js.stat().st_mtime_ns
    js.write_text("window.SwaggerUIBundle = function () { return 2; };\n")
    os.utime(js, ns=(mtime_ns + 10**9, mtime_ns + 10**9))

    after = _page(client.get("/api/docs")).scripts[0]["integrity"]
    assert after == compute_sri(js)
    assert after != before


@pytest.mark.parametrize("missing", [None, api_docs.SWAGGER_CSS, api_docs.SWAGGER_JS])
def test_api_docs_without_swagger_ui_says_how_to_install_it(
    client: FlaskClient, static_root: Path, missing: str | None
) -> None:
    if missing is not None:
        # One file present is still not enough to load the explorer.
        present = (
            api_docs.SWAGGER_JS
            if missing == api_docs.SWAGGER_CSS
            else api_docs.SWAGGER_CSS
        )
        (static_root / present).parent.mkdir(parents=True)
        (static_root / present).write_text("x", encoding="utf-8")

    resp = client.get("/api/docs")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "install/update_vendors.sh" in body
    page = _page(resp)
    assert page.scripts == [] and page.stylesheets == []
    assert "/api/openapi.json" in page.links


def test_swagger_files_are_the_ones_update_vendors_installs() -> None:
    vendors = (REPO_ROOT / "install" / "update_vendors.sh").read_text()
    ignored = (REPO_ROOT / ".gitignore").read_text().splitlines()
    for name in (api_docs.SWAGGER_CSS, api_docs.SWAGGER_JS):
        assert f"|src/static/{name}|" in vendors
        assert f"/src/static/{name}" in ignored


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
