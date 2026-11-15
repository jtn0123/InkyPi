# pyright: reportMissingImports=false
from __future__ import annotations

import os
import re
from typing import Any

import pytest
from playwright.sync_api import Page, expect
from tests.integration.browser_helpers import navigate_and_wait, prepare_playlist

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

# The chevron rotates over a 0.2 s CSS transition, so its computed transform
# passes through in-between matrices before it reaches the end state.
_ICON_UNROTATED = re.compile(r"^(none|matrix\(1, 0, 0, 1, 0, 0\))$")
_ICON_ROTATED_180 = "matrix(-1, 0, 0, -1, 0, 0)"


def test_playlist_card_toggle(
    live_server: str, device_config_dev: Any, mobile_page: Page
) -> None:
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
        expect(body, "Body should be hidden after collapsing").to_be_hidden()

    # Expand
    toggle.click()
    expect(body, "Playlist card body should be visible after expand").to_be_visible()

    # Collapse
    toggle.click()
    expect(body, "Playlist card body should be hidden after collapse").to_be_hidden()


def test_settings_tabs_switch(live_server: str, browser_page: Page) -> None:
    """Each settings section button shows its own panel and hides the others.

    This used to look for ``[data-tab], .tab-button, .settings-tab``, none of
    which the page has, so it fell through to checking that the Save button
    was visible and never clicked a tab at all.
    """
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")

    buttons = page.locator("[data-settings-tab]")
    names = [
        buttons.nth(i).get_attribute("data-settings-tab") or ""
        for i in range(buttons.count())
    ]
    assert len(names) > 1, f"expected several settings sections, found {names}"
    panels = page.locator("[data-settings-panel]")
    assert sorted(
        panels.nth(i).get_attribute("data-settings-panel") or ""
        for i in range(panels.count())
    ) == sorted(names), "every section button needs exactly one panel"

    # Walk backwards so the first click moves away from the default section.
    for name in reversed(names):
        page.locator(f'[data-settings-tab="{name}"]').click()

        expect(page.locator(f'[data-settings-tab="{name}"]')).to_have_class(
            re.compile(r"\bactive\b")
        )
        expect(page.locator("[data-settings-tab].active")).to_have_count(1)
        panel = page.locator(f'[data-settings-panel="{name}"]')
        expect(panel).to_be_visible()
        expect(panel).to_have_attribute("aria-hidden", "false")
        for other in names:
            if other != name:
                expect(page.locator(f'[data-settings-panel="{other}"]')).to_be_hidden()


def test_plugin_style_accordion_chevron_flips(
    live_server: str, browser_page: Page
) -> None:
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
    page.wait_for_selector('[data-settings-panel="maintenance"].active', timeout=5000)

    # Guard loudly if Diagnostics is ever flattened too: without this assert,
    # `.first` on an empty locator would silently time out inside `.click()`
    # and the contract regression would be obscured by a generic timeout.
    headers = page.locator("button.collapsible-header[data-collapsible-toggle]")
    assert headers.count() >= 1, (
        "Expected at least one collapsible header on the settings page; "
        "if Diagnostics was flattened, move this contract test to whichever "
        "collapsible survives."
    )
    header = headers.first
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
    expect(header).to_have_attribute("aria-expanded", "true")
    expect(icon).to_have_css("transform", _ICON_ROTATED_180)
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
    expect(header).to_have_attribute("aria-expanded", "false")
    expect(icon).to_have_css("transform", _ICON_UNROTATED)
    assert header.get_attribute("aria-expanded") == "false"
    transform_collapsed_again = icon.evaluate("el => getComputedStyle(el).transform")
    assert transform_collapsed_again in ("none", "matrix(1, 0, 0, 1, 0, 0)")


def test_playlist_details_expand(
    live_server: str, device_config_dev: Any, browser_page: Page
) -> None:
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
    live_server: str, device_config_dev: Any, browser_page: Page
) -> None:
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

    before_expanded = toggle.get_attribute("aria-expanded")
    before_visible = body.is_visible()
    assert before_expanded is not None, "setup should have set aria-expanded"

    toggle.click()
    # The handler flips aria-expanded and the body's visibility together.
    expect(toggle).not_to_have_attribute("aria-expanded", before_expanded)

    after_expanded = toggle.get_attribute("aria-expanded")
    after_visible = body.is_visible()

    assert (
        before_expanded != after_expanded
    ), "Toggle must reflect changed expanded state"
    assert (
        before_visible != after_visible
    ), "Toggle click must change playlist body visibility"
