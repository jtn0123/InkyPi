# pyright: reportMissingImports=false
"""Journey: first-run setup — add plugin, schedule, refresh, history (JTN-720).

This is the first journey test under epic JTN-719. Unlike the click-sweep
tests (JTN-679/693/698) which only verify handlers fire without error, this
test drives a full multi-step user flow end-to-end and asserts the *end
state* at every checkpoint.

Flow:
    1. Load dashboard (``/``) on a fresh-install fixture.
    2. Save plugin settings for the clock (creates instance in Default).
    3. Reload plugin page — verify config persisted.
    4. Schedule a second clock instance on the playlist with a refresh
       interval via ``/add_plugin``.
    5. Trigger a manual refresh via ``/update_now`` (refresh_task is not
       running in tests, so the direct-render fallback writes a history
       entry synchronously).
    6. Poll ``/api/diagnostics`` — verify the refresh_task snapshot shape.
    7. Load ``/history`` and assert the new sidecar entry shows the
       clock plugin with a fresh timestamp.

Gating: ``SKIP_UI=1`` disables the browser-based checks (live_server +
browser_page). The API-only portion still runs so the journey has value
even in minimal CI lanes.  ``SKIP_BROWSER=1`` is honored identically.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.journey


_SKIP_UI = os.getenv("SKIP_UI", "").lower() in ("1", "true") or os.getenv(
    "SKIP_BROWSER", ""
).lower() in ("1", "true")


def _playwright_chromium_available() -> bool:
    """Return True only when a real Chromium binary is installed locally.

    Mirrors the detection in ``tests/conftest.py`` so the UI variant of this
    journey cleanly skips in CI lanes that don't install Playwright browsers
    (the main ``pytest`` job) instead of erroring at fixture setup.
    """
    try:  # pragma: no cover - best-effort probe
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            browser.close()
        return True
    except Exception:
        return False


_SKIP_UI = _SKIP_UI or not _playwright_chromium_available()


def _latest_history_sidecar(history_dir: Path) -> dict | None:
    """Return the parsed JSON sidecar of the newest history entry, if any."""
    if not history_dir.is_dir():
        return None
    sidecars = sorted(
        (p for p in history_dir.iterdir() if p.suffix == ".json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not sidecars:
        return None
    try:
        return json.loads(sidecars[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def test_first_run_setup_journey(client, device_config_dev, flask_app):
    """Full first-run journey with per-step assertions."""
    app = flask_app
    # Refresh task is constructed but not started in the test fixture; keep
    # ``running=False`` so ``/update_now`` falls through to the direct-render
    # path that writes a history entry synchronously.
    rt = app.config["REFRESH_TASK"]
    assert rt.running is False, "precondition: refresh_task should be idle in tests"

    pm = device_config_dev.get_playlist_manager()

    # ---- Step 1: fresh dashboard loads and has no plugin instances yet.
    resp = client.get("/")
    assert resp.status_code == 200, resp.data[:200]
    assert pm.get_playlist_names() == [] or all(
        not pl.plugins for pl in pm.playlists
    ), "precondition: no plugin instances on a fresh install"

    # ---- Step 2: configure the clock plugin and save its settings.
    save_resp = client.post(
        "/save_plugin_settings",
        data={
            "plugin_id": "clock",
            "timeZone": "UTC",
            "timeFormat": "24h",
        },
    )
    assert save_resp.status_code == 200, save_resp.data[:500]
    saved = save_resp.get_json() or {}
    assert saved.get("success") is True
    saved_instance = saved.get("instance_name") or "clock_saved_settings"

    # Assertion: config persisted — reload and confirm the instance exists.
    default_pl = pm.get_playlist("Default")
    assert default_pl is not None, "save_plugin_settings should create Default playlist"
    persisted = default_pl.find_plugin("clock", saved_instance)
    assert persisted is not None, "clock instance should be persisted to Default"
    assert (persisted.settings or {}).get("timeZone") == "UTC"

    # Reload the plugin GET page to confirm round-trip survives a fresh read.
    plugin_page = client.get(f"/plugin/clock?instance={saved_instance}")
    assert plugin_page.status_code == 200

    # ---- Step 3: schedule a second clock instance on the playlist with a
    # specific refresh interval (simulates the "add to playlist" UI path).
    scheduled_instance = "Clock Schedule"
    add_resp = client.post(
        "/add_plugin",
        data={
            "plugin_id": "clock",
            "refresh_settings": json.dumps(
                {
                    "playlist": "Default",
                    "instance_name": scheduled_instance,
                    "refreshType": "interval",
                    "unit": "minute",
                    "interval": 5,
                }
            ),
            "timeZone": "UTC",
            "timeFormat": "24h",
        },
    )
    assert add_resp.status_code == 200, add_resp.data[:500]

    scheduled = default_pl.find_plugin("clock", scheduled_instance)
    assert scheduled is not None, "scheduled clock instance must appear in playlist"
    assert scheduled.refresh.get("interval") in (
        300,
        "300",
        5,
        "5",
    ), f"refresh interval should be stored (got {scheduled.refresh!r})"

    # ---- Step 4: trigger a manual refresh. With refresh_task.running=False
    # the handler falls through to the synchronous direct-render path,
    # which writes a history entry via DisplayManager.display_image.
    before_ts = datetime.now(UTC)
    refresh_resp = client.post(
        "/update_now",
        data={"plugin_id": "clock", "timeZone": "UTC", "timeFormat": "24h"},
    )
    assert refresh_resp.status_code == 200, refresh_resp.data[:500]
    refresh_body = refresh_resp.get_json() or {}
    assert refresh_body.get("success") is True
    assert "metrics" in refresh_body, "direct render path should report metrics"

    # ---- Step 5: diagnostics endpoint exposes the refresh_task snapshot.
    diag_resp = client.get("/api/diagnostics")
    assert diag_resp.status_code == 200
    diag = diag_resp.get_json() or {}
    assert "refresh_task" in diag, "diagnostics must include refresh_task snapshot"
    rt_snap = diag["refresh_task"]
    assert set(rt_snap.keys()) >= {"running", "last_run_ts", "last_error"}
    assert rt_snap["last_error"] in (
        None,
        "",
    ), f"refresh should not have recorded an error: {rt_snap['last_error']!r}"

    # ---- Step 6: history page renders and the newest sidecar points at clock.
    history_resp = client.get("/history")
    assert history_resp.status_code == 200
    assert "No history yet." not in history_resp.get_data(as_text=True)

    history_dir = Path(device_config_dev.history_image_dir)
    sidecar = _latest_history_sidecar(history_dir)
    assert sidecar is not None, f"expected a history sidecar in {history_dir}"
    assert (
        sidecar.get("plugin_id") == "clock"
    ), f"newest history entry should be for clock (got {sidecar!r})"

    # Timestamp sanity: within a generous 5-minute window of when we triggered.
    ts_raw = sidecar.get("refresh_time")
    assert isinstance(ts_raw, str) and ts_raw, "sidecar must record refresh_time"
    parsed = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delta = abs((parsed - before_ts).total_seconds())
    assert delta < 300, f"history timestamp {ts_raw} too far from trigger {before_ts}"


@pytest.mark.skipif(_SKIP_UI, reason="UI interactions skipped by env")
def test_first_run_setup_journey_ui_render(
    client, device_config_dev, flask_app, live_server, browser_page
):
    """Browser-level companion: after API-driven setup the history page
    renders the new entry with the plugin name visible to the user.

    This adds UI coverage on top of the API-level journey without duplicating
    every assertion — the core journey test above already guards the data
    model.  Here we only verify the rendered DOM so regressions in the
    history template (e.g. truncated metadata, missing images) are caught.
    """
    from tests.integration.browser_helpers import navigate_and_wait

    # Run the minimum setup inline so this test is independent of the
    # API-only case above.
    client.post(
        "/save_plugin_settings",
        data={"plugin_id": "clock", "timeZone": "UTC", "timeFormat": "24h"},
    )
    refresh = client.post(
        "/update_now",
        data={"plugin_id": "clock", "timeZone": "UTC", "timeFormat": "24h"},
    )
    assert refresh.status_code == 200

    page = browser_page
    rc = navigate_and_wait(page, live_server, "/history")
    page.wait_for_selector("#storage-block", timeout=10000)

    body = page.content()
    assert "No history yet." not in body, "history page must render the new entry"
    assert "clock" in body.lower(), "plugin id should appear on the history page"

    rc.assert_no_errors(name="journey_first_run_history")
