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


def test_plugin_style_accordion_chevron_flips(live_server, browser_page):
    """JTN-643: The collapsible accordion chevron must visually flip between the
    collapsed (▼) and expanded (▲) states.

    The CSS contract is driven by `aria-expanded`: when the header has
    `aria-expanded="true"`, `_toggle.css` applies `transform: rotate(180deg)`
    to `.collapsible-icon`. This test exercises the real browser so a future
    regression (e.g. removing the CSS rule, swapping the chevron to a display
    mode transforms can't apply to, or forgetting to toggle aria-expanded)
    is caught end-to-end.

    Note: this test originally targeted the Style accordion on plugin pages,
    but that UX was refactored into a tab bar. The collapsible CSS contract
    is still exercised on the Settings page — the Diagnostics section on the
    Updates ("maintenance") tab is the last remaining collapsible after the
    handoff-driven Card refactor flattened the other settings sections. The
    contract is shared CSS, so testing it there preserves the regression
    signal.
    """
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")

    # Diagnostics lives on the Updates/maintenance tab; switch to it so the
    # collapsible header is in the rendered, interactable panel.
    page.click('[data-settings-tab="maintenance"]')
    page.wait_for_selector(
        '[data-settings-panel="maintenance"].active', timeout=5000
    )

    header = page.locator("button.collapsible-header[data-collapsible-toggle]").first
    icon = header.locator(".collapsible-icon")

    # Collapsed baseline: aria-expanded=false, no rotation applied.
    assert header.get_attribute("aria-expanded") == "false"
    transform_collapsed = icon.evaluate("el => getComputedStyle(el).transform")
    assert transform_collapsed in (
        "none",
        "matrix(1, 0, 0, 1, 0, 0)",
    ), f"Collapsed icon should not be rotated; got {transform_collapsed!r}"

    # Expand and verify the 180deg rotation is applied.
    header.click()
    page.wait_for_timeout(300)
    assert header.get_attribute("aria-expanded") == "true"
    transform_expanded = icon.evaluate("el => getComputedStyle(el).transform")
    # A 180deg rotation serialises as matrix(-1, 0, 0, -1, 0, 0).
    assert (
        transform_expanded == "matrix(-1, 0, 0, -1, 0, 0)"
    ), f"Expanded icon should be rotated 180deg; got {transform_expanded!r}"
    # For transforms to take effect the element cannot be a plain inline box.
    assert icon.evaluate("el => getComputedStyle(el).display") != "inline"

    # Collapse again and confirm the rotation is cleared.
    header.click()
    page.wait_for_timeout(300)
    assert header.get_attribute("aria-expanded") == "false"
    transform_collapsed_again = icon.evaluate("el => getComputedStyle(el).transform")
    assert transform_collapsed_again in ("none", "matrix(1, 0, 0, 1, 0, 0)")


def test_playlist_details_expand(live_server, device_config_dev, browser_page):
    """Playlist details stay expanded on desktop; the mobile toggle may be hidden."""
    prepare_playlist(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")

    toggles = page.locator("[data-playlist-toggle]")
    toggle = toggles.first
    body = page.locator("[data-playlist-body]").first

    assert body.is_visible(), "Details section should be visible on desktop"
    assert toggles.count() == 1, "Toggle button should still be rendered for mobile"
    assert not toggle.is_visible(), "Desktop layout should hide the mobile-only toggle"


def test_playlist_toggle_is_not_noop_if_visible_on_desktop(
    live_server, device_config_dev, browser_page
):
    """JTN-692: if the mobile-only toggle becomes visible on desktop, it must still work."""
    prepare_playlist(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")

    toggle = page.locator("[data-playlist-toggle]").first
    body = page.locator("[data-playlist-body]").first

    # Simulate a CSS/regression case where the mobile-only toggle is visible.
    page.evaluate("""
        () => {
            const btn = document.querySelector('[data-playlist-toggle]');
            const body = document.querySelector('[data-playlist-body]');
            const card = document.querySelector('[data-playlist-card]');
            if (!btn) return;
            btn.style.display = 'inline-flex';
            btn.setAttribute('aria-expanded', 'true');
            if (body) {
                body.hidden = false;
            }
            if (card) {
                card.classList.add('mobile-expanded');
                card.classList.remove('mobile-collapsed');
            }
        }
        """)
    page.wait_for_timeout(200)

    before_expanded = toggle.get_attribute("aria-expanded")
    before_visible = body.is_visible()

    toggle.click()
    page.wait_for_timeout(300)

    after_expanded = toggle.get_attribute("aria-expanded")
    after_visible = body.is_visible()

    assert (
        before_expanded != after_expanded
    ), "Toggle must reflect changed expanded state"
    assert (
        before_visible != after_visible
    ), "Toggle click must change playlist body visibility"
