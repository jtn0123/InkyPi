"""Tests for HTMX progressive enhancement (JTN-288).

Covers the history page pagination partial swap — the first HTMX-enabled
feature in InkyPi.  The same /history URL serves either the full page or
the grid partial depending on the presence of the ``HX-Request: true``
header (progressive enhancement — no-JS users follow normal link navigation).
"""

import os

from PIL import Image


def _make_history_images(history_dir: str, count: int = 2) -> None:
    os.makedirs(history_dir, exist_ok=True)
    for i in range(count):
        name = f"display_20250101_{i:06d}.png"
        Image.new("RGB", (10, 10), "white").save(os.path.join(history_dir, name))


def test_htmx_partial_returned_when_hx_header_present(client, device_config_dev):
    """GET /history with HX-Request header returns the grid partial, not a full HTML page."""
    _make_history_images(device_config_dev.history_image_dir)

    resp = client.get("/history", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Partial must NOT include the outer html shell
    assert "<html" not in body
    assert "<head>" not in body
    # Partial MUST include the grid container
    assert "history-grid-container" in body


def test_full_page_returned_without_hx_header(client, device_config_dev):
    """GET /history without HX-Request header returns a full HTML page."""
    _make_history_images(device_config_dev.history_image_dir)

    resp = client.get("/history")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Full page includes the outer HTML shell
    assert "<html" in body
    assert "<!DOCTYPE html>" in body
    # And should still contain the grid container
    assert "history-grid-container" in body


def test_htmx_script_loaded_in_base(client):
    """The base template includes htmx.min.js so HTMX is available on all pages."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "htmx.min.js" in body


def test_htmx_partial_pagination_links_have_hx_attributes(client, device_config_dev):
    """When multiple pages exist the partial pagination links include hx-get attributes."""
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    # Create enough images to exceed page 1 (default per_page=24)
    for i in range(30):
        name = f"display_20250101_{i:06d}.png"
        Image.new("RGB", (10, 10), "white").save(os.path.join(d, name))

    resp = client.get("/history?per_page=10&page=2", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Pagination links in the partial should carry hx-get for HTMX navigation
    assert "hx-get" in body
    assert "hx-target" in body
    assert "hx-swap" in body


def test_history_partial_works_without_js_via_plain_links(client, device_config_dev):
    """Full page response contains plain href links for no-JS progressive enhancement."""
    _make_history_images(device_config_dev.history_image_dir, count=30)

    # Request as plain browser (no HX-Request header)
    resp = client.get("/history?per_page=10&page=1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Normal <a href> links must be present for no-JS users
    assert 'href="/history?' in body
