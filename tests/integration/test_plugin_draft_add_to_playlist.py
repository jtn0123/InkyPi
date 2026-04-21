"""Regression tests for JTN-633.

Clicking "Add to Playlist" on a DRAFT plugin page (no saved settings yet)
must either reveal the inline Schedule tab or surface a clear message —
never fail silently.
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


def test_draft_add_to_playlist_button_renders_with_schedule_target(client):
    """DRAFT page must render an Add-to-Playlist trigger that targets Schedule."""
    html = _render_clock_draft(client)
    # DRAFT chip present
    assert "Draft" in html
    # Button exposes a Schedule target so a click is never silently absorbed. JTN-633.
    assert 'data-plugin-subtab-target="schedule"' in html
    # DRAFT-state marker is present so JS can attach the defensive handler.
    assert 'data-plugin-draft="true"' in html
    # The inline schedule UI exists.
    assert 'id="pluginSchedulePanel"' in html
    assert 'id="scheduleForm"' in html
    # Help text explains that current settings seed the playlist entry.
    assert "current settings" in html


def test_draft_add_to_playlist_button_reveals_schedule_tab_with_real_handlers(client):
    """Real plugin_page.js handlers must reveal Schedule when the button is clicked.

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
        # Target the DRAFT-marked Add-to-Playlist trigger specifically. The
        # Schedule subtab button itself also matches
        # `[data-plugin-subtab-target="schedule"]`, so without the draft
        # marker this test could pass without exercising the DRAFT click path.
        page.click(
            'button[data-plugin-draft="true"][data-plugin-subtab-target="schedule"]'
        )

        # Poll for the observable schedule-active state instead of sleeping a
        # fixed 250ms. The real click handler reveals the schedule panel via a
        # rAF + focus call, which can be slower on CI than on dev machines.
        # wait_for_function raises TimeoutError if the predicate never becomes
        # true, which is the only failure mode we care about here — a
        # follow-up page.evaluate would just re-run the same predicate
        # (CodeRabbit review, PR #570).
        page.wait_for_function(
            """() => {
                const tab = document.querySelector('[data-plugin-subtab="schedule"]');
                const panel = document.getElementById('pluginSchedulePanel');
                const instance = document.getElementById('instance');
                return !!tab && tab.getAttribute('aria-selected') === 'true'
                    && !!panel && panel.hidden === false
                    && !!instance && document.activeElement === instance;
            }""",
            timeout=5000,
        )

        browser.close()


def test_draft_add_to_playlist_click_surfaces_failure_if_schedule_panel_missing(client):
    """If the inline scheduling panel is ever removed, the click must surface a
    visible error — never silently no-op. JTN-633 defensive path."""
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
            // Simulate the schedule panel missing from the DOM to exercise the fallback.
            document.getElementById('pluginSchedulePanel')?.remove();
            window.InkyPiPluginPage.create(window.__INKYPI_PLUGIN_BOOT__).init();
            """)

        # Target the DRAFT-marked Add-to-Playlist trigger specifically. The
        # Schedule subtab button itself also matches
        # `[data-plugin-subtab-target="schedule"]`, so without the draft
        # marker this test could pass without exercising the DRAFT click path.
        page.click(
            'button[data-plugin-draft="true"][data-plugin-subtab-target="schedule"]'
        )

        # Poll for the observable failure feedback rather than sleeping a
        # fixed 400ms. The fallback path renders either a toast or the
        # response modal — wait for either to surface the expected copy.
        page.wait_for_function(
            """() => {
                const toast = document.querySelector('.toast-container .toast');
                const toastText = toast ? (toast.textContent || '') : '';
                const modal = document.getElementById('responseModal');
                const modalText = modal ? (modal.textContent || '') : '';
                const combined = toastText + '\\n' + modalText;
                return combined.includes('scheduling controls')
                    || combined.includes('refresh the page');
            }""",
            timeout=5000,
        )

        # A visible toast or response modal must surface actionable feedback —
        # not a silent no-op. JTN-633.
        feedback = page.evaluate("""() => {
                const toast = document.querySelector('.toast-container .toast');
                if (toast) return toast.textContent || '';
                const m = document.getElementById('responseModal');
                return m ? (m.textContent || '') : '';
            }""")
        assert (
            "scheduling controls" in feedback or "refresh the page" in feedback
        ), f"Expected visible failure feedback, got: {feedback!r}"

        browser.close()
