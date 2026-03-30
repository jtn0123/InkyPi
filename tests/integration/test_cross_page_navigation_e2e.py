# pyright: reportMissingImports=false
from __future__ import annotations

import os

import pytest
from tests.integration.browser_helpers import navigate_and_wait

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


@pytest.mark.parametrize(
    "path,label",
    [
        ("/", "home"),
        ("/settings", "settings"),
        ("/history", "history"),
        ("/playlist", "playlist"),
        ("/api-keys", "api_keys"),
    ],
)
def test_all_pages_load_without_js_errors(live_server, browser_page, path, label):
    page = browser_page
    rc = navigate_and_wait(page, live_server, path)
    page.wait_for_timeout(1000)
    rc.assert_no_errors(name=f"page_load_{label}")


def test_nav_links_work(live_server, browser_page):
    page = browser_page
    navigate_and_wait(page, live_server, "/")

    # Navigate to settings
    settings_link = page.locator("a[href='/settings']").first
    settings_link.click()
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    assert "/settings" in page.url

    # Go back to dashboard to find playlist link
    navigate_and_wait(page, live_server, "/")
    playlist_link = page.locator("a[href='/playlist']").first
    playlist_link.click()
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    assert "/playlist" in page.url

    # Go back to dashboard to find history link
    navigate_and_wait(page, live_server, "/")
    history_link = page.locator("a[href='/history']").first
    history_link.click()
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    assert "/history" in page.url


def test_browser_back_forward(live_server, browser_page):
    page = browser_page
    base_url = live_server
    navigate_and_wait(page, base_url, "/")
    navigate_and_wait(page, base_url, "/settings")

    page.go_back()
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    assert page.url.rstrip("/") == base_url.rstrip("/") or page.url.endswith("/")

    page.go_forward()
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    assert "/settings" in page.url


def test_plugin_page_loads_without_errors(live_server, browser_page):
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/plugin/clock")
    page.wait_for_timeout(1000)
    rc.assert_no_errors(name="plugin_page_clock")
