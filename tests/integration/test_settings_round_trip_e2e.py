# pyright: reportMissingImports=false
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402


def test_change_device_name_persists(live_server, browser_page):
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")

    name_input = page.locator("#deviceName")
    name_input.wait_for(state="attached", timeout=5000)
    name_input.scroll_into_view_if_needed()
    name_input.fill("")
    name_input.fill("TestInkyDevice")

    save_btn = page.locator("#saveSettingsBtn")
    save_btn.scroll_into_view_if_needed()
    save_btn.click()
    page.wait_for_timeout(2000)

    # Reload and verify persistence
    navigate_and_wait(page, live_server, "/settings")
    name_input = page.locator("#deviceName")
    name_input.wait_for(state="attached", timeout=5000)
    value = name_input.input_value()
    assert value == "TestInkyDevice", f"Device name should persist, got '{value}'"


def test_change_timezone_persists(live_server, browser_page):
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")

    # Time & Locale is now a flat section (design handoff) inside the Device
    # panel — no expand click needed.
    tz_input = page.locator("#timezone")
    tz_input.wait_for(state="visible", timeout=5000)
    tz_input.scroll_into_view_if_needed()
    tz_input.fill("")
    tz_input.fill("US/Eastern")

    save_btn = page.locator("#saveSettingsBtn")
    save_btn.scroll_into_view_if_needed()
    save_btn.click()
    page.wait_for_timeout(2000)

    navigate_and_wait(page, live_server, "/settings")
    tz_input = page.locator("#timezone")
    tz_input.wait_for(state="attached", timeout=5000)
    value = tz_input.input_value()
    assert value == "US/Eastern", f"Timezone should persist, got '{value}'"


def test_image_slider_values_persist(live_server, browser_page):
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")

    page.locator("#saturation").wait_for(state="attached", timeout=5000)
    page.evaluate("""() => {
        const slider = document.getElementById('saturation');
        slider.value = '1.5';
        slider.dispatchEvent(new Event('input', { bubbles: true }));
        slider.dispatchEvent(new Event('change', { bubbles: true }));
    }""")

    save_btn = page.locator("#saveSettingsBtn")
    save_btn.scroll_into_view_if_needed()
    save_btn.click()
    page.wait_for_timeout(2000)

    navigate_and_wait(page, live_server, "/settings")
    page.locator("#saturation").wait_for(state="attached", timeout=5000)
    value = page.locator("#saturation").input_value()
    assert value == "1.5", f"Saturation slider should persist at 1.5, got '{value}'"


def test_orientation_persists(live_server, browser_page):
    """Orientation is now a segmented-radio control — check() the vertical
    option instead of select_option(). FormData still serializes the chosen
    radio as `orientation=vertical` so the round-trip contract is preserved.
    """
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")

    vertical_radio = page.locator("input[name='orientation'][value='vertical']")
    vertical_radio.wait_for(state="attached", timeout=5000)
    vertical_radio.scroll_into_view_if_needed()
    vertical_radio.check()

    save_btn = page.locator("#saveSettingsBtn")
    save_btn.scroll_into_view_if_needed()
    save_btn.click()
    page.wait_for_timeout(2000)

    navigate_and_wait(page, live_server, "/settings")
    vertical_radio = page.locator("input[name='orientation'][value='vertical']")
    vertical_radio.wait_for(state="attached", timeout=5000)
    assert vertical_radio.is_checked(), "Vertical orientation should persist"
