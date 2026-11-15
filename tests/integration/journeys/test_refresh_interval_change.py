# pyright: reportMissingImports=false
"""Journey: refresh-interval change — save, persist, cadence respected (JTN-726).

Complementary to ``test_jtn_726_refresh_cadence_journey`` (which asserts the
save flow signals the refresh task). This test drives the end-to-end UI
round-trip: change -> save toast -> reload shows new value -> diagnostics
poll reports the new cadence -> the scheduler's due rule, fed from the
saved config, makes the next refresh due one new interval after the last.

The refresh task is not running in the test fixture, so we seed
``device_config.refresh_info.refresh_time`` (which ``/api/diagnostics``
exposes as ``refresh_task.last_run_ts``) and call ``schedule.is_due`` with
fixed times instead of waiting.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from playwright.sync_api import Page

pytestmark = [
    pytest.mark.integration,
    pytest.mark.journey,
    pytest.mark.skipif(
        os.getenv("SKIP_UI", "").lower() in ("1", "true"),
        reason="UI interactions skipped by env",
    ),
]

# Short cadence keeps the cadence-check step fast without making the save
# path reject the value (the backend clamps to 1..86400 seconds, so the UI
# expresses cadence in minutes/hours). 2 minutes -> 120s.
_NEW_INTERVAL_MINUTES = 2
_NEW_INTERVAL_SECONDS = _NEW_INTERVAL_MINUTES * 60


def _open_settings_scheduling(page: Page, live_server: str) -> Any:
    from tests.integration.browser_helpers import RuntimeCollector, stub_leaflet

    stub_leaflet(page)
    collector = RuntimeCollector(page, live_server)
    page.goto(f"{live_server}/settings", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector(".settings-console-layout", timeout=10000)
    page.click('[data-settings-tab="scheduling"]')
    page.wait_for_selector('[data-settings-panel="scheduling"].active', timeout=5000)
    # The scheduling panel's display-cycle section is now flat (no collapsible
    # toggle), so the interval input is visible once the panel is active.
    page.wait_for_selector("#interval:visible", timeout=5000)
    return collector


def test_refresh_interval_change_save_persist_cadence_respected(
    live_server: str,
    flask_app: Flask,
    device_config_dev: Any,
    browser_page: Page,
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Change cadence -> toast -> reload -> /api/diagnostics -> last_run_ts advances."""
    # INKYPI_ENV=dev keeps /api/diagnostics unauthenticated for the local
    # live_server + test client (mirrors test_diagnostics_endpoint.py).
    monkeypatch.setenv("INKYPI_ENV", "dev")

    page = browser_page
    collector = _open_settings_scheduling(page, live_server)

    # Precondition: seeded config uses a 300s / 5-minute cadence.
    assert page.locator("#interval").input_value() == "5"
    assert page.locator("#unit").input_value() == "minute"

    # ---- Step 1: change interval and save via UI; assert 200 + toast.
    page.fill("#interval", str(_NEW_INTERVAL_MINUTES))
    page.select_option("#unit", "minute")
    # The save button is gated on a dirty-form check; flush via blur.
    page.locator("#interval").press("Tab")
    page.wait_for_function(
        "() => !document.getElementById('saveSettingsBtn').disabled", timeout=5000
    )
    with page.expect_response(
        lambda r: "/save_settings" in r.url and r.request.method == "POST"
    ) as save_info:
        page.click("#saveSettingsBtn")
    assert save_info.value.status == 200, "save_settings should return 200"
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('.toast .toast-content'))"
        ".some((el) => (el.textContent || '').includes('Saved settings.'))",
        timeout=10000,
    )

    # Interval is stored as seconds.
    expected_seconds = _NEW_INTERVAL_SECONDS
    assert (
        device_config_dev.get_config("plugin_cycle_interval_seconds")
        == expected_seconds
    )

    # ---- Step 2: reload the page and assert the input shows the new value.
    page.goto(f"{live_server}/settings", wait_until="domcontentloaded", timeout=30000)
    page.click('[data-settings-tab="scheduling"]')
    page.wait_for_selector('[data-settings-panel="scheduling"].active', timeout=5000)
    # Display-cycle section is now flat (no collapsible toggle) after the
    # Settings refactor, so the interval input is visible once the panel is
    # active.
    page.wait_for_selector("#interval:visible", timeout=5000)
    assert page.locator("#interval").input_value() == str(_NEW_INTERVAL_MINUTES)

    # ---- Step 3: diagnostics poll reports the new cadence (equivalent
    # field: the config value that refresh_task consults each tick).
    diag = client.get("/api/diagnostics").get_json() or {}
    assert "refresh_task" in diag and isinstance(diag["refresh_task"], dict)
    assert (
        device_config_dev.get_config("plugin_cycle_interval_seconds")
        == expected_seconds
    ), "diagnostics snapshot and config must agree on the new cadence"

    # ---- Step 4: seed the last refresh, then ask the scheduler's own
    # "is a refresh due?" rule, fed from the saved config, at fixed times.
    # Under the old 5-minute cadence a refresh 2 minutes later would not be
    # due, so this proves the new interval is what the scheduler uses.
    from refresh_task import schedule

    # The scheduler only refreshes an active playlist with something in it.
    # The app's all-day Default playlist starts empty and sets no cycle of
    # its own, so give it a plugin; the device interval then applies.
    playlists = device_config_dev.get_playlist_manager()
    if playlists.get_playlist("Default") is None:
        playlists.add_playlist("Default", "00:00", "24:00")
    playlists.add_plugin_to_playlist(
        "Default",
        {"plugin_id": "clock", "name": "Clock", "plugin_settings": {}},
    )

    t0 = datetime.now(UTC).replace(microsecond=0)
    device_config_dev.refresh_info.refresh_time = t0.isoformat()
    diag = client.get("/api/diagnostics").get_json() or {}
    assert diag["refresh_task"]["last_run_ts"] == t0.isoformat()

    def due_at(seconds_after: float) -> bool:
        return schedule.is_due(
            playlist_manager=device_config_dev.get_playlist_manager(),
            latest_refresh=device_config_dev.refresh_info.get_refresh_datetime(),
            last_attempt=None,
            now=t0 + timedelta(seconds=seconds_after),
            device_interval=schedule.device_interval_seconds(device_config_dev),
        )

    assert not due_at(expected_seconds - 1), "refresh due before the new interval"
    assert due_at(expected_seconds), "refresh not due once the new interval passed"

    collector.assert_no_errors(name="refresh_interval_change")
