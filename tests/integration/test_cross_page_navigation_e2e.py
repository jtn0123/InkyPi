# pyright: reportMissingImports=false
from __future__ import annotations

import os
from typing import Any, cast

import pytest
from playwright.sync_api import Page, expect
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
def test_all_pages_load_without_js_errors(
    live_server: str, browser_page: Page, path: Any, label: Any
) -> None:
    page = browser_page
    rc = navigate_and_wait(page, live_server, path)
    page.wait_for_timeout(1000)
    rc.assert_no_errors(name=f"page_load_{label}")


@pytest.mark.parametrize(
    "page_fixture", ["browser_page", "mobile_page"], ids=["desktop", "mobile"]
)
def test_nav_links_work(
    live_server: str, page_fixture: str, request: pytest.FixtureRequest
) -> None:
    page = cast(Page, request.getfixturevalue(page_fixture))
    for path in ("/settings", "/playlist", "/history"):
        collector = navigate_and_wait(page, live_server, "/")
        if page_fixture == "mobile_page":
            menu = page.locator(".mobile-site-nav-summary")
            expect(menu).to_be_visible()
            menu.click()
        # Both desktop and mobile links exist in the DOM. Click the navigation
        # visible to this viewport, as a user would, rather than the hidden first.
        navigation = page.get_by_role(
            "navigation",
            name=(
                "Mobile site navigation"
                if page_fixture == "mobile_page"
                else "Site navigation"
            ),
            exact=True,
        )
        link = navigation.locator(f"a[href='{path}']:visible")
        expect(link).to_have_count(1)
        link.click()
        page.wait_for_selector("[data-page-shell]", timeout=10000)
        expect(page).to_have_url(f"{live_server}{path}")
        collector.assert_no_errors(name=f"{page_fixture}_navigation_{path}")


def test_browser_back_forward(live_server: str, browser_page: Page) -> None:
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


def test_plugin_page_loads_without_errors(live_server: str, browser_page: Page) -> None:
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/plugin/clock")
    page.wait_for_timeout(1000)
    rc.assert_no_errors(name="plugin_page_clock")
