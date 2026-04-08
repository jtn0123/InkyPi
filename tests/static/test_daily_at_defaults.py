"""Tests for JTN-227: Daily-at scheduling should prefill 09:00 and show help text.

Verifies both the template (refresh_settings_form.html) and the JS manager
(refresh_settings_manager.js) contain the logic for:
  Option A – prefill the time input with '09:00' when no value is present.
  Option B – show inline guidance text when Daily at is active.
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "src" / "templates" / "refresh_settings_form.html"
MANAGER_JS = ROOT / "src" / "static" / "scripts" / "refresh_settings_manager.js"


class TestDailyAtTemplateDefaults:
    """Verify the refresh_settings_form.html template has the required markup."""

    def test_help_text_element_present(self):
        """The template must contain a help-text paragraph for the scheduled mode."""
        html = TEMPLATE.read_text()
        assert "scheduled-help" in html, (
            "refresh_settings_form.html must contain an element with id "
            "'{{ prefix }}-scheduled-help' for inline guidance (Option B)"
        )

    def test_help_text_initially_hidden(self):
        """The help text must start hidden so it only appears when Daily at is active."""
        html = TEMPLATE.read_text()
        # The element should have display:none in its initial inline style
        assert (
            "display:none" in html or "display: none" in html
        ), "The scheduled-help element must start with display:none"

    def test_help_text_content(self):
        """The help text must include the expected guidance copy."""
        html = TEMPLATE.read_text()
        assert (
            "Pick a time of day for the refresh" in html
        ), "Help text must say 'Pick a time of day for the refresh.'"

    def test_template_prefills_default_on_switch(self):
        """The inline script must set inputScheduled.value to '09:00' when empty."""
        html = TEMPLATE.read_text()
        assert "09:00" in html, (
            "refresh_settings_form.html inline script must contain '09:00' as "
            "the default time for the Daily at option (Option A)"
        )

    def test_help_text_toggled_by_mode(self):
        """The inline script must toggle the help element visibility."""
        html = TEMPLATE.read_text()
        # The script must reference scheduled-help to show/hide it
        assert "scheduled-help" in html, (
            "The inline script must reference the scheduled-help element to "
            "show it when Daily at is active and hide it otherwise"
        )


class TestDailyAtManagerDefaults:
    """Verify refresh_settings_manager.js applies defaults and shows help text."""

    def test_manager_has_sync_method(self):
        """The manager must have a syncScheduledDefaults method."""
        js = MANAGER_JS.read_text()
        assert "syncScheduledDefaults" in js, (
            "refresh_settings_manager.js must define syncScheduledDefaults() "
            "to handle Option A and Option B logic"
        )

    def test_manager_prefills_default_time(self):
        """syncScheduledDefaults must set '09:00' when no time is selected."""
        js = MANAGER_JS.read_text()
        assert (
            "09:00" in js
        ), "refresh_settings_manager.js must default the time input to '09:00'"

    def test_manager_toggles_help_text(self):
        """syncScheduledDefaults must show/hide the help element."""
        js = MANAGER_JS.read_text()
        assert "scheduled-help" in js, (
            "refresh_settings_manager.js must reference 'scheduled-help' to "
            "toggle the inline guidance text"
        )

    def test_manager_calls_sync_on_radio_click(self):
        """Clicking either radio must trigger syncScheduledDefaults."""
        js = MANAGER_JS.read_text()
        # syncScheduledDefaults is called from activateGroup which is called
        # by the radio click handlers
        assert "this.syncScheduledDefaults()" in js, (
            "refresh_settings_manager.js must call syncScheduledDefaults() "
            "when the user clicks a radio button"
        )

    def test_manager_does_not_overwrite_existing_value(self):
        """The default must only apply when the time input is empty (!value check)."""
        js = MANAGER_JS.read_text()
        assert "!this.inputScheduled.value" in js, (
            "refresh_settings_manager.js must guard the default with "
            "'!this.inputScheduled.value' so existing times are not overwritten"
        )
