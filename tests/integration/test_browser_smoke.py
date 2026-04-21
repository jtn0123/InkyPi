# pyright: reportMissingImports=false
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image
from scripts.ui_audit import TOP_LEVEL_ROUTES, discover_plugin_ids

REQUIRE_BROWSER_SMOKE = os.getenv("REQUIRE_BROWSER_SMOKE", "").lower() in ("1", "true")
pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true") and not REQUIRE_BROWSER_SMOKE,
    reason="UI interactions skipped by env",
)


TOP_LEVEL_MARKERS = {
    "home": "#previewImage",
    "settings": ".settings-console-layout",
    "history": "#storage-block",
    "playlist": "#newPlaylistBtn",
    "api_keys": "#saveApiKeysBtn",
}

TOP_LEVEL_PRIMARY_ACTIONS = {
    "home": "#themeToggle",
    "settings": "#saveSettingsBtn",
    "history": "#historyRefreshBtn",
    "playlist": "#newPlaylistBtn",
    "api_keys": "#saveApiKeysBtn",
}

MOBILE_VIEWPORTS = (
    {"width": 360, "height": 800, "label": "phone_360"},
    {"width": 390, "height": 844, "label": "phone_390"},
)

MOBILE_PLUGIN_IDS = ("calendar", "weather", "todo_list", "image_upload", "ai_text")

PLUGIN_IDS = discover_plugin_ids(Path(__file__).resolve().parents[2])
CRITICAL_RESPONSE_TYPES = {"document", "script", "stylesheet", "xhr", "fetch"}


def _slug(value: str) -> str:
    return value.replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "_")


def _leaflet_stub_js() -> str:
    return """
      (() => {
        function chain() { return this; }
        function markerFactory() {
          return {
            addTo: chain,
            bindPopup: chain,
            openPopup: chain,
            setLatLng: chain,
          };
        }
        window.L = {
          map() {
            return {
              setView: chain,
              on: chain,
              off: chain,
              fitBounds: chain,
              addLayer: chain,
              removeLayer: chain,
              invalidateSize: chain,
              closePopup: chain,
            };
          },
          tileLayer() {
            return { addTo: chain };
          },
          marker: markerFactory,
          latLng(lat, lng) {
            return { lat, lng };
          },
        };
      })();
    """


def _attach_runtime_collectors(page, base_url: str):
    runtime = {
        "console_errors": [],
        "page_errors": [],
        "request_failures": [],
        "response_failures": [],
    }

    def handle_console(msg):
        if msg.type != "error":
            return
        text = msg.text
        if "integrity" in text and "leaflet" in text.lower():
            return
        runtime["console_errors"].append(text)

    page.route(
        "**/static/vendor/leaflet/leaflet.css",
        lambda route: route.fulfill(
            status=200,
            content_type="text/css",
            body="",
        ),
    )
    page.route(
        "**/static/vendor/leaflet/leaflet.js",
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body=_leaflet_stub_js(),
        ),
    )

    page.on("pageerror", lambda exc: runtime["page_errors"].append(str(exc)))
    page.on("console", handle_console)
    page.on(
        "requestfailed",
        lambda request: (
            runtime["request_failures"].append(
                {
                    "url": request.url,
                    "resource_type": request.resource_type,
                    "failure": request.failure or "",
                }
            )
            if request.url.startswith(base_url)
            and request.resource_type in CRITICAL_RESPONSE_TYPES
            else None
        ),
    )
    page.on(
        "response",
        lambda response: (
            runtime["response_failures"].append(
                {
                    "url": response.url,
                    "status": response.status,
                    "resource_type": response.request.resource_type,
                }
            )
            if response.url.startswith(base_url)
            and response.status >= 400
            and response.request.resource_type in CRITICAL_RESPONSE_TYPES
            else None
        ),
    )
    return runtime


def _assert_clean_runtime(page, runtime: dict, screenshot_dir: Path, name: str):
    failures = []

    if runtime["page_errors"]:
        failures.append(f"pageerror: {runtime['page_errors'][:5]}")
    if runtime["console_errors"]:
        failures.append(f"console error: {runtime['console_errors'][:5]}")
    if runtime["request_failures"]:
        failures.append(f"request failures: {runtime['request_failures'][:5]}")
    if runtime["response_failures"]:
        failures.append(f"response failures: {runtime['response_failures'][:5]}")

    if failures:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshot_dir / f"{_slug(name)}.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        pytest.fail("\n".join(failures + [f"screenshot: {screenshot_path}"]))


def _assert_skip_link_present(page):
    """Skip links are an accessibility requirement — verify they exist."""
    html = page.content()
    assert "skip-link" in html or "Skip to main content" in html


def _assert_plugin_page_ready(page, plugin_id: str):
    page.wait_for_selector("#settingsForm", state="attached")
    interactive_fields = page.locator(
        "#settingsForm input, #settingsForm select, #settingsForm textarea"
    )
    assert interactive_fields.count() > 0

    if plugin_id == "calendar":
        page.wait_for_selector("[name='calendarURLs[]']", state="attached")
        initial = page.locator("[name='calendarURLs[]']").count()
        assert initial > 0
    elif plugin_id == "weather":
        page.wait_for_selector("#openMap", state="attached")
        assert page.locator("#latitude").count() == 1
        assert page.locator("#longitude").count() == 1
    elif plugin_id == "todo_list":
        page.wait_for_selector("[name='list-title[]']", state="attached")
        assert page.locator("[name='list-title[]']").count() > 0
    elif plugin_id == "image_upload":
        page.wait_for_selector("#imageUpload", state="attached")
        assert page.locator("#fileNames").count() == 1


def _new_page(browser, viewport: dict, theme: str):
    page = browser.new_page(
        viewport={"width": viewport["width"], "height": viewport["height"]}
    )
    page.add_init_script(script=f"""
        (() => {{
            try {{
                localStorage.setItem("theme", {theme!r});
                localStorage.setItem("inkypi-theme", {theme!r});
            }} catch (e) {{}}
        }})();
        """)
    return page


def _assert_no_horizontal_overflow(page):
    widths = page.evaluate("""
        () => ({
            innerWidth: window.innerWidth,
            clientWidth: document.documentElement.clientWidth,
            scrollWidth: document.documentElement.scrollWidth,
        })
        """)
    assert widths["scrollWidth"] <= widths["clientWidth"] + 2, widths


def _assert_action_visible(page, selector: str):
    locator = page.locator(selector).first
    locator.scroll_into_view_if_needed()
    box = locator.bounding_box()
    viewport = page.viewport_size or {"width": 0, "height": 0}
    assert box is not None
    assert box["x"] >= -1
    assert box["x"] + box["width"] <= viewport["width"] + 1
    assert box["y"] + box["height"] <= viewport["height"] + 160


def _maybe_capture_baseline(page, screenshot_dir: Path, name: str):
    if os.getenv("CAPTURE_MOBILE_SCREENSHOTS", "").lower() not in ("1", "true"):
        return
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot_dir / f"{_slug(name)}.png"), full_page=True)


def _open_and_check(
    page, base_url: str, route_name: str, route_path: str, screenshot_dir: Path
):
    runtime = _attach_runtime_collectors(page, base_url)
    page.goto(f"{base_url}{route_path}", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    page.wait_for_timeout(500)
    _assert_skip_link_present(page)
    return runtime


def _artifact_dir(tmp_path: Path) -> Path:
    override = os.getenv("BROWSER_SMOKE_ARTIFACT_DIR")
    if override:
        return Path(override)
    return tmp_path / "browser_smoke_failures"


def _wait_for_toast_text(page, expected: str, timeout: int = 10000):
    page.wait_for_function(
        """(needle) => Array.from(document.querySelectorAll('.toast-content'))
            .some((el) => (el.textContent || '').includes(needle))
        """,
        arg=expected,
        timeout=timeout,
    )


def _open_settings_tab(page, tab_name: str):
    tab = page.locator(f'[data-settings-tab="{tab_name}"]').first
    tab.click()
    page.wait_for_function(
        """(tab) => {
          const panel = document.querySelector(`[data-settings-panel="${tab}"]`);
          return !!panel && panel.classList.contains("active");
        }""",
        arg=tab_name,
        timeout=8000,
    )


def _expand_settings_section(page, section_id: str):
    toggle = page.locator(f"{section_id} [data-collapsible-toggle]").first
    toggle.wait_for(state="attached", timeout=8000)
    if toggle.get_attribute("aria-expanded") != "true":
        toggle.click()
        page.wait_for_function(
            """(selector) => {
              const el = document.querySelector(selector);
              return !!el && el.getAttribute("aria-expanded") === "true";
            }""",
            arg=f"{section_id} [data-collapsible-toggle]",
            timeout=8000,
        )


def _seed_history_entries(history_dir: Path, count: int = 12):
    history_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for idx in range(count):
        name = f"display_20260101_120{idx:02d}.png"
        path = history_dir / name
        Image.new("RGB", (16, 16), "white").save(path)
        sidecar = {
            "refresh_type": "Playlist",
            "plugin_id": "clock",
            "playlist": "Default",
            "plugin_instance": f"Clock {idx + 1}",
        }
        (history_dir / name.replace(".png", ".json")).write_text(
            json.dumps(sidecar), encoding="utf-8"
        )
        names.append(name)
    return names


def test_top_level_tabs_boot_cleanly(live_server, tmp_path):
    from playwright.sync_api import sync_playwright

    screenshot_dir = _artifact_dir(tmp_path)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for route_name, route_path in TOP_LEVEL_ROUTES:
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                runtime = _open_and_check(
                    page, live_server, route_name, route_path, screenshot_dir
                )
                marker = TOP_LEVEL_MARKERS[route_name]
                page.wait_for_selector(marker, timeout=10000)
                if route_name == "settings":
                    page.wait_for_selector("#saveSettingsBtn")
                elif route_name == "playlist":
                    assert page.locator("#newPlaylistBtn").is_enabled()
                _assert_clean_runtime(page, runtime, screenshot_dir, route_name)
                page.close()
        finally:
            browser.close()


def test_jtn_730_settings_deep_high_risk_paths(live_server, tmp_path):
    """JTN-730: Exercise high-risk /settings interactions end-to-end."""
    from playwright.sync_api import sync_playwright

    screenshot_dir = _artifact_dir(tmp_path)
    import_payload = {
        "config": {
            "name": "JTN730 Imported Device",
            "orientation": "vertical",
            "timezone": "UTC",
            "time_format": "24h",
            "plugin_cycle_interval_seconds": 300,
        }
    }
    import_file = tmp_path / "jtn_730_import.json"
    import_file.write_text(json.dumps(import_payload), encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            runtime = _open_and_check(
                page,
                live_server,
                "jtn_730_settings_deep",
                "/settings",
                screenshot_dir,
            )
            page.wait_for_selector("#saveSettingsBtn", timeout=10000)

            # Save-path depth: dirty-state -> POST -> persisted value after reload.
            device_name = page.locator("#deviceName")
            original_name = device_name.input_value().strip() or "InkyPi"
            updated_name = f"{original_name}-JTN730"
            device_name.fill(updated_name)
            page.wait_for_function(
                "() => !document.getElementById('saveSettingsBtn').disabled",
                timeout=8000,
            )
            page.locator("#saveSettingsBtn").click()
            _wait_for_toast_text(page, "Saved settings.")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector("[data-page-shell]", timeout=10000)
            assert page.locator("#deviceName").input_value() == updated_name

            _open_settings_tab(page, "maintenance")
            # Backup & restore is now a flat section inside the maintenance
            # tab (no collapsible). Wait for visibility before interacting.
            page.wait_for_selector("#exportConfigBtn", state="visible", timeout=10000)

            # Backup & restore path: export feedback + file import round-trip.
            page.locator("#exportConfigBtn").click()
            _wait_for_toast_text(page, "Backup downloaded")

            page.set_input_files("#importFile", str(import_file))
            assert page.locator("#importConfigBtn").is_enabled()
            page.locator("#importConfigBtn").click()
            _wait_for_toast_text(page, "Import completed")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector("[data-page-shell]", timeout=10000)
            assert page.locator("#deviceName").input_value() == "JTN730 Imported Device"

            _open_settings_tab(page, "maintenance")

            # Diagnostics path: isolate/un-isolate round trip on a valid plugin.
            _expand_settings_section(page, "#section-observability")
            page.locator("#isolatePluginInput").fill("clock")
            page.locator("#isolatePluginBtn").click()
            _wait_for_toast_text(page, 'Plugin "clock" has been isolated.')
            page.locator("#unIsolatePluginBtn").click()
            _wait_for_toast_text(page, 'Plugin "clock" has been un-isolated.')

            # Device action safety gates: modal open/close + focus restore.
            # Reboot/shutdown now live on their own "Power" tab (matches
            # handoff design: Device / Scheduling / Image / Updates / Power).
            _open_settings_tab(page, "power")
            page.locator("#rebootBtn").click()
            page.wait_for_selector("#rebootConfirmModal", state="visible", timeout=8000)
            page.keyboard.press("Escape")
            page.wait_for_selector("#rebootConfirmModal", state="hidden", timeout=8000)
            assert page.evaluate(
                "document.activeElement && document.activeElement.id"
            ) == ("rebootBtn")

            page.locator("#shutdownBtn").click()
            page.wait_for_selector(
                "#shutdownConfirmModal", state="visible", timeout=8000
            )
            page.locator("#cancelShutdownBtn").click()
            page.wait_for_selector(
                "#shutdownConfirmModal", state="hidden", timeout=8000
            )

            _assert_clean_runtime(
                page, runtime, screenshot_dir, "jtn_730_settings_deep"
            )
        finally:
            browser.close()


def test_jtn_731_history_deep_high_risk_paths(live_server, tmp_path, device_config_dev):
    """JTN-731: Exercise high-risk /history actions and pagination end-to-end."""
    from playwright.sync_api import sync_playwright

    screenshot_dir = _artifact_dir(tmp_path)
    _seed_history_entries(Path(device_config_dev.history_image_dir), count=12)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            runtime = _open_and_check(
                page,
                live_server,
                "jtn_731_history_deep",
                "/history?per_page=10&page=1",
                screenshot_dir,
            )
            page.wait_for_selector("#history-grid-container", timeout=10000)
            assert "Page 1 of 2" in page.locator(".pagination-info").inner_text()

            # Pagination depth with HTMX history grid swaps.
            page.locator("a.btn", has_text="Next").click()
            page.wait_for_timeout(500)
            assert "Page 2 of 2" in page.locator(".pagination-info").inner_text()
            page.locator("a.btn", has_text="Previous").click()
            page.wait_for_timeout(500)
            assert "Page 1 of 2" in page.locator(".pagination-info").inner_text()

            # Redisplay path should complete and surface its success toast.
            page.locator('[data-history-action="display"]').first.click()
            _wait_for_toast_text(page, "Display updated")

            # Delete path: ESC cancel first (focus restore), then confirm delete.
            delete_btn = page.locator('[data-history-action="delete"]').first
            target_filename = delete_btn.get_attribute("data-filename")
            delete_btn.click()
            page.wait_for_selector("#deleteHistoryModal", state="visible", timeout=8000)
            page.keyboard.press("Escape")
            page.wait_for_selector("#deleteHistoryModal", state="hidden", timeout=8000)
            assert (
                page.evaluate(
                    "document.activeElement && document.activeElement.dataset.historyAction"
                )
                == "delete"
            )

            delete_btn = page.locator('[data-history-action="delete"]').first
            delete_btn.click()
            page.wait_for_selector("#deleteHistoryModal", state="visible", timeout=8000)
            page.locator("#confirmDeleteHistoryBtn").click()
            page.wait_for_selector("[data-page-shell]", timeout=10000)
            _wait_for_toast_text(page, "Deleted")
            assert not (
                Path(device_config_dev.history_image_dir) / target_filename
            ).exists()

            # Clear-all path: cancel once, then confirm and verify empty state.
            clear_btn = page.locator("#historyClearBtn")
            clear_btn.click()
            page.wait_for_selector("#clearHistoryModal", state="visible", timeout=8000)
            page.locator("#cancelClearHistoryBtn").click()
            page.wait_for_selector("#clearHistoryModal", state="hidden", timeout=8000)

            page.locator("#historyClearBtn").click()
            page.wait_for_selector("#clearHistoryModal", state="visible", timeout=8000)
            page.locator("#confirmClearHistoryBtn").click()
            page.wait_for_selector("[data-page-shell]", timeout=10000)
            _wait_for_toast_text(page, "Cleared")
            assert (
                "No history yet."
                in page.locator("#history-grid-container").inner_text()
            )
            assert page.locator("#historyClearBtn").count() == 0

            _assert_clean_runtime(page, runtime, screenshot_dir, "jtn_731_history_deep")
        finally:
            browser.close()


@pytest.mark.parametrize("plugin_id", PLUGIN_IDS)
def test_plugin_pages_boot_cleanly(live_server, tmp_path, plugin_id):
    from playwright.sync_api import sync_playwright

    screenshot_dir = _artifact_dir(tmp_path)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            runtime = _open_and_check(
                page,
                live_server,
                f"plugin_{plugin_id}",
                f"/plugin/{plugin_id}",
                screenshot_dir,
            )
            _assert_plugin_page_ready(page, plugin_id)
            _assert_clean_runtime(page, runtime, screenshot_dir, f"plugin_{plugin_id}")
        finally:
            browser.close()


@pytest.mark.parametrize("viewport", MOBILE_VIEWPORTS, ids=lambda item: item["label"])
@pytest.mark.parametrize("theme", ("light", "dark"))
def test_top_level_tabs_phone_layout(live_server, tmp_path, viewport, theme):
    from playwright.sync_api import sync_playwright

    screenshot_dir = _artifact_dir(tmp_path)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for route_name, route_path in TOP_LEVEL_ROUTES:
                page = _new_page(browser, viewport, theme)
                runtime = _open_and_check(
                    page, live_server, route_name, route_path, screenshot_dir
                )
                page.wait_for_selector(TOP_LEVEL_MARKERS[route_name], timeout=10000)
                _assert_no_horizontal_overflow(page)
                _assert_action_visible(page, TOP_LEVEL_PRIMARY_ACTIONS[route_name])
                _maybe_capture_baseline(
                    page,
                    screenshot_dir,
                    f"mobile_{route_name}_{theme}_{viewport['label']}",
                )
                _assert_clean_runtime(
                    page,
                    runtime,
                    screenshot_dir,
                    f"mobile_{route_name}_{theme}_{viewport['label']}",
                )
                page.close()
        finally:
            browser.close()


@pytest.mark.parametrize("viewport", MOBILE_VIEWPORTS, ids=lambda item: item["label"])
@pytest.mark.parametrize("theme", ("light", "dark"))
@pytest.mark.parametrize("plugin_id", MOBILE_PLUGIN_IDS)
def test_plugin_pages_phone_layout(live_server, tmp_path, viewport, theme, plugin_id):
    from playwright.sync_api import sync_playwright

    screenshot_dir = _artifact_dir(tmp_path)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _new_page(browser, viewport, theme)
            runtime = _open_and_check(
                page,
                live_server,
                f"mobile_plugin_{plugin_id}",
                f"/plugin/{plugin_id}",
                screenshot_dir,
            )
            _assert_plugin_page_ready(page, plugin_id)
            # Design refresh: the Configure/Preview mode bar was removed; both
            # panels are always rendered (stacked on mobile, side-by-side on
            # desktop). Assert both panels attach and are visible.
            page.wait_for_selector("[data-workflow-panel='configure']", state="attached")
            page.wait_for_selector("[data-workflow-panel='preview']", state="attached")
            assert page.locator("[data-workflow-panel='preview']").count() >= 1
            assert page.locator("[data-workflow-panel='configure']").count() >= 1
            _assert_no_horizontal_overflow(page)
            _assert_action_visible(page, "[data-workflow-panel='preview']")
            _maybe_capture_baseline(
                page,
                screenshot_dir,
                f"mobile_plugin_{plugin_id}_{theme}_{viewport['label']}",
            )
            _assert_clean_runtime(
                page,
                runtime,
                screenshot_dir,
                f"mobile_plugin_{plugin_id}_{theme}_{viewport['label']}",
            )
        finally:
            browser.close()
