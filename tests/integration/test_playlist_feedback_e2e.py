# pyright: reportMissingImports=false
"""Playlist buttons show that they are working, and their messages last.

Every playlist change reloads the page. The page used to toast the reply and
reload at once, so "Created new Playlist!" flashed and was gone, and Display
next showed two toasts with no sign of work while the panel was drawn. Each
button now says what it is doing until the reply comes, and the message is
shown on the reloaded page.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, Route, expect
from tests.integration.browser_helpers import navigate_and_wait, prepare_playlist

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


def _hold(page: Page, pattern: str, click: Locator) -> Route:
    """Click, and return the request it sends, not yet answered."""
    held: list[Route] = []
    page.route(pattern, lambda route: held.append(route))
    with page.expect_request(pattern):
        click.click()
    for _ in range(100):
        if held:
            return held[0]
        page.wait_for_timeout(20)
    raise AssertionError(f"no request reached {pattern}")


def _toasts(page: Page) -> Locator:
    return page.locator(".toast-container .toast")


def _open_display_next(page: Page) -> Locator:
    page.locator('[data-playlist-action="confirm-display-next"]').first.click()
    dialog = page.locator("#displayNextConfirmModal")
    expect(dialog).to_be_visible()
    return dialog


def test_create_shows_saving_then_keeps_the_message_across_the_reload(
    live_server: str, device_config_dev: Any, browser_page: Page
) -> None:
    prepare_playlist(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")

    page.locator("#newPlaylistBtn").click()
    page.locator("#playlist_name").fill("Mornings")
    save = page.locator("#saveButton")
    route = _hold(page, "**/create_playlist", save)

    expect(save).to_be_disabled()
    expect(save).to_contain_text("Saving playlist…")
    expect(page.locator("#scheduleForm")).to_have_attribute("aria-busy", "true")

    with page.expect_navigation():
        route.continue_()
    # 09:00-17:00 sits inside Default's all-day window, so the server adds a
    # warning; it shares the toast with the success message.
    toast = _toasts(page)
    expect(toast).to_have_count(1)
    expect(toast).to_have_class("toast warning show")
    expect(toast.locator(".toast-content")).to_have_text(
        "Created new Playlist! This playlist overlaps with Default. During its "
        "active hours, this playlist will take priority."
    )
    expect(page.locator('[data-playlist-name="Mornings"]').first).to_be_visible()


def test_a_refused_save_names_the_field_and_frees_the_button(
    live_server: str, device_config_dev: Any, browser_page: Page
) -> None:
    prepare_playlist(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")
    page.evaluate("window.__sameDocument = true")

    page.locator("#newPlaylistBtn").click()
    page.locator("#playlist_name").fill("Default")
    save = page.locator("#saveButton")
    route = _hold(page, "**/create_playlist", save)
    expect(save).to_be_disabled()
    route.fulfill(
        status=400,
        content_type="application/json",
        body=(
            '{"success": false, "error": "Playlist already exists",'
            ' "details": {"field": "playlist_name"}}'
        ),
    )

    expect(page.locator(".toast.error .toast-content")).to_have_text(
        "Failed to save playlist: Playlist already exists"
    )
    expect(page.locator("#playlist-name-error")).to_have_text("Playlist already exists")
    expect(page.locator("#playlist_name")).to_have_attribute("aria-invalid", "true")
    expect(save).to_be_enabled()
    expect(save).to_have_text("Save playlist")
    expect(page.locator("#playlistModal")).to_be_visible()
    assert page.evaluate("window.__sameDocument === true"), "page reloaded"


def test_display_next_shows_displaying_then_one_toast_after_the_reload(
    live_server: str, device_config_dev: Any, browser_page: Page
) -> None:
    prepare_playlist(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")

    dialog = _open_display_next(page)
    confirm = dialog.locator("#confirmDisplayNextBtn")
    route = _hold(page, "**/display_next_in_playlist", confirm)

    # The dialog stays up while the panel is drawn, and says so.
    expect(dialog).to_be_visible()
    expect(confirm).to_have_text("Displaying…")
    expect(confirm).to_be_disabled()
    expect(confirm).to_have_attribute("aria-busy", "true")
    expect(dialog.locator("#cancelDisplayNextBtn")).to_be_disabled()
    assert route.request.post_data_json == {"playlist_name": "Default"}

    with page.expect_navigation():
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success": true, "message": "Displayed next instance"}',
        )
    toast = _toasts(page)
    expect(toast).to_have_count(1)
    expect(toast).to_have_class("toast success show")
    expect(toast.locator(".toast-content")).to_have_text("Displayed next instance")


def test_display_next_failure_says_why_and_lets_you_retry(
    live_server: str, device_config_dev: Any, browser_page: Page
) -> None:
    prepare_playlist(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")
    page.evaluate("window.__sameDocument = true")

    dialog = _open_display_next(page)
    confirm = dialog.locator("#confirmDisplayNextBtn")
    route = _hold(page, "**/display_next_in_playlist", confirm)
    expect(confirm).to_be_disabled()
    route.fulfill(
        status=500,
        content_type="application/json",
        body='{"success": false, "error": "Clock render failed"}',
    )

    expect(page.locator(".toast.error .toast-content")).to_have_text(
        "Failed to display next: Clock render failed"
    )
    expect(dialog).to_be_visible()
    expect(confirm).to_be_enabled()
    expect(confirm).to_have_text("Display next")
    expect(confirm).to_have_attribute("aria-busy", "false")
    expect(dialog.locator("#cancelDisplayNextBtn")).to_be_enabled()
    assert page.evaluate("window.__sameDocument === true"), "page reloaded"


def test_delete_instance_shows_deleting_then_keeps_the_message(
    live_server: str, device_config_dev: Any, browser_page: Page
) -> None:
    prepare_playlist(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")

    page.locator(".delete-instance-btn").first.click()
    dialog = page.locator("#deleteInstanceModal")
    expect(dialog).to_be_visible()
    confirm = dialog.locator("#confirmDeleteInstanceBtn")
    route = _hold(page, "**/delete_plugin_instance", confirm)

    expect(confirm).to_have_text("Deleting…")
    expect(confirm).to_be_disabled()
    expect(dialog.locator("#cancelDeleteInstanceBtn")).to_be_disabled()

    with page.expect_navigation():
        route.continue_()
    toast = _toasts(page)
    expect(toast).to_have_count(1)
    expect(toast).to_have_class("toast success show")
    expect(toast.locator(".toast-content")).to_have_text("Deleted plugin instance.")
    expect(page.locator('.plugin-item[data-instance-name="Clock A"]')).to_have_count(0)


def test_delete_playlist_failure_says_why(
    live_server: str, device_config_dev: Any, browser_page: Page
) -> None:
    """The server refuses to delete Default, and the toast gives its reason."""
    prepare_playlist(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")
    page.evaluate("window.__sameDocument = true")

    page.locator('.delete-playlist-btn[data-playlist="Default"]').click()
    dialog = page.locator("#deletePlaylistModal")
    expect(dialog).to_be_visible()
    confirm = dialog.locator("#confirmDeletePlaylistBtn")
    with page.expect_response("**/delete_playlist/Default"):
        confirm.click()

    expect(page.locator(".toast.error .toast-content")).to_have_text(
        "Failed to delete playlist: Cannot delete the default playlist"
    )
    expect(confirm).to_be_enabled()
    expect(confirm).to_have_text("Delete")
    assert page.evaluate("window.__sameDocument === true"), "page reloaded"
