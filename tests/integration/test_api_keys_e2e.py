# pyright: reportMissingImports=false
from __future__ import annotations

import os

import pytest
from playwright.sync_api import Dialog, Page, Request

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import (  # noqa: E402
    is_response_to,
    navigate_and_wait,
)


def test_api_keys_page_loads(live_server: str, browser_page: Page) -> None:
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/api-keys")

    save_btn = page.locator("#saveApiKeysBtn")
    save_btn.wait_for(state="visible", timeout=5000)
    assert save_btn.is_visible(), "Save API keys button should be visible"

    rc.assert_no_errors(name="api_keys_loads")


def test_api_key_input_and_save(live_server: str, browser_page: Page) -> None:
    page = browser_page
    navigate_and_wait(page, live_server, "/api-keys")

    # Prevent page reload after save
    page.evaluate("window.location.reload = () => {};")

    page.locator("#addApiKeyBtn").click()
    new_row = page.locator(".apikey-row").last
    new_row.locator(".apikey-key").fill("OPEN_AI_SECRET")
    new_row.locator(".apikey-value").fill("test-api-key-12345")

    # Track save requests
    save_responses = []
    page.on(
        "response",
        lambda resp: (
            save_responses.append(resp.status) if "/api-keys/save" in resp.url else None
        ),
    )

    save_btn = page.locator("#saveApiKeysBtn")
    with page.expect_response(is_response_to("POST", "/api-keys/save")) as info:
        save_btn.click()
    assert info.value.ok, f"POST /api-keys/save returned {info.value.status}"

    assert len(save_responses) > 0, "Save should fire a request"


def test_api_key_close_buttons_are_buttons(
    live_server: str, browser_page: Page
) -> None:
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


def test_api_key_managed_fields_exist(live_server: str, browser_page: Page) -> None:
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


def _store_nasa_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put NASA_SECRET in the test .env. setenv makes teardown remove the copy
    that load_dotenv puts in os.environ."""
    env_file = os.path.join(os.environ["PROJECT_DIR"], ".env")
    with open(env_file, "w", encoding="utf-8") as fh:
        fh.write("NASA_SECRET=test-nasa-key\n")
    monkeypatch.setenv("NASA_SECRET", "test-nasa-key")


def _record_native_dialogs(page: Page) -> list[str]:
    """Dismiss and record any alert/confirm/prompt the page opens."""
    seen: list[str] = []

    def dismiss(dialog: Dialog) -> None:
        seen.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", dismiss)
    return seen


def test_removing_a_saved_key_row_asks_in_the_page_dialog(
    live_server: str, browser_page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Escape keeps the row and returns focus; Remove takes it out and arms Save."""
    from playwright.sync_api import expect

    _store_nasa_key(monkeypatch)
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/api-keys")
    native_dialogs = _record_native_dialogs(page)

    row = page.locator('.apikey-row:has(.apikey-key[value="NASA_SECRET"])')
    delete_btn = row.locator('[data-api-action="delete-row"]')
    modal = page.locator("#confirmApiKeyModal")

    delete_btn.click()
    expect(modal).to_be_visible()
    expect(page.locator("#confirmApiKeyText")).to_have_text(
        "Remove NASA_SECRET? It is deleted when you save."
    )
    expect(page.locator("#cancelApiKeyBtn")).to_be_focused()
    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
    expect(row).to_have_count(1)
    expect(delete_btn).to_be_focused()
    expect(page.locator("#saveApiKeysBtn")).to_be_disabled()

    delete_btn.click()
    page.locator("#confirmApiKeyBtn").click()
    expect(modal).to_be_hidden()
    expect(row).to_have_count(0)
    expect(page.locator("#saveApiKeysBtn")).to_be_enabled()
    assert native_dialogs == [], native_dialogs
    rc.assert_no_errors(name="api_key_remove_row_dialog")


def test_deleting_a_managed_key_asks_first_and_cancel_sends_nothing(
    live_server: str, browser_page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancel sends no request; Delete posts the key name and reports success."""
    from playwright.sync_api import expect

    _store_nasa_key(monkeypatch)
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/settings/api-keys")
    native_dialogs = _record_native_dialogs(page)
    deletes: list[str | None] = []

    def record_delete(request: Request) -> None:
        if request.url.endswith("/settings/delete_api_key"):
            deletes.append(request.post_data)

    page.on("request", record_delete)

    page.locator('[data-api-action="reveal-input"][data-input-id="nasa-input"]').click()
    delete_btn = page.locator(
        '[data-api-action="delete-key"][data-key-name="NASA_SECRET"]'
    )
    modal = page.locator("#confirmApiKeyModal")

    delete_btn.click()
    expect(modal).to_be_visible()
    expect(page.locator("#confirmApiKeyText")).to_have_text(
        "Delete the NASA_SECRET API key? This cannot be undone."
    )
    page.locator("#cancelApiKeyBtn").click()
    expect(modal).to_be_hidden()
    page.wait_for_timeout(200)
    assert deletes == [], "Cancel must not send the delete request"

    delete_btn.click()
    with page.expect_response(
        is_response_to("POST", "/settings/delete_api_key")
    ) as info:
        page.locator("#confirmApiKeyBtn").click()
    assert info.value.ok, f"delete returned {info.value.status}"
    assert len(deletes) == 1 and "NASA_SECRET" in (deletes[0] or "")
    expect(page.locator(".toast.success .toast-content")).to_have_text(
        "Success! Deleted NASA_SECRET."
    )
    assert native_dialogs == [], native_dialogs
    rc.assert_no_errors(name="api_key_delete_managed_dialog")
