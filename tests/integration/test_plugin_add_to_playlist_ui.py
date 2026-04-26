import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


def test_plugin_add_to_playlist_flow(client):
    pytest.importorskip("playwright.sync_api", reason="playwright not available")

    # Choose a simple plugin page that renders without external deps
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html)

        for path in (
            "src/static/scripts/ui_helpers.js",
            "src/static/scripts/response_modal.js",
            "src/static/scripts/form_validator.js",
            "src/static/scripts/plugin_form.js",
            "src/static/scripts/plugin_page/shared.js",
            "src/static/scripts/plugin_page/progress.js",
            "src/static/scripts/plugin_page.js",
        ):
            with open(path, encoding="utf-8") as f:
                page.add_script_tag(content=f.read())

        page.evaluate("""
            window.__requests__ = [];
            const ok = (body) => new Response(JSON.stringify(Object.assign({success:true,message:"Added"}, body||{})), {status:200, headers:{'Content-Type':'application/json'}});
            window.fetch = (url, opts) => {
                opts = opts || {};
                try { window.__requests__.push({url: (url && url.toString ? url.toString() : String(url)), body: opts.body, method: (opts && opts.method) || 'GET'}); } catch(e){};
                return Promise.resolve(ok());
            };
            window.__INKYPI_PLUGIN_BOOT__ = {
                deviceFrameUrl: "",
                displayInstancePayload: {playlist_name: "", plugin_id: "clock", plugin_instance: ""},
                displayInstanceUrl: "/display_plugin_instance",
                instanceImageUrl: null,
                lastRefresh: "",
                latestPluginImageUrl: "/plugin/clock/latest.png",
                loadPluginSettings: false,
                pluginId: "clock",
                pluginSettings: {},
                previewUrl: "/preview_image",
                progressContext: {page: "plugin", pluginId: "clock", instance: null},
                refreshInfoUrl: "/refresh_info",
                resolution: [800, 480],
                styleSettings: false,
                urls: {
                    add_to_playlist: "/add_plugin",
                    save_settings: "/save_plugin_settings",
                    update_instance: "/update_plugin_instance",
                    update_now: "/update_now"
                }
            };
            window.InkyPiPluginPage.create(window.__INKYPI_PLUGIN_BOOT__).init();
        """)

        page.click('button[data-plugin-subtab-target="schedule"]')
        page.wait_for_timeout(200)
        page.fill("#instance", "My Instance")
        page.fill("#scheduleInterval", "15")
        page.select_option("#scheduleUnit", "minute")
        page.click('button[data-plugin-action="add_to_playlist"]')

        # Small wait for async fetch stub to fire
        page.wait_for_timeout(500)

        # Verify our stubbed fetch captured a request to add_plugin (Add to Playlist)
        posts = [
            r
            for r in page.evaluate("() => window.__requests__")
            if r and r.get("method", "GET") == "POST"
        ]
        assert any(
            (isinstance(p.get("url"), str) and "/add_plugin" in p.get("url"))
            for p in posts
        )

        browser.close()
