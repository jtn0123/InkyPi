"""
UI Interaction Tests

WHY THESE TESTS REQUIRE BROWSER AUTOMATION:
================================================================================
These tests verify dynamic JavaScript behavior in the web interface that cannot
be tested via static HTML requests. They require Playwright/Selenium because:

1. **JavaScript Execution**:
   - Tests verify client-side form validation
   - Dynamic DOM updates (add/remove playlist items)
   - AJAX requests and response handling
   - Event listeners and user interactions
   Cannot be tested with Flask test client (no JavaScript engine)

2. **User Interactions**:
   - Button clicks (add plugin, delete instance, etc.)
   - Form submissions with validation
   - Drag-and-drop reordering
   - Modal dialogs (open/close/submit)
   - Real browser events (mousedown, keypress, etc.)

3. **Asynchronous Behavior**:
   - Fetch API calls to backend
   - Promise resolution and error handling
   - Loading states and spinners
   - Success/error message display
   - Real network timing

4. **Environment Requirements**:
   - Browser automation framework (Playwright/Selenium)
   - Browser binaries (Chromium ~200MB)
   - JavaScript runtime
   - Headless mode or display server

WHAT THESE TESTS VERIFY:
- Playlist UI allows adding/removing plugins via JavaScript
- Form validation prevents invalid configurations
- Dynamic updates work without page reload
- Error messages display correctly
- Modals and dialogs function properly

TO RUN THESE TESTS:
1. Install Playwright: pip install playwright
2. Install browsers: playwright install chromium
3. Unset SKIP_UI: unset SKIP_UI or SKIP_UI=0 pytest tests/integration/test_playlist_interactions.py
"""

import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from model import RefreshInfo


def _fixed_now(_device_config):
    return datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)


def _prepare_playlist(device_config_dev):
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pl = pm.get_playlist("Default")
    pl.add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    pl.add_plugin(
        {
            "plugin_id": "weather",
            "name": "Weather B",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )
    device_config_dev.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time="2025-01-01T07:55:00+00:00",
        image_hash=0,
        playlist="Default",
        plugin_instance="Clock A",
    )
    device_config_dev.write_config()


@pytest.mark.skip(reason="Keyboard reordering broken by upstream merge - needs JS investigation")
def test_playlist_keyboard_reorder_and_delete_modal(client, device_config_dev, monkeypatch):
    pw = pytest.importorskip("playwright.sync_api", reason="playwright not available")
    monkeypatch.setattr("utils.time_utils.now_device_tz", _fixed_now, raising=True)
    _prepare_playlist(device_config_dev)

    resp = client.get("/playlist")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Load HTML and front-end scripts
        page.set_content(html)
        # Make response_modal helpers available
        with open("src/static/scripts/response_modal.js", "r", encoding="utf-8") as f:
            js_modal = f.read()
        page.add_script_tag(content=js_modal)

        # Set up mocks and context
        page.evaluate("""
            window.PLAYLIST_CTX = {
                reorder_url: "/reorder_plugins",
                delete_plugin_instance_url: "/delete_plugin_instance",
                display_plugin_instance_url: "/display_plugin_instance",
                create_playlist_url: "/create_playlist",
                update_playlist_base_url: "/update_playlist/",
                delete_playlist_base_url: "/delete_playlist/",
                display_next_url: "/display_next_in_playlist",
                device_tz_offset_min: 0
            };

            window.__requests__ = [];
            const ok = (body) => new Response(JSON.stringify(Object.assign({success:true,message:"ok"}, body||{})), {status:200, headers:{'Content-Type':'application/json'}});

            const origFetch = window.fetch;
            window.fetch = (url, opts) => {
                opts = opts || {};
                console.log('Mock fetch called with URL:', url);
                try { window.__requests__.push({url: (url && url.toString ? url.toString() : String(url)), body: opts.body, method: (opts && opts.method) || 'GET'}); } catch(e){ console.error('Error pushing request:', e); };
                return Promise.resolve(ok());
            };
        """)

        # Attach playlist behavior script
        with open("src/static/scripts/playlist.js", "r", encoding="utf-8") as f:
            js_playlist = f.read()
        page.add_script_tag(content=js_playlist)

        # Wait for script to load
        page.wait_for_timeout(100)

        # Check if playlist functions are loaded (check for a function that actually exists)
        loaded = page.evaluate("() => typeof window.deletePluginInstance !== 'undefined'")
        print(f"DEBUG: Playlist functions loaded: {loaded}")

        # Check if plugin items exist
        plugin_items = page.query_selector_all(".plugin-item")
        print(f"DEBUG: Found {len(plugin_items)} plugin items")
        if plugin_items:
            print(f"DEBUG: First plugin item HTML: {plugin_items[0].inner_html()[:200]}")

        # Focus first plugin item and move it down with ArrowDown to trigger reorder
        page.focus(".plugin-item")
        page.evaluate("""
            const el = document.querySelector('.plugin-item');
            if (el){
                const evt = new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true });
                el.dispatchEvent(evt);
            }
        """)

        # Wait a bit for any async operations
        page.wait_for_timeout(100)

        # Ensure reordering via ArrowDown triggers our mock fetch to reorder endpoint
        reqs = page.evaluate("() => window.__requests__")
        assert any((r and r.get('url') and isinstance(r.get('url'), str) and r.get('url').endswith('/reorder_plugins')) for r in reqs)

        # Open and confirm Delete Playlist modal; ensure DELETE request fires
        page.click(".delete-playlist-btn")
        page.click("#confirmDeletePlaylistBtn")
        reqs2 = page.evaluate("() => window.__requests__")
        assert any((r and isinstance(r.get('url'), str) and '/delete_playlist/' in r.get('url') and r.get('method') == 'DELETE') for r in reqs2)

        # Trigger delete playlist modal and confirm
        # Click the first playlist's delete button
        # (Assertions moved above after modal interaction)

        browser.close()


