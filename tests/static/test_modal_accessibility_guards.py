# pyright: reportMissingImports=false
"""Regression guards for modal keyboard dismissal hooks."""

from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "scripts"


def _read_script(name: str) -> str:
    return (_SCRIPTS_DIR / name).read_text(encoding="utf-8")


def test_history_page_script_handles_escape_for_open_modals():
    content = _read_script("history_page.js")

    assert 'event.key !== "Escape"' in content
    assert "deleteHistoryModal" in content
    assert "clearHistoryModal" in content


def test_playlist_script_handles_escape_for_playlist_modals():
    content = _read_script("playlist.js")

    assert "getOpenModalId" in content
    assert "closeModalById" in content
    assert "deleteInstanceModal" in content
    assert "deviceCycleModal" in content
    assert "event.key !== 'Escape'" in content


def test_image_modal_script_handles_escape_and_null_container():
    content = _read_script("image_modal.js")

    assert "if (!imageContainer) return;" in content
    assert "e.key === 'Escape'" in content


def test_plugin_page_schedule_modal_handles_escape():
    """JTN-461: #scheduleModal closes on Escape key."""
    content = _read_script("plugin_page.js")

    assert 'event.key !== "Escape"' in content
    assert "scheduleModal" in content


def test_plugin_page_open_modal_focuses_first_focusable():
    """JTN-463: openModal moves focus to first focusable element on open."""
    content = _read_script("plugin_page.js")

    assert "focusable.focus()" in content
    assert "_lastModalTrigger" in content


def test_settings_page_reboot_shutdown_modals_handle_escape():
    """JTN-652: /settings reboot + shutdown confirm modals close on Escape."""
    content = _read_script("settings_page.js")

    assert 'event.key !== "Escape"' in content
    assert "rebootConfirmModal" in content
    assert "shutdownConfirmModal" in content


def test_settings_page_device_action_modals_manage_focus():
    """JTN-652: /settings confirm modals move focus in on open and restore
    focus to the trigger on close."""
    content = _read_script("settings_page.js")

    assert "focusable.focus()" in content
    assert "_lastDeviceActionTrigger" in content
