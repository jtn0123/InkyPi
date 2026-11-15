# pyright: reportMissingImports=false
"""
UI Interaction Tests for playlist page.

Tests verify dynamic JavaScript behavior: keyboard reordering,
delete modals, and drag-and-drop in the playlist interface.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pytest
from tests.integration.browser_helpers import is_response_to, stub_leaflet

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from model import RefreshInfo  # noqa: E402


def _fixed_now(_device_config: Any) -> Any:
    return datetime(2025, 1, 1, 8, 0, 0, tzinfo=UTC)


def _prepare_playlist(device_config_dev: Any) -> None:
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


def test_playlist_keyboard_reorder(
    live_server: str, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
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
            with page.expect_response(is_response_to("POST", "/reorder_plugins")):
                items.nth(0).press("ArrowDown")

            # Verify reorder request was fired
            assert len(reorder_requests) > 0, "Reorder request should have been sent"
        finally:
            browser.close()


def test_playlist_delete_modal(
    live_server: str, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delete playlist button opens confirmation modal and fires DELETE request."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    _prepare_playlist(device_config_dev)

    from playwright.sync_api import expect, sync_playwright

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
            expect(modal, "Delete playlist modal should be visible").to_be_visible()

            # Confirm delete
            with page.expect_response(
                is_response_to("DELETE", "/delete_playlist/", prefix=True)
            ):
                page.locator("#confirmDeletePlaylistBtn").click()

            # Verify DELETE request was sent
            assert any(
                m == "DELETE" for m in delete_requests
            ), "DELETE request should have been sent"
        finally:
            browser.close()


def test_playlist_delete_instance_modal(
    live_server: str, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delete instance button opens confirmation modal and fires POST request."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    _prepare_playlist(device_config_dev)

    from playwright.sync_api import expect, sync_playwright

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
            expect(modal, "Delete instance modal should be visible").to_be_visible()

            # Confirm delete
            with page.expect_response(
                is_response_to("POST", "/delete_plugin_instance")
            ):
                page.locator("#confirmDeleteInstanceBtn").click()

            # Verify POST request was sent
            assert any(
                m == "POST" for m in delete_requests
            ), "POST delete request should have been sent"
        finally:
            browser.close()


def _prepare_two_playlists_sharing_an_instance_name(device_config_dev: Any) -> None:
    """Default and Night each hold a clock instance called "Clock A"."""
    _prepare_playlist(device_config_dev)
    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Night", "20:00", "24:00")
    pm.get_playlist("Night").add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.write_config()


def _display_button(page: Any, playlist: str) -> Any:
    return page.locator(
        f'[data-playlist-action="display-instance"][data-playlist="{playlist}"]'
        '[data-instance="Clock A"]'
    )


def _row_of(button: Any) -> Any:
    return button.locator("xpath=ancestor::div[contains(@class, 'plugin-item')][1]")


def _press_display_and_hold_request(page: Any, button: Any) -> Any:
    """Press Display and return the request's route, not yet answered."""
    held: list[Any] = []
    page.route("**/display_plugin_instance", lambda route: held.append(route))
    with page.expect_request("**/display_plugin_instance"):
        button.click()
    for _ in range(100):
        if held:
            return held[0]
        page.wait_for_timeout(20)
    raise AssertionError("the display request never reached the route")


def test_playlist_display_now_spins_the_pressed_row_then_reloads_with_a_toast(
    live_server: str, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the pressed row spins, even when another playlist has the same
    instance name, and success reloads the page and shows the server's message."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    _prepare_two_playlists_sharing_an_instance_name(device_config_dev)

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            stub_leaflet(page)
            page.goto(
                f"{live_server}/playlist", wait_until="domcontentloaded", timeout=30000
            )
            page.wait_for_selector("[data-page-shell]", timeout=10000)

            night = _display_button(page, "Night")
            default = _display_button(page, "Default")
            night_row, default_row = _row_of(night), _row_of(default)
            route = _press_display_and_hold_request(page, night)

            # While the panel is drawing, the Night row is the busy one.
            expect(night_row).to_have_attribute("aria-busy", "true")
            expect(night_row.locator(".loading-indicator")).to_be_visible()
            expect(night).to_be_disabled()
            expect(default_row).not_to_have_attribute("aria-busy", "true")
            expect(default_row.locator(".loading-indicator")).to_be_hidden()
            expect(default).to_be_enabled()
            assert route.request.post_data_json == {
                "playlist_name": "Night",
                "plugin_id": "clock",
                "plugin_instance": "Clock A",
            }

            with page.expect_navigation():
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"success": true, "message": "Display updated"}',
                )
            expect(page.locator(".toast.success .toast-content")).to_have_text(
                "Success! Display updated"
            )
            expect(_row_of(_display_button(page, "Night"))).not_to_have_attribute(
                "aria-busy", "true"
            )
        finally:
            browser.close()


def test_playlist_display_now_failure_shows_the_error_and_frees_the_row(
    live_server: str, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed display stays on the page, says why, and lets you try again."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    _prepare_playlist(device_config_dev)

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            stub_leaflet(page)
            page.goto(
                f"{live_server}/playlist", wait_until="domcontentloaded", timeout=30000
            )
            page.wait_for_selector("[data-page-shell]", timeout=10000)
            page.evaluate("window.__sameDocument = true")

            button = _display_button(page, "Default")
            row = _row_of(button)
            route = _press_display_and_hold_request(page, button)
            expect(row).to_have_attribute("aria-busy", "true")
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"success": false, "error": "Clock render failed"}',
            )

            expect(page.locator(".toast.error .toast-content")).to_have_text(
                "Clock render failed"
            )
            expect(row).not_to_have_attribute("aria-busy", "true")
            expect(row.locator(".loading-indicator")).to_be_hidden()
            expect(button).to_be_enabled()
            expect(button).to_be_focused()
            assert page.evaluate("window.__sameDocument === true"), "page reloaded"
        finally:
            browser.close()
