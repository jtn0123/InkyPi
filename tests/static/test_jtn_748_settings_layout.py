"""Regression tests for the /settings layout fixes in JTN-748."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS_PATH = ROOT / "src" / "static" / "styles" / "partials" / "_settings.css"
SETTINGS_HTML = ROOT / "src" / "templates" / "settings.html"


def test_settings_summary_device_name_truncates_cleanly():
    """Long device names in the settings summary should ellipsize."""
    css = CSS_PATH.read_text(encoding="utf-8")
    assert ".settings-device-name" in css
    assert "max-width: min(100%, 18rem)" in css
    assert "overflow: hidden" in css
    assert "text-overflow: ellipsis" in css
    assert "white-space: nowrap" in css

    html = SETTINGS_HTML.read_text(encoding="utf-8")
    assert 'class="status-chip info settings-device-name"' in html
    assert 'title="{{ device_settings.name }}"' in html


def test_settings_form_reserves_space_for_sticky_save_bar():
    """The sticky save bar needs a dedicated spacer on /settings."""
    css = CSS_PATH.read_text(encoding="utf-8")
    assert ".settings-form--sticky-save" in css
    assert "padding-bottom: calc(6rem + env(safe-area-inset-bottom, 0px))" in css

    html = SETTINGS_HTML.read_text(encoding="utf-8")
    assert 'class="settings-form settings-form--sticky-save"' in html
