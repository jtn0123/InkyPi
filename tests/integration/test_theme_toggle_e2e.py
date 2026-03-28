# pyright: reportMissingImports=false
from __future__ import annotations

import os

import pytest

from tests.integration.browser_helpers import navigate_and_wait

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


def test_theme_toggle_changes_attribute(live_server, browser_page):
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/")

    initial_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    page.locator("#themeToggle").click()
    page.wait_for_timeout(500)

    new_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert new_theme != initial_theme
    assert new_theme in ("light", "dark")

    rc.assert_no_errors("screenshots", "theme_toggle_changes_attribute")


def test_theme_persists_in_localstorage(live_server, browser_page):
    page = browser_page
    navigate_and_wait(page, live_server, "/")

    initial_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    page.locator("#themeToggle").click()
    page.wait_for_timeout(500)

    expected = "dark" if initial_theme == "light" else "light"

    stored_theme = page.evaluate("localStorage.getItem('theme')")
    stored_inkypi = page.evaluate("localStorage.getItem('inkypi-theme')")

    assert stored_theme == expected, f"localStorage 'theme' expected {expected}, got {stored_theme}"
    assert stored_inkypi == expected, f"localStorage 'inkypi-theme' expected {expected}, got {stored_inkypi}"


def test_theme_persists_across_navigation(live_server, browser_page):
    page = browser_page
    navigate_and_wait(page, live_server, "/")

    current = page.evaluate("document.documentElement.getAttribute('data-theme')")
    if current != "dark":
        page.locator("#themeToggle").click()
        page.wait_for_timeout(500)

    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"

    navigate_and_wait(page, live_server, "/settings")

    theme_after = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert theme_after == "dark", f"Expected 'dark' after navigation, got '{theme_after}'"


def test_theme_persists_after_reload(live_server, browser_page):
    page = browser_page
    navigate_and_wait(page, live_server, "/")

    current = page.evaluate("document.documentElement.getAttribute('data-theme')")
    if current != "dark":
        page.locator("#themeToggle").click()
        page.wait_for_timeout(500)

    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"

    page.reload()
    page.wait_for_load_state("networkidle")

    theme_after = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert theme_after == "dark", f"Expected 'dark' after reload, got '{theme_after}'"
