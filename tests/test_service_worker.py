# pyright: reportMissingImports=false
"""Tests for the service worker route (JTN-303)."""


def test_sw_js_returns_200(client):
    """GET /sw.js returns HTTP 200."""
    response = client.get("/sw.js")
    assert response.status_code == 200


def test_sw_js_content_type_javascript(client):
    """GET /sw.js returns application/javascript content type."""
    response = client.get("/sw.js")
    assert "application/javascript" in response.content_type


def test_sw_js_contains_cache_name(client):
    """GET /sw.js body contains the expected CACHE_NAME constant."""
    response = client.get("/sw.js")
    body = response.data.decode("utf-8")
    assert "inkypi-shell-v1" in body


def test_sw_js_service_worker_allowed_header(client):
    """GET /sw.js includes Service-Worker-Allowed header set to '/'."""
    response = client.get("/sw.js")
    assert response.headers.get("Service-Worker-Allowed") == "/"
