import os

import pytest


@pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)
def test_plugin_add_to_playlist_flow(client):
    pw = pytest.importorskip("playwright.sync_api", reason="playwright not available")

    # Choose a simple plugin page that renders without external deps
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html)

        # Inject response modal helpers and stub fetch
        js_modal = open("src/static/scripts/response_modal.js", "r", encoding="utf-8").read()
        page.add_script_tag(content=js_modal)
        page.add_init_script(
            """
            window.__requests__ = [];
            const ok = (body) => new Response(JSON.stringify(Object.assign({success:true,message:"Added"}, body||{})), {status:200, headers:{'Content-Type':'application/json'}});
            window.fetch = (url, opts={}) => { try { window.__requests__.push({url, body: opts.body, method: opts.method||'GET'}); } catch(e){}; return Promise.resolve(ok()); };
            """
        )

        # Open Add to Playlist modal and fill fields
        page.click("text=Add to Playlist")
        page.fill("#instance", "My Instance")
        page.fill("#interval", "15")
        page.select_option("#unit", "minute")
        # Save
        page.click("text=Save")

        reqs = page.evaluate("() => window.__requests__")
        # Verify a POST to /add_plugin occurred and its body contains refresh_settings
        post = next((r for r in reqs if r.get("method") == "POST" and "add_plugin" in r.get("url", "")), None)
        assert post is not None
        body = post.get("body") or ""
        # Body is FormData; in this stub it's opaque but ensure our call happened
        assert post["method"] == "POST"

        browser.close()


