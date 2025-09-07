import os
from datetime import datetime, timezone

import pytest

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


@pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)
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
        js_modal = open("src/static/scripts/response_modal.js", "r", encoding="utf-8").read()
        page.add_script_tag(content=js_modal)
        # Provide PLAYLIST_CTX minimal URLs (won't be used due to fetch stub) and tz offset
        page.add_init_script(
            """
            window.PLAYLIST_CTX = { reorder_url: "/reorder_plugins", delete_plugin_instance_url: "/delete_plugin_instance", display_plugin_instance_url: "/display_plugin_instance", create_playlist_url: "/create_playlist", update_playlist_base_url: "/update_playlist/", delete_playlist_base_url: "/delete_playlist/", display_next_url: "/display_next_in_playlist", device_tz_offset_min: 0 };
            """
        )
        # Stub fetch to capture calls and return success
        page.add_init_script(
            """
            window.__requests__ = [];
            const ok = (body) => new Response(JSON.stringify(Object.assign({success:true,message:"ok"}, body||{})), {status:200, headers:{'Content-Type':'application/json'}});
            const origFetch = window.fetch;
            window.fetch = (url, opts={}) => { try { window.__requests__.push({url, body: opts.body}); } catch(e){}; return Promise.resolve(ok()); };
            """
        )
        # Attach playlist behavior script
        js_playlist = open("src/static/scripts/playlist.js", "r", encoding="utf-8").read()
        page.add_script_tag(content=js_playlist)

        # Focus first plugin item and move it down with ArrowDown to trigger reorder
        page.focus(".plugin-item")
        page.keyboard.press("ArrowDown")

        # Ensure reorder fetch was called with expected endpoint
        reqs = page.evaluate("() => window.__requests__")
        assert any("reorder_plugins" in r.get("url", "") for r in reqs)

        # Trigger delete playlist modal and confirm
        # Click the first playlist's delete button
        page.click(".delete-playlist-btn")
        # Confirm delete in modal
        page.click("#confirmDeletePlaylistBtn")
        # Verify delete endpoint was called
        reqs2 = page.evaluate("() => window.__requests__")
        assert any("/delete_playlist/" in r.get("url", "") for r in reqs2)

        browser.close()


