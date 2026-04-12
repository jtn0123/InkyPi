"""Regression tests for error pages (JTN-641).

Users who land on a 404 page must still have access to the full site
navigation (History, Playlists, Settings) so there is a discovery path
from any broken URL.
"""

from __future__ import annotations


def test_404_page_includes_main_navigation(client):
    """404 HTML page must expose links to History, Playlists, and Settings."""
    resp = client.get("/this-url-does-not-exist", headers={"Accept": "text/html"})
    assert resp.status_code == 404
    body = resp.data
    # Nav links users need for site discovery.
    assert b'href="/playlist"' in body
    assert b'href="/history"' in body
    assert b'href="/settings"' in body
    # Still has the Home link and the "Page Not Found" heading.
    assert b"Page Not Found" in body
    assert b'href="/"' in body


def test_404_page_includes_nav_landmark(client):
    """404 page should render a <nav> landmark for site navigation."""
    resp = client.get("/another-bogus-url", headers={"Accept": "text/html"})
    assert resp.status_code == 404
    assert b'aria-label="Site navigation"' in resp.data


def test_404_json_response_unaffected(client):
    """JSON clients should still receive a structured JSON error, not HTML."""
    resp = client.get("/still-not-there", headers={"Accept": "application/json"})
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["success"] is False
    assert "Not found" in data["error"]
