# pyright: reportMissingImports=false
"""Regression guards for modal keyboard dismissal hooks."""

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
_SCRIPTS_DIR = _SRC / "static" / "scripts"
_TEMPLATES_DIR = _SRC / "templates"


def _read_script(name: str) -> str:
    return (_SCRIPTS_DIR / name).read_text(encoding="utf-8")


def test_history_page_dialogs_close_through_the_shared_helper() -> None:
    # InkyPiModalFocus handles Escape and fires inkypi:modal-dismiss on the
    # dialog; each history dialog must listen for it. A page-level Escape
    # handler would never run: the helper stops the key first.
    content = _read_script("history_page.js")

    for modal_id in ("deleteHistoryModal", "clearHistoryModal", "lightboxModal"):
        assert (
            f'getElementById("{modal_id}")?.addEventListener("inkypi:modal-dismiss"'
            in content
        ), modal_id
    assert 'event.key !== "Escape"' not in content


# Every custom dialog goes through the shared InkyPiModalFocus helper, which
# moves focus in, keeps Tab inside, closes on Escape and restores focus.
# tests/integration/test_modal_keyboard_e2e.py checks that behaviour in a real
# browser; this cheap guard keeps a dialog from quietly dropping the helper in
# lanes where browser tests are skipped.
@pytest.mark.parametrize(
    "script",
    [
        "errors_page.js",
        "history_page.js",
        "lightbox.js",
        "playlist/modals.js",
        "plugin_page.js",
        "plugin_schema.js",
        "settings/modals.js",
    ],
)
def test_dialog_scripts_use_the_shared_focus_helper(script: str) -> None:
    content = _read_script(script)

    assert "InkyPiModalFocus?.activate" in content or (
        "InkyPiModalFocus.activate" in content
    )
    assert "InkyPiModalFocus?.deactivate" in content or (
        "InkyPiModalFocus.deactivate" in content
    )


def test_playlist_escape_routes_every_dialog_to_its_close_function() -> None:
    content = _read_script("playlist/modals.js")
    # Read the dialogs from the page itself, so a new one can't be missed and
    # a removed one doesn't keep its close code alive.
    template = (_TEMPLATES_DIR / "playlist.html").read_text(encoding="utf-8")
    modal_ids = set(re.findall(r'id="(\w+Modal)"', template))
    assert {"playlistModal", "refreshSettingsModal"} <= modal_ids

    routed = set(re.findall(r'case "(\w+Modal)":', content))
    assert routed == modal_ids


def test_settings_page_reboot_shutdown_modals_handle_escape() -> None:
    """JTN-652: /settings reboot + shutdown confirm modals close on Escape."""
    content = _read_script("settings/modals.js")

    assert 'event.key !== "Escape"' in content
    assert "rebootConfirmModal" in content
    assert "shutdownConfirmModal" in content


def test_settings_page_device_action_modals_manage_focus() -> None:
    """JTN-652: /settings confirm modals move focus in on open and restore
    focus to the trigger on close."""
    content = _read_script("settings/modals.js")

    assert "InkyPiModalFocus.activate" in content
    assert "InkyPiModalFocus.deactivate" in content


def test_plugin_workflow_panels_do_not_hide_content_from_assistive_tech() -> None:
    """Design refresh: both Configure and Preview panels render together on every
    viewport (the old Configure/Preview mode bar was removed). Neither panel
    should be force-hidden via inert or aria-hidden='true' by setWorkflowMode —
    every interactive control must stay in the focus order.
    """
    content = _read_script("plugin_page.js")

    # The panels should be marked aria-hidden="false" (not "true") in the
    # mode setter, and inert should be *removed*, not applied.
    assert 'removeAttribute("inert")' in content
    assert 'setAttribute("aria-hidden", "false")' in content
