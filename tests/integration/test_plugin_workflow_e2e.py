# pyright: reportMissingImports=false
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402


def test_plugin_settings_form_has_fields(live_server, browser_page, tmp_path):
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/plugin/clock")

    form = page.locator("#settingsForm")
    form.wait_for(state="visible", timeout=5000)
    assert form.is_visible(), "Settings form should be visible on plugin page"

    inputs = form.locator("input, select, textarea")
    assert inputs.count() > 0, "Settings form should contain input fields"

    rc.assert_no_errors(str(tmp_path), "plugin_form_fields")


def test_plugin_settings_form_fields_editable(live_server, browser_page, tmp_path):
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/plugin/clock")

    form = page.locator("#settingsForm")
    form.wait_for(state="visible", timeout=5000)

    text_input = form.locator("input[type='text'], input:not([type])")
    assert text_input.count() > 0, "Form should have at least one text input"
    first_input = text_input.first
    first_input.fill("test-value-123")
    value = first_input.input_value()
    assert value == "test-value-123", f"Input should accept typed value, got '{value}'"

    rc.assert_no_errors(str(tmp_path), "plugin_form_editable")


def test_plugin_page_has_workflow_tabs(live_server, browser_page, tmp_path):
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/plugin/clock")

    configure_tab = page.locator("[data-workflow-mode='configure']")
    preview_tab = page.locator("[data-workflow-mode='preview']")

    assert configure_tab.count() > 0, "Configure workflow tab should exist"
    assert preview_tab.count() > 0, "Preview workflow tab should exist"

    configure_tab.first.click()
    page.wait_for_timeout(300)

    preview_tab.first.click()
    page.wait_for_timeout(300)

    rc.assert_no_errors(str(tmp_path), "plugin_workflow_tabs")
