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
