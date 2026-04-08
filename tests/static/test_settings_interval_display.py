"""Tests for sub-minute interval display fix in settings page (JTN-245)."""

from pathlib import Path


def test_populate_interval_fields_clamps_sub_minute():
    """JTN-245: Values < 60 seconds must not display as '0 minutes'.

    Math.max(1, intervalInMinutes) ensures that sub-minute intervals
    are shown as 1 minute rather than 0 minutes (which fails min="1" validation).
    """
    js = Path("src/static/scripts/settings_page.js").read_text()
    assert "Math.max(1, intervalInMinutes)" in js


def test_populate_interval_fields_hours_branch_unchanged():
    """The hours branch should still use the raw hour value without clamping."""
    js = Path("src/static/scripts/settings_page.js").read_text()
    assert "intervalInput.value = String(intervalInHours)" in js
    assert 'unitSelect.value = "hour"' in js


def test_unit_select_has_no_second_option():
    """The unit <select> has no 'second' option, so clamping is the correct fix."""
    html = Path("src/templates/settings.html").read_text()
    # Confirm minute and hour options exist
    assert 'value="minute"' in html
    assert 'value="hour"' in html
    # Confirm second option is absent (clamping approach is correct)
    assert 'value="second"' not in html
