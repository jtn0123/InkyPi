# pyright: reportMissingImports=false
"""Keyboard behaviour of every custom dialog, checked in a real browser.

Each dialog goes through the shared ``InkyPiModalFocus`` helper, so all of
them should behave the same way for a keyboard user:

* opening moves focus into the dialog;
* the page behind it is inert (no clicks, no focus);
* Tab and Shift+Tab wrap around inside the dialog instead of escaping;
* Escape closes it and focus goes back to whatever opened it.

These replace source-text assertions that only checked the scripts contained
the right words.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from playwright.sync_api import Page
from tests.integration.browser_helpers import navigate_and_wait, prepare_playlist

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

_FOCUS_INSIDE = "sel => { const m = document.querySelector(sel); return !!m && m.contains(document.activeElement); }"


def _focus_is_inside(page: Page, modal_selector: str) -> bool:
    return bool(page.evaluate(_FOCUS_INSIDE, modal_selector))


def _is_inert(page: Page, selector: str) -> bool:
    return bool(
        page.evaluate(
            "sel => !!document.querySelector(sel)?.closest('[inert]')", selector
        )
    )


def _assert_keyboard_contract(
    page: Page, modal_selector: str, trigger_selector: str
) -> None:
    """Check the shared contract once the dialog has been opened."""
    modal = page.locator(modal_selector)
    modal.wait_for(state="visible", timeout=5000)
    page.wait_for_function(_FOCUS_INSIDE, arg=modal_selector, timeout=3000)

    assert _is_inert(
        page, trigger_selector
    ), "the page behind an open dialog must be inert"

    stops = int(
        page.evaluate(
            """sel => Array.from(document.querySelector(sel).querySelectorAll(
                'button:not([disabled]), [href], input:not([disabled]), '
                + 'select:not([disabled]), textarea:not([disabled]), '
                + '[tabindex]:not([tabindex="-1"])'
            )).filter(n => n.getClientRects().length).length""",
            modal_selector,
        )
    )
    for _ in range(stops + 1):
        page.keyboard.press("Tab")
        assert _focus_is_inside(page, modal_selector), "Tab escaped the dialog"
    for _ in range(stops + 1):
        page.keyboard.press("Shift+Tab")
        assert _focus_is_inside(page, modal_selector), "Shift+Tab escaped the dialog"

    page.keyboard.press("Escape")
    modal.wait_for(state="hidden", timeout=3000)
    page.wait_for_function(
        "sel => document.activeElement === document.querySelector(sel)",
        arg=trigger_selector,
        timeout=3000,
    )
    assert not _is_inert(
        page, trigger_selector
    ), "the page must be interactive again after the dialog closes"


def _open_with_keyboard(page: Page, trigger_selector: str) -> None:
    page.locator(trigger_selector).focus()
    page.keyboard.press("Enter")


def test_errors_clear_dialog_keyboard(
    live_server: str, browser_page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    import blueprints.errors as errors_mod

    monkeypatch.setattr(
        errors_mod,
        "get_captured_reports",
        lambda: [{"level": "error", "message": "boom", "url": "/", "ts": ""}],
    )
    page = browser_page
    navigate_and_wait(page, live_server, "/errors")

    _open_with_keyboard(page, "#errorsClearBtn")
    _assert_keyboard_contract(page, "#clearErrorsModal", "#errorsClearBtn")


def test_weather_map_dialog_keyboard(live_server: str, browser_page: Page) -> None:
    page = browser_page
    navigate_and_wait(page, live_server, "/plugin/weather")
    page.wait_for_selector("#openMap", state="visible")

    _open_with_keyboard(page, "#openMap")
    _assert_keyboard_contract(page, "#mapModal", "#openMap")


def test_plugin_api_keys_leave_dialog_keyboard(
    live_server: str, browser_page: Page
) -> None:
    page = browser_page
    navigate_and_wait(page, live_server, "/plugin/weather")
    link = "[data-api-keys-link]"
    page.wait_for_selector(link, state="visible")
    # The guard only prompts when the settings form has unsaved edits.
    page.evaluate("""() => {
            const field = document.querySelector(
                '#settingsForm input[type="text"]:not([readonly]), #settingsForm select'
            );
            if (field.tagName === 'SELECT') {
                field.selectedIndex = (field.selectedIndex + 1) % field.options.length;
            } else {
                field.value = field.value + ' edited';
            }
            field.dispatchEvent(new Event('input', {bubbles: true}));
            field.dispatchEvent(new Event('change', {bubbles: true}));
        }""")

    _open_with_keyboard(page, link)
    _assert_keyboard_contract(page, "#apiKeysLeaveConfirmModal", link)
    assert page.url.endswith("/plugin/weather"), "Escape must not follow the link"


def test_lightbox_keyboard(live_server: str, browser_page: Page) -> None:
    page = browser_page
    navigate_and_wait(page, live_server, "/plugin/clock")
    page.wait_for_function("() => !!globalThis.Lightbox")
    # A stand-in opener outside the dialog, so focus has somewhere to return.
    trigger = "#lightboxTrigger"
    page.evaluate("""() => {
            const button = document.createElement('button');
            button.id = 'lightboxTrigger';
            button.type = 'button';
            button.textContent = 'Open preview';
            button.addEventListener('click', () => globalThis.Lightbox.open(
                'data:image/gif;base64,R0lGODlhAQABAAAAACw=', 'Preview'
            ));
            document.body.prepend(button);
        }""")
    _open_with_keyboard(page, trigger)
    _assert_keyboard_contract(page, "#imagePreviewModal", trigger)


@pytest.mark.parametrize(
    ("trigger", "modal"),
    [
        ("#newPlaylistBtn", "#playlistModal"),
        (".delete-instance-btn", "#deleteInstanceModal"),
        ('[data-playlist-action="edit-refresh"]', "#refreshSettingsModal"),
    ],
)
def test_playlist_dialogs_keyboard(
    live_server: str,
    browser_page: Page,
    device_config_dev: Any,
    trigger: str,
    modal: str,
) -> None:
    prepare_playlist(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")
    first_trigger = f"{trigger} >> nth=0"
    page.locator(first_trigger).wait_for(state="visible")
    # Tag the trigger so the contract check can find it with a plain selector.
    page.locator(first_trigger).evaluate(
        "node => node.setAttribute('data-test-trigger', '')"
    )

    _open_with_keyboard(page, "[data-test-trigger]")
    _assert_keyboard_contract(page, modal, "[data-test-trigger]")


@pytest.mark.parametrize(
    ("trigger", "modal"),
    [
        ("#historyClearBtn", "#clearHistoryModal"),
        ('[data-history-action="delete"]', "#deleteHistoryModal"),
        ("a.history-thumb", "#lightboxModal"),
    ],
)
def test_history_dialogs_keyboard(
    live_server: str,
    browser_page: Page,
    device_config_dev: Any,
    trigger: str,
    modal: str,
) -> None:
    history_dir = Path(device_config_dev.history_image_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), "white").save(
        history_dir / "display_20260101_120000.png"
    )
    page = browser_page
    navigate_and_wait(page, live_server, "/history")
    first_trigger = f"{trigger} >> nth=0"
    page.locator(first_trigger).wait_for(state="visible")
    page.locator(first_trigger).evaluate(
        "node => node.setAttribute('data-test-trigger', '')"
    )

    _open_with_keyboard(page, "[data-test-trigger]")
    _assert_keyboard_contract(page, modal, "[data-test-trigger]")


def test_toasts_stay_live_while_a_dialog_is_open(
    live_server: str, browser_page: Page
) -> None:
    """An error toast raised from inside a dialog must still be announced."""
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")
    page.evaluate("showResponseModal('success', 'before')")
    page.locator(".toast-container").wait_for(state="attached")

    _open_with_keyboard(page, "#newPlaylistBtn")
    page.locator("#playlistModal").wait_for(state="visible")
    assert _is_inert(page, "#newPlaylistBtn")
    assert not _is_inert(page, ".toast-container")
