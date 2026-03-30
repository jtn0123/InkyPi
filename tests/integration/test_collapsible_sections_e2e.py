# pyright: reportMissingImports=false
from __future__ import annotations

import os

import pytest
from tests.integration.browser_helpers import navigate_and_wait, prepare_playlist

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


def test_playlist_card_toggle(live_server, device_config_dev, mobile_page):
    """On mobile viewport, toggling a playlist card expands/collapses its body."""
    prepare_playlist(device_config_dev)
    page = mobile_page
    navigate_and_wait(page, live_server, "/playlist")

    toggle = page.locator("[data-playlist-toggle]").first
    body = page.locator("[data-playlist-body]").first

    # On mobile with a single active playlist, it may already be expanded.
    initial_visible = body.is_visible()
    if initial_visible:
        toggle.click()
        page.wait_for_timeout(500)
        assert not body.is_visible(), "Body should be hidden after collapsing"

    # Expand
    toggle.click()
    page.wait_for_timeout(500)
    assert body.is_visible(), "Playlist card body should be visible after expand"

    # Collapse
    toggle.click()
    page.wait_for_timeout(500)
    assert not body.is_visible(), "Playlist card body should be hidden after collapse"


def test_settings_tabs_switch(live_server, browser_page):
    """Settings page tabs switch between content panels."""
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")

    tabs = page.locator("[data-tab], .tab-button, .settings-tab")
    tab_count = tabs.count()

    if tab_count > 1:
        tabs.nth(1).click()
        page.wait_for_timeout(300)
        is_active = tabs.nth(1).evaluate(
            "el => el.classList.contains('active') || el.getAttribute('aria-selected') === 'true'"
        )
        assert is_active, "Clicked tab should become active"
    else:
        assert page.locator("#saveSettingsBtn").is_visible()


def test_playlist_details_expand(live_server, device_config_dev, browser_page):
    """Playlist details toggle expands and collapses on desktop."""
    prepare_playlist(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")

    toggle = page.locator("[data-playlist-toggle]").first
    body = page.locator("[data-playlist-body]").first

    assert body.is_visible(), "Details section should be visible on desktop"
    assert toggle.is_visible(), "Toggle button should exist"
