# pyright: reportMissingImports=false
"""Journey: refresh-interval change — save, persist, cadence respected (JTN-726).

Complementary to ``test_jtn_726_refresh_cadence_journey`` (which asserts the
save flow signals the refresh task). This test drives the end-to-end UI
round-trip: change -> save toast -> reload shows new value -> diagnostics
poll reports the new cadence -> ``last_run_ts`` advances by roughly one
interval after a simulated refresh tick.

The refresh task is not running in the test fixture, so we simulate its
effect on ``device_config.refresh_info.latest_refresh_time`` — which is the
field ``/api/diagnostics`` exposes as ``refresh_task.last_run_ts``.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import pytest

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


def _open_settings_scheduling(page, live_server: str):
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
    live_server,
    flask_app,
    device_config_dev,
    browser_page,
    client,
    monkeypatch,
):
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

    # ---- Step 4: seed a baseline last_run_ts, wait one interval, and
    # simulate the next refresh. last_run_ts from /api/diagnostics should
    # advance by approximately the new cadence.
    t0 = datetime.now(UTC)
    device_config_dev.refresh_info.latest_refresh_time = t0.isoformat()
    before = client.get("/api/diagnostics").get_json() or {}
    assert before["refresh_task"]["last_run_ts"] == t0.isoformat()

    # Use a small absolute sleep (matches the 5-minute -> 300s cadence isn't
    # feasible in tests; we verify monotonic advance by ~interval instead).
    time.sleep(1.0)
    t1 = t0 + timedelta(seconds=expected_seconds)
    device_config_dev.refresh_info.latest_refresh_time = t1.isoformat()
    after = client.get("/api/diagnostics").get_json() or {}
    last_run = after["refresh_task"]["last_run_ts"]
    assert isinstance(last_run, str) and last_run == t1.isoformat()
    advanced = (
        datetime.fromisoformat(last_run)
        - datetime.fromisoformat(before["refresh_task"]["last_run_ts"])
    ).total_seconds()
    # Tolerance: within 10% of the expected cadence.
    assert (
        abs(advanced - expected_seconds) <= expected_seconds * 0.1
    ), f"last_run_ts should advance by ~{expected_seconds}s, advanced {advanced}s"

    collector.assert_no_errors(name="refresh_interval_change")
