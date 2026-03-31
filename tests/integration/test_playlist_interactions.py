# pyright: reportMissingImports=false
"""
UI Interaction Tests for playlist page.

Tests verify dynamic JavaScript behavior: keyboard reordering,
delete modals, and drag-and-drop in the playlist interface.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from tests.integration.browser_helpers import stub_leaflet

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from model import RefreshInfo  # noqa: E402


def _fixed_now(_device_config):
    return datetime(2025, 1, 1, 8, 0, 0, tzinfo=UTC)


def _prepare_playlist(device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "Weather B",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time="2025-01-01T07:55:00+00:00",
        image_hash=0,
        playlist="Default",
        plugin_instance="Clock A",
    )
    device_config_dev.write_config()


def test_playlist_keyboard_reorder(live_server, device_config_dev, monkeypatch):
    """Keyboard ArrowDown reorders plugin items and fires a reorder request."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    _prepare_playlist(device_config_dev)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            stub_leaflet(page)

            # Intercept reorder requests instead of letting them hit the server
            reorder_requests = []
            page.route(
                "**/reorder_plugins",
                lambda route: (
                    reorder_requests.append(route.request.url),
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body='{"success": true, "message": "Reordered"}',
                    ),
                ),
            )
            # Prevent location.reload from navigating away
            page.add_init_script("window.location.reload = () => {};")

            page.goto(
                f"{live_server}/playlist", wait_until="domcontentloaded", timeout=30000
            )
            page.wait_for_selector("[data-page-shell]", timeout=10000)

            # Verify plugin items exist
            items = page.locator(".plugin-item")
            assert items.count() >= 2, "Need at least 2 plugin items for reorder test"

            # Get initial order
            first_name = items.nth(0).get_attribute("data-instance-name")
            assert first_name == "Clock A"

            # Focus first item and press ArrowDown to reorder
            items.nth(0).focus()
            items.nth(0).press("ArrowDown")
            page.wait_for_timeout(500)

            # Verify reorder request was fired
            assert len(reorder_requests) > 0, "Reorder request should have been sent"
        finally:
            browser.close()


def test_playlist_delete_modal(live_server, device_config_dev, monkeypatch):
    """Delete playlist button opens confirmation modal and fires DELETE request."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    _prepare_playlist(device_config_dev)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            stub_leaflet(page)

            # Intercept delete requests
            delete_requests = []
            page.route(
                "**/delete_playlist/**",
                lambda route: (
                    delete_requests.append(route.request.method),
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body='{"success": true, "message": "Deleted"}',
                    ),
                ),
            )
            page.add_init_script("window.location.reload = () => {};")

            page.goto(
                f"{live_server}/playlist", wait_until="domcontentloaded", timeout=30000
            )
            page.wait_for_selector("[data-page-shell]", timeout=10000)

            # Click delete playlist button
            delete_btn = page.locator(".delete-playlist-btn").first
            delete_btn.click()

            # Verify delete modal appeared
            modal = page.locator("#deletePlaylistModal")
            page.wait_for_timeout(300)
            assert modal.is_visible(), "Delete playlist modal should be visible"

            # Confirm delete
            page.locator("#confirmDeletePlaylistBtn").click()
            page.wait_for_timeout(500)

            # Verify DELETE request was sent
            assert any(
                m == "DELETE" for m in delete_requests
            ), "DELETE request should have been sent"
        finally:
            browser.close()


def test_playlist_delete_instance_modal(live_server, device_config_dev, monkeypatch):
    """Delete instance button opens confirmation modal and fires POST request."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    _prepare_playlist(device_config_dev)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            stub_leaflet(page)

            # Intercept delete instance requests
            delete_requests = []
            page.route(
                "**/delete_plugin_instance",
                lambda route: (
                    delete_requests.append(route.request.method),
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body='{"success": true, "message": "Deleted"}',
                    ),
                ),
            )
            page.add_init_script("window.location.reload = () => {};")

            page.goto(
                f"{live_server}/playlist", wait_until="domcontentloaded", timeout=30000
            )
            page.wait_for_selector("[data-page-shell]", timeout=10000)

            # Click delete instance button on first plugin
            delete_btn = page.locator(".delete-instance-btn").first
            delete_btn.click()

            # Verify delete instance modal appeared
            modal = page.locator("#deleteInstanceModal")
            page.wait_for_timeout(300)
            assert modal.is_visible(), "Delete instance modal should be visible"

            # Confirm delete
            page.locator("#confirmDeleteInstanceBtn").click()
            page.wait_for_timeout(500)

            # Verify POST request was sent
            assert any(
                m == "POST" for m in delete_requests
            ), "POST delete request should have been sent"
        finally:
            browser.close()
