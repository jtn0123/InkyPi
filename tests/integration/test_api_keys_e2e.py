# pyright: reportMissingImports=false
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402


def test_api_keys_page_loads(live_server, browser_page):
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/api-keys")

    save_btn = page.locator("#saveApiKeysBtn")
    save_btn.wait_for(state="visible", timeout=5000)
    assert save_btn.is_visible(), "Save API keys button should be visible"

    rc.assert_no_errors(name="api_keys_loads")


def test_api_key_input_and_save(live_server, browser_page):
    page = browser_page
    navigate_and_wait(page, live_server, "/api-keys")

    # Prevent page reload after save
    page.evaluate("window.location.reload = () => {};")

    # Fill the OpenAI key input
    key_input = page.locator("#openai-input")
    key_input.wait_for(state="attached", timeout=5000)
    key_input.fill("test-api-key-12345")

    # Track save requests
    save_responses = []
    page.on(
        "response",
        lambda resp: (
            save_responses.append(resp.status)
            if "/save_api_keys" in resp.url or "/api-keys" in resp.url
            else None
        ),
    )

    save_btn = page.locator("#saveApiKeysBtn")
    save_btn.click()
    page.wait_for_timeout(2000)

    assert len(save_responses) > 0, "Save should fire a request"


def test_api_key_close_buttons_are_buttons(live_server, browser_page):
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/api-keys")

    close_btns = page.locator("[aria-label='Close'], .close-button")
    count = close_btns.count()
    for i in range(count):
        tag = close_btns.nth(i).evaluate("el => el.tagName.toLowerCase()")
        assert (
            tag == "button"
        ), f"Close button at index {i} should be a <button>, got <{tag}>"

    rc.assert_no_errors(name="api_key_close_buttons")


def test_api_key_managed_fields_exist(live_server, browser_page):
    """The managed API keys page at /settings/api-keys has provider input fields."""
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/settings/api-keys")

    managed_inputs = page.locator(
        "#openai-input, #openweather-input, #nasa-input, #unsplash-input"
    )
    assert (
        managed_inputs.count() >= 1
    ), "Managed API keys page should have provider input fields"

    rc.assert_no_errors(name="api_key_managed_fields")
