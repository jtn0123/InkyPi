# pyright: reportMissingImports=false
from __future__ import annotations

import os
from pathlib import Path

import pytest

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
        "**://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
        lambda route: route.fulfill(
            status=200,
            content_type="text/css",
            body="",
        ),
    )
    page.route(
        "**://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
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
        lambda request: runtime["request_failures"].append(
            {
                "url": request.url,
                "resource_type": request.resource_type,
                "failure": request.failure or "",
            }
        )
        if request.url.startswith(base_url)
        and request.resource_type in CRITICAL_RESPONSE_TYPES
        else None,
    )
    page.on(
        "response",
        lambda response: runtime["response_failures"].append(
            {
                "url": response.url,
                "status": response.status,
                "resource_type": response.request.resource_type,
            }
        )
        if response.url.startswith(base_url)
        and response.status >= 400
        and response.request.resource_type in CRITICAL_RESPONSE_TYPES
        else None,
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


def _assert_skip_link_removed(page):
    html = page.content()
    assert "skip-nav" not in html
    assert "Skip to main content" not in html
    assert "Skip to settings content" not in html


def _assert_plugin_page_ready(page, plugin_id: str):
    page.wait_for_selector("#settingsForm", state="attached")
    interactive_fields = page.locator("#settingsForm input, #settingsForm select, #settingsForm textarea")
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
    page = browser.new_page(viewport={"width": viewport["width"], "height": viewport["height"]})
    page.add_init_script(
        script=f"""
        (() => {{
            try {{
                localStorage.setItem("theme", {theme!r});
                localStorage.setItem("inkypi-theme", {theme!r});
            }} catch (e) {{}}
        }})();
        """
    )
    return page


def _assert_no_horizontal_overflow(page):
    widths = page.evaluate(
        """
        () => ({
            innerWidth: window.innerWidth,
            clientWidth: document.documentElement.clientWidth,
            scrollWidth: document.documentElement.scrollWidth,
        })
        """
    )
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


def _open_and_check(page, base_url: str, route_name: str, route_path: str, screenshot_dir: Path):
    runtime = _attach_runtime_collectors(page, base_url)
    page.goto(f"{base_url}{route_path}", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector("[data-page-shell]", timeout=10000)
    page.wait_for_timeout(500)
    _assert_skip_link_removed(page)
    return runtime


def _artifact_dir(tmp_path: Path) -> Path:
    override = os.getenv("BROWSER_SMOKE_ARTIFACT_DIR")
    if override:
        return Path(override)
    return tmp_path / "browser_smoke_failures"


def test_top_level_tabs_boot_cleanly(live_server, tmp_path):
    from playwright.sync_api import sync_playwright

    screenshot_dir = _artifact_dir(tmp_path)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for route_name, route_path in TOP_LEVEL_ROUTES:
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                runtime = _open_and_check(page, live_server, route_name, route_path, screenshot_dir)
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
                runtime = _open_and_check(page, live_server, route_name, route_path, screenshot_dir)
                page.wait_for_selector(TOP_LEVEL_MARKERS[route_name], timeout=10000)
                _assert_no_horizontal_overflow(page)
                _assert_action_visible(page, TOP_LEVEL_PRIMARY_ACTIONS[route_name])
                _maybe_capture_baseline(
                    page,
                    screenshot_dir,
                    f"mobile_{route_name}_{theme}_{viewport['label']}",
                )
                _assert_clean_runtime(page, runtime, screenshot_dir, f"mobile_{route_name}_{theme}_{viewport['label']}")
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
            page.wait_for_selector("[data-workflow-mode='configure']", state="attached")
            page.wait_for_selector("[data-workflow-mode='preview']", state="attached")
            page.locator("[data-workflow-mode='preview']").click()
            page.wait_for_timeout(200)
            assert page.locator("[data-workflow-panel='preview']").count() >= 1
            _assert_no_horizontal_overflow(page)
            _assert_action_visible(page, "[data-workflow-mode='preview']")
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
