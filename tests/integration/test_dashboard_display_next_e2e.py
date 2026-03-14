# pyright: reportMissingImports=false
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import navigate_and_wait, prepare_playlist


def test_display_next_button_exists(live_server, device_config_dev, browser_page, tmp_path):
    prepare_playlist(device_config_dev)
    page = browser_page
    rc = navigate_and_wait(page, live_server, "/")

    display_next = page.locator("#displayNextBtn, button:has-text('Display Next')")
    display_next.first.wait_for(state="visible", timeout=5000)
    assert display_next.first.is_visible(), "Display Next button should be visible"

    rc.assert_no_errors(str(tmp_path), "display_next_exists")


def test_display_next_sends_request(live_server, device_config_dev, browser_page, tmp_path):
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

    display_next = page.locator("#displayNextBtn, button:has-text('Display Next')")
    display_next.first.wait_for(state="visible", timeout=5000)
    display_next.first.click()
    page.wait_for_timeout(1000)

    calls = page.evaluate("() => window.__fetchCalls || []")
    display_next_calls = [
        c for c in calls
        if "display-next" in c.get("url", "") or "display_next" in c.get("url", "")
    ]
    assert len(display_next_calls) > 0, (
        f"Display Next should fire a fetch request, got calls: {calls}"
    )

    rc.assert_no_errors(str(tmp_path), "display_next_request")


def test_display_next_no_js_errors(live_server, device_config_dev, browser_page, tmp_path):
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

    display_next = page.locator("#displayNextBtn, button:has-text('Display Next')")
    display_next.first.wait_for(state="visible", timeout=5000)
    display_next.first.click()
    page.wait_for_timeout(1500)

    rc.assert_no_errors(str(tmp_path), "display_next_no_errors")
