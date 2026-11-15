# pyright: reportMissingImports=false
"""The settings Save button shows its spinner, and tells the truth afterwards.

Saving replaced the button's text, which deleted its spinner, so the spinner
never showed. After a save the button came back on although there was nothing
left to save. A failed save put every field back to its saved value, erasing
what the user had typed.
"""

from __future__ import annotations

import json
import os

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402

_SAVED = {"success": True, "message": "Settings saved."}


def _hold_saves(page: Page) -> list[Route]:
    """Keep each POST /save_settings waiting until the test answers it."""
    held: list[Route] = []

    def hold(route: Route) -> None:
        held.append(route)

    page.route("**/save_settings", hold)
    return held


def _wait_for_save(page: Page, held: list[Route], count: int) -> Route:
    for _ in range(100):
        if len(held) >= count:
            return held[count - 1]
        page.wait_for_timeout(50)
    raise AssertionError("the page never sent the save")


def _answer(route: Route, status: int, body: dict[str, object]) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def _type_name(page: Page, name: str) -> None:
    field = page.locator("#deviceName")
    field.scroll_into_view_if_needed()
    field.fill(name)


def test_save_shows_its_spinner_then_turns_off_once_saved(
    live_server: str, browser_page: Page
) -> None:
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")
    held = _hold_saves(page)
    save = page.locator("#saveSettingsBtn")
    spinner = page.locator("#saveSettingsBtn .btn-spinner")

    for attempt, name in enumerate(["Kitchen frame", "Hall frame"], start=1):
        _type_name(page, name)
        expect(save).to_be_enabled()
        save.click()
        route = _wait_for_save(page, held, attempt)

        # Every save, not just the first, shows the spinner.
        expect(spinner).to_be_visible()
        expect(save).to_have_text("Saving settings…")
        expect(save).to_be_disabled()

        _answer(route, 200, _SAVED)
        expect(save).to_have_text("Save settings")
        expect(spinner).to_be_hidden()
        expect(save).to_be_disabled()  # nothing left to save

    _type_name(page, "Hall frame 2")
    expect(save).to_be_enabled()


def test_failed_save_keeps_what_was_typed_and_save_stays_on(
    live_server: str, browser_page: Page
) -> None:
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")
    held = _hold_saves(page)
    save = page.locator("#saveSettingsBtn")

    _type_name(page, "Kitchen frame")
    save.click()
    _answer(
        _wait_for_save(page, held, 1),
        500,
        {"success": False, "error": "Could not write the settings file"},
    )

    expect(save).to_have_text("Save settings")
    expect(page.locator("#deviceName")).to_have_value("Kitchen frame")
    expect(save).to_be_enabled()  # the change is still unsaved
