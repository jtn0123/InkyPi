# pyright: reportMissingImports=false
from __future__ import annotations

import os

import pytest

from tests.integration.browser_helpers import navigate_and_wait

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


def test_response_modal_close_button(live_server, browser_page):
    """Show response modal in legacy mode, close via button."""
    page = browser_page
    navigate_and_wait(page, live_server, "/")

    # Use legacy mode (useToast=false) so the actual modal element shows
    page.evaluate("showResponseModal('success', 'Test message', false)")
    modal = page.locator("#responseModal")
    modal.wait_for(state="visible", timeout=3000)
    assert modal.is_visible()

    page.locator("#responseModalClose").click()
    modal.wait_for(state="hidden", timeout=3000)
    assert not modal.is_visible()


def test_response_toast_appears(live_server, browser_page):
    """Show response via default toast mode, verify toast appears."""
    page = browser_page
    navigate_and_wait(page, live_server, "/")

    page.evaluate("showResponseModal('success', 'Toast test')")
    toast = page.locator(".toast-container .toast")
    toast.first.wait_for(state="visible", timeout=3000)
    assert toast.first.is_visible()


def test_response_modal_close_button_is_button(live_server, browser_page):
    """Response modal close button is a <button> element for a11y."""
    page = browser_page
    navigate_and_wait(page, live_server, "/")

    close_btn = page.locator("#responseModalClose")
    tag = close_btn.evaluate("el => el.tagName.toLowerCase()")
    assert tag == "button", f"Close button should be <button>, got <{tag}>"


def test_playlist_create_modal_lifecycle(live_server, browser_page):
    """Open playlist create modal, verify visible, close via button."""
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")

    page.locator("#newPlaylistBtn").click()
    modal = page.locator("#playlistModal")
    modal.wait_for(state="visible", timeout=3000)
    assert modal.is_visible()

    page.locator("#closePlaylistModalBtn").click()
    modal.wait_for(state="hidden", timeout=3000)
    assert not modal.is_visible()


def test_playlist_modal_backdrop_close(live_server, browser_page):
    """Open playlist modal, close via backdrop click."""
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")

    page.locator("#newPlaylistBtn").click()
    modal = page.locator("#playlistModal")
    modal.wait_for(state="visible", timeout=3000)

    # Click the backdrop area of the modal (top-left corner)
    modal.click(position={"x": 5, "y": 5})
    modal.wait_for(state="hidden", timeout=3000)
    assert not modal.is_visible()
