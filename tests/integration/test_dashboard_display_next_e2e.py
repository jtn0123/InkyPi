# pyright: reportMissingImports=false
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import (  # noqa: E402
    navigate_and_wait,
    prepare_playlist,
)


def test_display_next_button_exists(
    live_server, device_config_dev, browser_page, tmp_path
):
    prepare_playlist(device_config_dev)
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/")

    display_next = page.locator("#displayNextBtn, button:has-text('Display next')")
    display_next.first.wait_for(state="visible", timeout=5000)
    assert display_next.first.is_visible(), "Display next button should be visible"

    rc.assert_no_errors(str(tmp_path), "display_next_exists")


def test_display_next_sends_request(
    live_server, device_config_dev, browser_page, tmp_path
):
    prepare_playlist(device_config_dev)
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/")

    # Mock fetch AFTER navigation so JS context is live
    page.evaluate("""() => {
        const origFetch = window.fetch;
        window.__fetchCalls = [];
        window.fetch = function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : args[0].url;
            const opts = args[1] || {};
            window.__fetchCalls.push({url: url, method: opts.method || 'GET'});
            if (url.includes('display-next') || url.includes('display_next')) {
                return Promise.resolve(new Response(JSON.stringify({status: 'success'}), {
                    status: 200,
                    headers: {'Content-Type': 'application/json'}
                }));
            }
            return origFetch.apply(this, args);
        };
        window.location.reload = function() {};
    }""")

    display_next = page.locator("#displayNextBtn, button:has-text('Display next')")
    display_next.first.wait_for(state="visible", timeout=5000)
    display_next.first.click()
    page.wait_for_timeout(1000)

    calls = page.evaluate("() => window.__fetchCalls || []")
    display_next_calls = [
        c
        for c in calls
        if "display-next" in c.get("url", "") or "display_next" in c.get("url", "")
    ]
    assert (
        len(display_next_calls) > 0
    ), f"Display next should fire a fetch request, got calls: {calls}"

    rc.assert_no_errors(str(tmp_path), "display_next_request")


def test_display_next_no_js_errors(
    live_server, device_config_dev, browser_page, tmp_path
):
    prepare_playlist(device_config_dev)
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/")

    page.evaluate("""() => {
        const origFetch = window.fetch;
        window.fetch = function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : args[0].url;
            if (url.includes('display-next') || url.includes('display_next')) {
                return Promise.resolve(new Response(JSON.stringify({status: 'success'}), {
                    status: 200,
                    headers: {'Content-Type': 'application/json'}
                }));
            }
            return origFetch.apply(this, args);
        };
        window.location.reload = function() {};
    }""")

    display_next = page.locator("#displayNextBtn, button:has-text('Display next')")
    display_next.first.wait_for(state="visible", timeout=5000)
    display_next.first.click()
    page.wait_for_timeout(1500)

    rc.assert_no_errors(str(tmp_path), "display_next_no_errors")


def test_quick_switch_sends_playlist_request(
    live_server, device_config_dev, browser_page, tmp_path
):
    prepare_playlist(device_config_dev)
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Focus"):
        pm.add_playlist("Focus", "00:00", "24:00")
    focus = pm.get_playlist("Focus")
    if focus and not focus.plugins:
        focus.add_plugin(
            {
                "plugin_id": "weather",
                "name": "Focus Weather",
                "plugin_settings": {},
                "refresh": {"interval": 300},
            }
        )
    device_config_dev.write_config()

    page = browser_page
    rc = navigate_and_wait(page, live_server, "/")

    page.evaluate("""() => {
        const origFetch = window.fetch;
        window.__fetchCalls = [];
        window.fetch = function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : args[0].url;
            const opts = args[1] || {};
            window.__fetchCalls.push({
                url,
                method: opts.method || 'GET',
                body: opts.body || null,
            });
            if (url.includes('display_next_in_playlist')) {
                return Promise.resolve(new Response(JSON.stringify({
                    success: true,
                    message: 'Displayed next instance',
                    playlist: 'Focus'
                }), {
                    status: 200,
                    headers: {'Content-Type': 'application/json'}
                }));
            }
            if (url.includes('/refresh-info') || url.includes('/refresh_info')) {
                return Promise.resolve(new Response(JSON.stringify({
                    playlist: 'Focus',
                    plugin_id: 'weather',
                    plugin_display_name: 'Weather',
                    refresh_time: '2025-01-01T08:00:00+00:00'
                }), {
                    status: 200,
                    headers: {'Content-Type': 'application/json'}
                }));
            }
            if (url.includes('/next-up')) {
                return Promise.resolve(new Response(JSON.stringify({
                    playlist: 'Focus',
                    plugin_id: 'clock',
                    plugin_display_name: 'Clock'
                }), {
                    status: 200,
                    headers: {'Content-Type': 'application/json'}
                }));
            }
            return origFetch.apply(this, args);
        };
    }""")

    switch_btn = page.locator(
        'button[data-quick-switch-button][data-playlist-name="Focus"]'
    )
    switch_btn.wait_for(state="visible", timeout=5000)
    switch_btn.click()

    # Wait for the observable condition — the fetch call we expect to land —
    # instead of a fixed 1s sleep that can race on slow CI.
    page.wait_for_function(
        """() => (window.__fetchCalls || []).some(
            c => (c.url || '').includes('display_next_in_playlist')
        )""",
        timeout=5000,
    )

    calls = page.evaluate("() => window.__fetchCalls || []")
    quick_switch_calls = [
        c for c in calls if "display_next_in_playlist" in c.get("url", "")
    ]
    assert (
        quick_switch_calls
    ), f"Quick switch should POST to display_next_in_playlist, got: {calls}"
    assert quick_switch_calls[0].get("method") == "POST"
    assert '"playlist_name":"Focus"' in (quick_switch_calls[0].get("body") or "")

    focus_row = page.locator('[data-quick-switch-row][data-playlist-name="Focus"]')
    assert "is-active" in (focus_row.first.get_attribute("class") or "")

    rc.assert_no_errors(str(tmp_path), "dashboard_quick_switch_request")


def test_refresh_cell_shows_forward_looking_eta(
    live_server, device_config_dev, browser_page, tmp_path
):
    prepare_playlist(device_config_dev)
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/")

    page.evaluate("""() => {
        const fixedNow = new Date('2025-01-01T07:57:00+00:00').getTime();
        Date.now = () => fixedNow;

        const origFetch = window.fetch;
        window.fetch = function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : args[0].url;
            if (url.includes('/refresh-info') || url.includes('/refresh_info')) {
                return Promise.resolve(new Response(JSON.stringify({
                    playlist: 'Default',
                    plugin_id: 'clock',
                    plugin_display_name: 'Clock',
                    refresh_time: '2025-01-01T07:55:00+00:00',
                    cycle_minutes: 5,
                    next_refresh_time: '2025-01-01T08:00:00+00:00',
                    next_refresh_meta: 'ETA 8:00 AM · Every 5 min · auto'
                }), {
                    status: 200,
                    headers: {'Content-Type': 'application/json'}
                }));
            }
            if (url.includes('/next-up')) {
                return Promise.resolve(new Response(JSON.stringify({
                    playlist: 'Default',
                    plugin_id: 'weather',
                    plugin_display_name: 'Weather'
                }), {
                    status: 200,
                    headers: {'Content-Type': 'application/json'}
                }));
            }
            return origFetch.apply(this, args);
        };
    }""")

    page.locator("#dashboardRefreshBtn").click()

    # Wait for the hero refresh cell to reflect the stubbed ETA instead of
    # polling after a fixed 500ms. The mocked fetch resolves synchronously
    # but the DOM update is scheduled via a rAF.
    page.locator("#heroRefreshValue").wait_for(state="visible", timeout=5000)
    page.wait_for_function(
        "() => document.getElementById('heroRefreshValue')?.textContent === 'in 3m'",
        timeout=5000,
    )

    assert page.locator("#heroRefreshValue").text_content() == "in 3m"
    refresh_meta = page.locator("#heroRefreshMeta").text_content()
    assert "ETA 8:00 AM" in refresh_meta
    assert "Every 5 min" in refresh_meta

    rc.assert_no_errors(str(tmp_path), "dashboard_refresh_eta")
