"""Regression tests for JTN-633.

Clicking "Add to Playlist" on a DRAFT plugin page (no saved settings yet)
must either open the scheduling modal or surface a clear message — never
fail silently.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


def _render_clock_draft(client):
    """Return the raw HTML for `/plugin/clock` in DRAFT state."""
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_draft_add_to_playlist_button_renders_with_open_modal_attr(client):
    """DRAFT page must render an Add-to-Playlist trigger that targets the modal."""
    html = _render_clock_draft(client)
    # DRAFT chip present
    assert "Draft" in html
    # Button exposes data-open-modal so a click is never silently absorbed. JTN-633.
    assert 'data-open-modal="scheduleModal"' in html
    # DRAFT-state marker is present so JS can attach the defensive handler.
    assert 'data-plugin-draft="true"' in html
    # The modal target markup exists
    assert 'id="scheduleModal"' in html
    # Help text explains that current settings will be captured.
    assert "current settings will be captured" in html


def test_draft_add_to_playlist_button_opens_modal_with_real_handlers(client):
    """Real plugin_page.js handlers must open the modal when the button is clicked.

    The previous test harness injected its own listeners. This test instead
    wires up the real plugin_page.js module so we catch regressions where the
    production click handler silently no-ops.
    """
    pytest.importorskip("playwright.sync_api", reason="playwright not available")
    html = _render_clock_draft(client)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html)

        # Load supporting scripts the real page would load.
        for path in (
            "src/static/scripts/ui_helpers.js",
            "src/static/scripts/response_modal.js",
            "src/static/scripts/form_validator.js",
            "src/static/scripts/plugin_form.js",
            "src/static/scripts/plugin_page.js",
        ):
            with open(path, encoding="utf-8") as f:
                page.add_script_tag(content=f.read())

        # Initialise plugin page with a minimal boot config matching DRAFT state.
        page.evaluate("""
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
            window.fetch = () => Promise.resolve(new Response("{}", {status: 200, headers: {"Content-Type": "application/json"}}));
            window.InkyPiPluginPage.create(window.__INKYPI_PLUGIN_BOOT__).init();
            """)

        # Click the DRAFT-state "Add to Playlist" button.
        page.click('button[data-open-modal="scheduleModal"]')

        # Modal must become visible (display:flex via openModal) — not silently no-op.
        page.wait_for_selector("#scheduleModal", state="visible", timeout=2000)
        is_visible = page.evaluate(
            "() => { const m = document.getElementById('scheduleModal'); return !!m && m.classList.contains('is-open') && m.style.display === 'flex'; }"
        )
        assert (
            is_visible
        ), "scheduleModal did not open when Add to Playlist was clicked in DRAFT state"

        browser.close()


def test_draft_add_to_playlist_click_surfaces_failure_if_modal_missing(client):
    """If the scheduling modal is ever removed, the click must surface a visible
    error — never silently no-op. JTN-633 defensive path."""
    pytest.importorskip("playwright.sync_api", reason="playwright not available")
    html = _render_clock_draft(client)

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
            "src/static/scripts/plugin_page.js",
        ):
            with open(path, encoding="utf-8") as f:
                page.add_script_tag(content=f.read())

        page.evaluate("""
            window.__INKYPI_PLUGIN_BOOT__ = {
                deviceFrameUrl: "", displayInstancePayload: {playlist_name: "", plugin_id: "clock", plugin_instance: ""},
                displayInstanceUrl: "/display_plugin_instance", instanceImageUrl: null, lastRefresh: "",
                latestPluginImageUrl: "/plugin/clock/latest.png", loadPluginSettings: false,
                pluginId: "clock", pluginSettings: {}, previewUrl: "/preview_image",
                progressContext: {page: "plugin", pluginId: "clock", instance: null},
                refreshInfoUrl: "/refresh_info", resolution: [800, 480], styleSettings: false,
                urls: {add_to_playlist: "/add_plugin", save_settings: "/save_plugin_settings",
                       update_instance: "/update_plugin_instance", update_now: "/update_now"}
            };
            window.fetch = () => Promise.resolve(new Response("{}", {status: 200, headers: {"Content-Type": "application/json"}}));
            // Simulate the scheduleModal missing from the DOM to exercise the fallback.
            document.getElementById('scheduleModal')?.remove();
            window.InkyPiPluginPage.create(window.__INKYPI_PLUGIN_BOOT__).init();
            """)

        page.click('button[data-plugin-draft="true"]')
        page.wait_for_timeout(400)

        # A visible toast or response modal must surface actionable feedback —
        # not a silent no-op. JTN-633.
        feedback = page.evaluate("""() => {
                const toast = document.querySelector('.toast-container .toast');
                if (toast) return toast.textContent || '';
                const m = document.getElementById('responseModal');
                return m ? (m.textContent || '') : '';
            }""")
        assert (
            "Add to Playlist" in feedback or "refresh the page" in feedback
        ), f"Expected visible failure feedback, got: {feedback!r}"

        browser.close()
