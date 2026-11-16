# pyright: reportMissingImports=false
"""A reply that isn't JSON is reported in plain words, not as a SyntaxError.

Each page called ``resp.json()`` itself, often before looking at the status,
so a proxy's 502 page or a login page in place of the JSON answer surfaced as
"Unexpected token '<' ... is not valid JSON". The pages now share one
``fetchJson`` helper that checks the status and turns any such reply into a
sentence. These tests also pin the page scripts' globals: their private
constants no longer leak into the shared global scope.
"""

from __future__ import annotations

import os
import re
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import (  # noqa: E402
    navigate_and_wait,
    prepare_playlist,
)

_BAD_GATEWAY_PAGE = "<html><body><h1>502 Bad Gateway</h1></body></html>"
_SERVER_ERROR_PAGE = "<!doctype html><title>500</title><p>Internal Server Error</p>"
_LOGIN_PAGE = "<!doctype html><title>Sign in</title><form>Password</form>"

# What a raw JSON parse failure looks like in Chromium.
_PARSE_ERROR = re.compile(r"SyntaxError|Unexpected token|not valid JSON")


def _answer_with_html(status: int, body: str) -> Any:
    def answer(route: Route) -> None:
        route.fulfill(status=status, content_type="text/html", body=body)

    return answer


def test_schedule_save_reports_a_502_page_in_plain_words(
    live_server: str, browser_page: Page, device_config_dev: Any
) -> None:
    prepare_playlist(device_config_dev)
    page = browser_page
    page.route(
        "**/update_plugin_instance/**", _answer_with_html(502, _BAD_GATEWAY_PAGE)
    )
    navigate_and_wait(page, live_server, "/playlist")

    page.locator('[data-playlist-action="edit-refresh"] >> nth=0').click()
    expect(page.locator("#refreshSettingsModal")).to_be_visible()
    page.locator("#saveRefreshSettingsBtn").click()

    toast = page.locator(".toast.error .toast-content")
    expect(toast).to_contain_text("Service temporarily unavailable")
    expect(toast).not_to_have_text(_PARSE_ERROR)


def test_health_panel_reports_a_500_page_in_plain_words(
    live_server: str, browser_page: Page
) -> None:
    page = browser_page
    page.route("**/api/health/system", _answer_with_html(500, _SERVER_ERROR_PAGE))
    navigate_and_wait(page, live_server, "/settings")

    panel = page.locator("#healthSummary")
    expect(panel).to_contain_text("Failed to load health data: Server error")
    expect(panel).not_to_have_text(_PARSE_ERROR)


def test_one_failed_benchmark_reply_leaves_the_other_panels_drawn(
    live_server: str, browser_page: Page
) -> None:
    page = browser_page
    page.route("**/api/benchmarks/plugins?*", _answer_with_html(502, _BAD_GATEWAY_PAGE))
    navigate_and_wait(page, live_server, "/settings")

    plugins = page.locator("#benchPlugins")
    expect(plugins).to_contain_text(
        "Failed to load plugin timing: Service temporarily unavailable"
    )
    expect(plugins).not_to_have_text(_PARSE_ERROR)
    # The panels that did load are drawn in the same pass, not left loading.
    expect(page.locator("#benchSummary")).to_contain_text("Timing Summary")
    expect(page.locator("#benchRefreshes")).not_to_have_text(
        re.compile("loading|Failed", re.IGNORECASE)
    )


def test_a_login_page_instead_of_json_asks_for_a_reload(
    live_server: str, browser_page: Page, device_config_dev: Any
) -> None:
    """A 200 HTML page (a sign-in redirect, say) is not a success."""
    prepare_playlist(device_config_dev)
    page = browser_page
    page.route("**/display_plugin_instance", _answer_with_html(200, _LOGIN_PAGE))
    navigate_and_wait(page, live_server, "/playlist")

    page.locator('[data-playlist-action="display-instance"] >> nth=0').click()

    toast = page.locator(".toast.error .toast-content")
    expect(toast).to_contain_text("Reload the page")
    expect(toast).not_to_have_text(_PARSE_ERROR)


# Names the shared scripts used to declare at the top level. A top-level
# const, let or class in a classic script lands in the one global scope every
# page script shares, so a second script declaring the same name fails to
# load at all.
_PRIVATE_NAMES = (
    "TOAST_DURATION_MS",
    "TOAST_ERROR_DURATION_MS",
    "TOAST_FADE_MS",
    "MAX_VISIBLE_TOASTS",
    "toastContainer",
    "toastCounter",
    "ensureToastContainer",
    "dismissStaleErrors",
    "closeToast",
    "getErrorMessage",
    "RefreshSettingsManager",
)
# Names other scripts and templates call, which stay global.
_PUBLIC_FUNCTIONS = (
    "showToast",
    "showResponseModal",
    "showError",
    "handleJsonResponse",
    "fetchJson",
    "createRefreshSettingsManager",
)


def test_shared_scripts_keep_their_private_names_out_of_the_global_scope(
    live_server: str, browser_page: Page, device_config_dev: Any
) -> None:
    prepare_playlist(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")

    # A string expression is evaluated in the page's global scope, so it sees
    # top-level let/const/class bindings that globalThis does not list.
    leaked = [
        name
        for name in _PRIVATE_NAMES
        if page.evaluate(f"typeof {name}") != "undefined"
    ]
    assert leaked == []
    missing = [
        name
        for name in _PUBLIC_FUNCTIONS
        if page.evaluate(f"typeof globalThis.{name}") != "function"
    ]
    assert missing == []
