"""Regression tests for the /settings layout fixes in JTN-748."""

import re
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
    # JTN-748's concern is the truncation rule — the chip variant
    # (info/neutral/accent) is an unrelated styling choice that should be
    # free to change with the design system. Since the settings page has
    # both chrome-level (`.settings-device-name`) and page-header
    # (`.settings-page-device-name`) chips — with the former hidden by
    # CSS to avoid redundancy (CodeRabbit review, PR #570) — accept
    # either truncation-styled class. Lookaheads keep the test agnostic
    # to class-attribute token order.
    chip_match = re.search(
        r'class="(?=[^"]*\bstatus-chip\b)'
        r'(?=[^"]*\bsettings(?:-page)?-device-name\b)[^"]*"',
        html,
    )
    assert chip_match, (
        "expected a .status-chip with either .settings-device-name or "
        ".settings-page-device-name"
    )
    assert 'title="{{ device_settings.name }}"' in html


def test_settings_form_reserves_space_for_sticky_save_bar():
    """The sticky save bar needs a dedicated spacer on /settings."""
    css = CSS_PATH.read_text(encoding="utf-8")
    assert ".settings-form--sticky-save" in css
    assert "padding-bottom: calc(6rem + env(safe-area-inset-bottom, 0px))" in css

    html = SETTINGS_HTML.read_text(encoding="utf-8")
    assert 'class="settings-form settings-form--sticky-save"' in html
