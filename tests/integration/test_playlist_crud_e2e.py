# pyright: reportMissingImports=false
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import (  # noqa: E402
    navigate_and_wait,
    prepare_playlist,
)


def test_create_playlist_via_form(
    live_server, device_config_dev, browser_page, tmp_path
):
    prepare_playlist(device_config_dev)
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/playlist")

    # Stub reload so the page stays testable after form submit
    page.evaluate("""() => {
        const origFetch = window.fetch;
        window.__fetchCalls = [];
        window.fetch = function(...args) {
            window.__fetchCalls.push({url: args[0], options: args[1]});
            return origFetch.apply(this, args);
        };
        window.location.reload = function() {};
    }""")

    # Click New Playlist button
    new_btn = page.locator("#newPlaylistBtn")
    new_btn.wait_for(state="visible", timeout=5000)
    new_btn.click()
    page.wait_for_timeout(500)

    # Fill playlist form fields
    name_input = page.locator("#playlist_name")
    name_input.wait_for(state="visible", timeout=3000)
    name_input.fill("Test Playlist")

    # Save
    save_btn = page.locator("#saveButton")
    save_btn.click()
    page.wait_for_timeout(500)

    rc.assert_no_errors(str(tmp_path), "create_playlist")


def test_edit_playlist_opens_modal(
    live_server, device_config_dev, browser_page, tmp_path
):
    prepare_playlist(device_config_dev)
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/playlist")

    # Click edit button on a playlist
    edit_btn = page.locator(".edit-playlist-btn").first
    edit_btn.wait_for(state="visible", timeout=5000)
    edit_btn.click()
    page.wait_for_timeout(500)

    # Verify modal is visible
    modal = page.locator("#playlistModal")
    modal.wait_for(state="visible", timeout=3000)
    assert modal.is_visible(), "Edit playlist modal should be visible"

    rc.assert_no_errors(str(tmp_path), "edit_playlist_modal")


def test_edit_playlist_opens_modal_mobile(
    live_server, device_config_dev, mobile_page, tmp_path
):
    prepare_playlist(device_config_dev)
    page = mobile_page
    rc = navigate_and_wait(page, live_server, "/playlist")

    edit_btn = page.locator(".edit-playlist-btn").first
    edit_btn.wait_for(state="visible", timeout=5000)
    edit_btn.click()
    page.wait_for_timeout(500)

    modal = page.locator("#playlistModal")
    modal.wait_for(state="visible", timeout=3000)
    assert modal.is_visible(), "Edit playlist modal should be visible on mobile"

    rc.assert_no_errors(str(tmp_path), "edit_playlist_modal_mobile")


def test_delete_playlist_modal(live_server, device_config_dev, browser_page, tmp_path):
    prepare_playlist(device_config_dev)
    # JTN-781: the server refuses to delete the canonical "Default" playlist,
    # so seed a second, deletable playlist to exercise the modal flow. Without
    # this, the DELETE request returns 400 and surfaces a console error that
    # fails `rc.assert_no_errors`.
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Deletable"):
        pm.add_playlist("Deletable", "00:00", "24:00")
    device_config_dev.write_config()

    page = browser_page
    rc = navigate_and_wait(page, live_server, "/playlist")

    # Stub fetch and reload AFTER navigation so JS context is live
    page.evaluate("""() => {
        const origFetch = window.fetch;
        window.__deleteCalls = [];
        window.fetch = function(...args) {
            const opts = args[1] || {};
            if (opts.method === 'DELETE') {
                window.__deleteCalls.push({url: args[0], options: opts});
            }
            return origFetch.apply(this, args);
        };
        window.location.reload = function() {};
    }""")

    # Target the non-Default playlist card so the DELETE is actually permitted.
    delete_btn = page.locator('[data-playlist-name="Deletable"] .delete-playlist-btn')
    delete_btn.wait_for(state="visible", timeout=5000)
    delete_btn.click()
    page.wait_for_timeout(500)

    # Verify delete modal is visible
    modal = page.locator("#deletePlaylistModal")
    modal.wait_for(state="visible", timeout=3000)
    assert modal.is_visible(), "Delete playlist modal should be visible"

    # Click confirm delete
    confirm_btn = modal.locator("#confirmDeletePlaylistBtn")
    confirm_btn.click()
    page.wait_for_timeout(500)

    rc.assert_no_errors(str(tmp_path), "delete_playlist_modal")


def test_delete_instance_modal(live_server, device_config_dev, browser_page, tmp_path):
    prepare_playlist(device_config_dev)
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/playlist")

    page.evaluate("() => { window.location.reload = function() {}; }")

    # Click delete button on a plugin instance
    delete_btn = page.locator(".delete-instance-btn").first
    delete_btn.wait_for(state="visible", timeout=5000)
    delete_btn.click()
    page.wait_for_timeout(500)

    # Verify delete instance modal is visible
    modal = page.locator("#deleteInstanceModal")
    modal.wait_for(state="visible", timeout=3000)
    assert modal.is_visible(), "Delete instance modal should be visible"

    # Click confirm delete
    confirm_btn = modal.locator("#confirmDeleteInstanceBtn")
    confirm_btn.click()
    page.wait_for_timeout(500)

    rc.assert_no_errors(str(tmp_path), "delete_instance_modal")
