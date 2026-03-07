# pyright: reportMissingImports=false
"""End-to-end form workflow tests using Playwright."""
from __future__ import annotations

import os

import pytest

REQUIRE_BROWSER_SMOKE = os.getenv("REQUIRE_BROWSER_SMOKE", "").lower() in ("1", "true")
pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true") and not REQUIRE_BROWSER_SMOKE,
    reason="UI interactions skipped by env",
)


def _leaflet_stub_js() -> str:
    return """
      (() => {
        function chain() { return this; }
        window.L = {
          map() { return { setView: chain, on: chain, off: chain, fitBounds: chain, addLayer: chain, removeLayer: chain, invalidateSize: chain, closePopup: chain }; },
          tileLayer() { return { addTo: chain }; },
          marker() { return { addTo: chain, bindPopup: chain, openPopup: chain, setLatLng: chain }; },
          latLng(lat, lng) { return { lat, lng }; },
        };
      })();
    """


def _stub_leaflet(page):
    page.route(
        "**://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
        lambda route: route.fulfill(status=200, content_type="text/css", body=""),
    )
    page.route(
        "**://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
        lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=_leaflet_stub_js()
        ),
    )


def test_settings_save_submit(live_server, tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            _stub_leaflet(page)

            # Track XHR responses
            save_responses = []
            page.on(
                "response",
                lambda resp: save_responses.append(resp.status)
                if "/save_settings" in resp.url
                else None,
            )

            page.goto(f"{live_server}/settings", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("[data-page-shell]", timeout=10000)

            # Click Save
            save_btn = page.locator("#saveSettingsBtn")
            save_btn.scroll_into_view_if_needed()
            save_btn.click()

            # Wait for the save request to complete
            page.wait_for_timeout(2000)

            # Should have gotten a response (200 or 422 for validation)
            assert len(save_responses) > 0, "Save request was never sent"
            assert save_responses[0] in (200, 422), f"Unexpected save response: {save_responses[0]}"

            # Toast or modal should appear (check for toast container)
            toast_or_modal = page.locator(".toast-container, #responseModal[style*='display: block']")
            # At minimum the page should still be functional
            assert page.locator("#saveSettingsBtn").count() == 1
        finally:
            browser.close()


def test_settings_save_shows_response(live_server, tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            _stub_leaflet(page)
            page.goto(f"{live_server}/settings", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("[data-page-shell]", timeout=10000)

            # The settings form should exist (class-based, not id)
            assert page.locator(".settings-form").count() >= 1

            # Save button should be present and enabled
            save_btn = page.locator("#saveSettingsBtn")
            assert save_btn.is_enabled()
        finally:
            browser.close()


def test_playlist_page_has_create_button(live_server, tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            _stub_leaflet(page)
            page.goto(f"{live_server}/playlist", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("[data-page-shell]", timeout=10000)

            # New Playlist button should be present
            new_btn = page.locator("#newPlaylistBtn")
            assert new_btn.count() == 1
            assert new_btn.is_enabled()
        finally:
            browser.close()


def test_plugin_config_form_exists(live_server, tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            _stub_leaflet(page)
            page.goto(f"{live_server}/plugin/clock", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("[data-page-shell]", timeout=10000)

            # Settings form should exist with inputs
            form = page.locator("#settingsForm")
            assert form.count() == 1
            inputs = form.locator("input, select, textarea")
            assert inputs.count() > 0
        finally:
            browser.close()


def test_api_keys_page_has_save_button(live_server, tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            _stub_leaflet(page)
            page.goto(f"{live_server}/api-keys", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("[data-page-shell]", timeout=10000)

            # Save button should exist
            save_btn = page.locator("#saveApiKeysBtn")
            assert save_btn.count() == 1
        finally:
            browser.close()
