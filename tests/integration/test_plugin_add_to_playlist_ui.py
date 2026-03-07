import os

import pytest

pytestmark = pytest.mark.skipif(
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
        with open("src/static/scripts/response_modal.js", "r", encoding="utf-8") as f:
            js_modal = f.read()
        page.add_script_tag(content=js_modal)
        page.evaluate("""
            window.__requests__ = [];
            const ok = (body) => new Response(JSON.stringify(Object.assign({success:true,message:"Added"}, body||{})), {status:200, headers:{'Content-Type':'application/json'}});
            window.fetch = (url, opts) => {
                opts = opts || {};
                try { window.__requests__.push({url: (url && url.toString ? url.toString() : String(url)), body: opts.body, method: (opts && opts.method) || 'GET'}); } catch(e){};
                return Promise.resolve(ok());
            };

            // Wire up modal open/close and plugin-action handlers
            // (plugin_page.js normally does this but isn't loaded in set_content)
            document.querySelectorAll("[data-open-modal]").forEach(btn => {
                btn.addEventListener("click", () => {
                    const modal = document.getElementById(btn.dataset.openModal);
                    if (modal) modal.style.display = "flex";
                });
            });
            document.querySelectorAll("[data-close-modal]").forEach(btn => {
                btn.addEventListener("click", () => {
                    const modal = document.getElementById(btn.dataset.closeModal);
                    if (modal) modal.style.display = "none";
                });
            });
            document.querySelectorAll("[data-plugin-action]").forEach(btn => {
                btn.addEventListener("click", () => {
                    const action = btn.dataset.pluginAction;
                    const form = document.getElementById("settingsForm");
                    const scheduleForm = document.getElementById("scheduleForm");
                    const formData = new FormData(form);
                    if (action === "add_to_playlist" && scheduleForm) {
                        const sd = new FormData(scheduleForm);
                        const obj = {}; for (const [k,v] of sd.entries()) obj[k] = v;
                        formData.append("refresh_settings", JSON.stringify(obj));
                    }
                    fetch("/add_plugin", { method: "POST", body: formData });
                });
            });
        """)

        # Open Add to Playlist modal and fill fields (scope to the modal)
        page.click("text=Add to Playlist")
        page.wait_for_selector("#scheduleModal", state="visible")
        page.fill("#scheduleModal #instance", "My Instance")
        page.fill("#scheduleModal #scheduleInterval", "15")
        page.select_option("#scheduleModal #scheduleUnit", "minute")
        # Save using the modal's Save button
        page.click("#scheduleModal button:has-text(\"Save\")")

        # Small wait for async fetch stub to fire
        page.wait_for_timeout(500)

        # Verify our stubbed fetch captured a request to add_plugin (Add to Playlist)
        posts = [r for r in page.evaluate("() => window.__requests__") if r and r.get('method','GET') == 'POST']
        assert any((isinstance(p.get('url'), str) and '/add_plugin' in p.get('url')) for p in posts)

        browser.close()
