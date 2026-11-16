# pyright: reportMissingImports=false
"""Settings shows the saved display cycle in a unit that keeps its value.

The page chose hours whenever the cycle was an hour or more, flooring the
rest away: 5400 s showed as "1 hour". The form took that as its saved state,
so the next Save, of any field, wrote 3600 s. Hours are now used only for a
whole number of hours; anything else shows in minutes.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402


def _seed_cycle(device_config_dev: Any, seconds: int) -> None:
    device_config_dev.update_value("plugin_cycle_interval_seconds", seconds, write=True)


def _open_scheduling(page: Page, live_server: str) -> Any:
    collector = navigate_and_wait(page, live_server, "/settings")
    page.click('[data-settings-tab="scheduling"]')
    page.wait_for_selector('[data-settings-panel="scheduling"].active', timeout=5000)
    page.wait_for_selector("#interval:visible", timeout=5000)
    return collector


@pytest.mark.parametrize(
    ("seconds", "value", "unit"),
    [
        (5400, "90", "minute"),
        (7200, "2", "hour"),
        (3600, "1", "hour"),
        (300, "5", "minute"),
        # The unit list has no seconds; less than a minute shows as 1 minute
        # rather than 0, which the field's min="1" would reject.
        (30, "1", "minute"),
    ],
    ids=["90-minutes", "2-hours", "1-hour", "5-minutes", "under-a-minute"],
)
def test_cycle_shows_in_a_unit_that_keeps_its_value(
    live_server: str,
    device_config_dev: Any,
    browser_page: Page,
    seconds: int,
    value: str,
    unit: str,
) -> None:
    _seed_cycle(device_config_dev, seconds)
    page = browser_page
    collector = _open_scheduling(page, live_server)

    expect(page.locator("#interval")).to_have_value(value)
    expect(page.locator("#unit")).to_have_value(unit)
    # The page's own saved state matches, so nothing reads as unsaved.
    expect(page.locator("#saveSettingsBtn")).to_be_disabled()
    collector.assert_no_errors(name=f"interval_display_{seconds}")


def test_saving_another_setting_keeps_a_90_minute_cycle(
    live_server: str, device_config_dev: Any, browser_page: Page
) -> None:
    _seed_cycle(device_config_dev, 5400)
    page = browser_page
    collector = navigate_and_wait(page, live_server, "/settings")

    name = page.locator("#deviceName")
    name.scroll_into_view_if_needed()
    name.fill("Hall frame")
    save = page.locator("#saveSettingsBtn")
    expect(save).to_be_enabled()
    with page.expect_response(
        lambda r: "/save_settings" in r.url and r.request.method == "POST"
    ) as saved:
        save.click()
    assert saved.value.status == 200
    expect(save).to_be_disabled()

    assert device_config_dev.get_config("name") == "Hall frame"
    assert device_config_dev.get_config("plugin_cycle_interval_seconds") == 5400

    # And it still reads 90 minutes after a reload.
    _open_scheduling(page, live_server)
    expect(page.locator("#interval")).to_have_value("90")
    expect(page.locator("#unit")).to_have_value("minute")
    collector.assert_no_errors(name="interval_save_keeps_90_minutes")
