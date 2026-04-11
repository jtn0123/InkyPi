"""Tests for plugin settings UX polish (JTN-184, JTN-174, JTN-157, JTN-158, JTN-154)."""

from pathlib import Path


def test_todo_remove_last_item_guarded():
    """bindRemoveButtons must prevent removing the last dynamic-list-item."""
    js = Path("src/static/scripts/plugin_schema.js").read_text()
    # Check for the guard condition
    assert "dynamic-list-item" in js
    assert "length <= 1" in js or "length < 2" in js


def test_calendar_repeater_has_descriptive_placeholder():
    """Calendar URL input should have a descriptive placeholder."""
    html = Path("src/templates/widgets/calendar_repeater.html").read_text()
    # lgtm[py/incomplete-url-substring-sanitization] — not URL sanitization;
    # asserting that a Jinja template's static placeholder contains an example
    # hostname for UX. No URL is parsed or trusted here.
    assert ".ics" in html or "calendar.google.com" in html


def test_calendar_repeater_has_help_text():
    """Calendar repeater should have help text."""
    html = Path("src/templates/widgets/calendar_repeater.html").read_text()
    assert "field-note" in html


def test_settings_schema_has_option_group():
    """settings_schema.py must have option_group helper."""
    py = Path("src/plugins/base_plugin/settings_schema.py").read_text()
    assert "def option_group" in py


def test_settings_schema_template_has_optgroup():
    """settings_schema.html must support optgroup rendering."""
    tpl = Path("src/templates/settings_schema.html").read_text()
    assert "optgroup" in tpl


def test_locale_groups_covers_locale_map():
    """Every locale in LOCALE_MAP must appear in LOCALE_GROUPS."""
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
    from plugins.calendar.constants import LOCALE_GROUPS, LOCALE_MAP

    grouped_codes = {code for _, locales in LOCALE_GROUPS for code, _ in locales}
    for code in LOCALE_MAP:
        assert code in grouped_codes, f"Locale {code!r} missing from LOCALE_GROUPS"
