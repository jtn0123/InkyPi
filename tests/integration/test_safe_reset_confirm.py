# pyright: reportMissingImports=false
"""Safe reset asks first, and the page shows the reset values afterwards.

Without the reload, the settings form kept the old interval, so the next
Save posted it back and quietly undid the reset.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402


def _open_power_tab(page: Page) -> None:
    page.locator('[data-settings-tab="power"]').first.click()
    page.wait_for_selector("#safeResetBtn", state="visible", timeout=10000)


def test_safe_reset_asks_first_then_reloads_with_the_reset_values(
    live_server: str, device_config_dev: Any, browser_page: Page, tmp_path: Path
) -> None:
    device_config_dev.update_value("plugin_cycle_interval_seconds", 300, write=True)
    page = browser_page
    resets: list[str] = []
    page.on(
        "request",
        lambda r: (
            resets.append(r.url)
            if r.method == "POST" and r.url.endswith("/settings/safe_reset")
            else None
        ),
    )
    rc = navigate_and_wait(page, live_server, "/settings")
    _open_power_tab(page)

    # Opening and cancelling the dialog changes nothing.
    modal = page.locator("#safeResetConfirmModal")
    page.locator("#safeResetBtn").click()
    modal.wait_for(state="visible", timeout=5000)
    assert resets == [], "Safe reset must ask before resetting"
    page.locator("#cancelSafeResetBtn").click()
    modal.wait_for(state="hidden", timeout=5000)
    assert resets == []
    assert device_config_dev.get_config("plugin_cycle_interval_seconds") == 300

    # Confirming resets, then reloads the page.
    page.locator("#safeResetBtn").click()
    modal.wait_for(state="visible", timeout=5000)
    with page.expect_event("domcontentloaded"):
        page.locator("#confirmSafeResetBtn").click()
    assert len(resets) == 1
    assert device_config_dev.get_config("plugin_cycle_interval_seconds") == 3600

    # The result is shown after the reload, and the form holds the new
    # interval, so the next Save keeps the reset.
    page.get_by_text("Safe reset applied.").first.wait_for(timeout=10000)
    page.locator('[data-settings-tab="scheduling"]').first.click()
    page.wait_for_selector("#interval:visible", timeout=5000)
    shown = (
        page.locator("#interval").input_value(),
        page.locator("#unit").input_value(),
    )
    assert shown in {("1", "hour"), ("60", "minute")}, shown

    rc.assert_no_errors(str(tmp_path), "safe_reset_confirm")
