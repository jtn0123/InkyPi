"""Real EventSource and HTTP recovery contracts in both production asset modes."""

import importlib.util
import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from flask import Flask
from playwright.sync_api import Page, Route, expect

from utils.event_bus import get_event_bus

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.flaky(reruns=0)


@pytest.fixture(params=[False, True], ids=["fallback-assets", "bundled-common-assets"])
def dashboard_asset_mode(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    flask_app: Flask,
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> bool:
    """Dashboard stays page-specific; build the actual common bundle for parity."""
    bundled = bool(request.param)
    monkeypatch.setitem(flask_app.jinja_env.globals, "bundled_assets_enabled", bundled)
    if bundled:
        spec = importlib.util.spec_from_file_location(
            "build_assets", ROOT / "scripts/build_assets.py"
        )
        assert spec is not None
        assert spec.loader is not None
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        monkeypatch.setattr(builder, "DIST_DIR", tmp_path)
        builder.main([])
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        monkeypatch.setitem(flask_app.jinja_env.globals, "bundled_asset", manifest.get)

        def serve_asset(path: Path) -> Callable[[Route], None]:
            def fulfill(route: Route) -> None:
                route.fulfill(path=path)

            return fulfill

        for filename in manifest.values():
            browser_page.route(
                f"**/static/dist/{filename}*", serve_asset(tmp_path / filename)
            )
    return bundled


def test_real_named_events_hydrate_and_update_dashboard(
    dashboard_asset_mode: bool, live_server: str, browser_page: Page
) -> None:
    """The production event endpoint emits named frames consumed by Chromium."""
    page = browser_page
    state = {"generation": 1, "refresh_requests": 0, "stats_requests": 0}
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def refresh_response(route: Route) -> None:
        state["refresh_requests"] += 1
        route.fulfill(
            json={
                "plugin_id": "weather",
                "plugin_display_name": f"Weather {state['generation']}",
            }
        )

    def next_response(route: Route) -> None:
        route.fulfill(
            json={
                "plugin_id": "countdown",
                "plugin_display_name": f"Countdown {state['generation']}",
            }
        )

    def stats_response(route: Route) -> None:
        state["stats_requests"] += 1
        route.fulfill(json={"last_24h": {"total": state["generation"], "failure": 0}})

    page.route("**/refresh-info", refresh_response)
    page.route("**/next-up", next_response)
    page.route("**/api/stats", stats_response)
    page.goto(live_server, wait_until="domcontentloaded")
    expect(page.locator("#heroNowValue")).to_have_text("Weather 1")
    expect(page.locator("#heroNextValue")).to_have_text("Countdown 1")
    # Subscribing precedes the first SSE body bytes; publishing starts real delivery.
    bus = get_event_bus()
    deadline = time.monotonic() + 5
    while bus.subscriber_count() == 0 and time.monotonic() < deadline:
        page.wait_for_timeout(25)
    assert bus.subscriber_count() > 0
    for generation, name in enumerate(
        ["refresh_started", "refresh_complete", "plugin_failed"], start=2
    ):
        before_refresh = state["refresh_requests"]
        before_stats = state["stats_requests"]
        state["generation"] = generation
        bus.publish(name, {"plugin_id": "weather"})
        expect(page.locator("#heroNowValue")).to_have_text(f"Weather {generation}")
        expect(page.locator("#heroNextValue")).to_have_text(f"Countdown {generation}")
        expect(page.locator("#kpiRefreshes")).to_have_text(str(generation))
        assert state["refresh_requests"] > before_refresh
        assert state["stats_requests"] > before_stats
    assert errors == []


@pytest.mark.expected_client_logs(r"^Failed to fetch (refresh|next-up) info:")
def test_http_503_retains_last_good_partial_success_and_recovers(
    dashboard_asset_mode: bool, live_server: str, browser_page: Page
) -> None:
    """Expected 503s are injected HTTP responses, never an unhandled JS failure."""
    page = browser_page
    state = {"generation": 1, "refresh_status": 200, "next_status": 200}
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def refresh_response(route: Route) -> None:
        status = state["refresh_status"]
        route.fulfill(
            status=status,
            json={
                "plugin_id": "weather" if status == 200 else None,
                "plugin_display_name": f"Weather {state['generation']}",
                "error": "Unavailable" if status != 200 else "",
            },
        )

    def next_response(route: Route) -> None:
        status = state["next_status"]
        route.fulfill(
            status=status,
            json={
                "plugin_id": "countdown" if status == 200 else None,
                "plugin_display_name": f"Countdown {state['generation']}",
                "error": "Unavailable" if status != 200 else "",
            },
        )

    page.add_init_script(r"""(() => {
        const original = window.fetch;
        window.__dashboardRequestsPending = 0;
        window.fetch = function(...args) {
            const tracked = /\/(refresh-info|next-up)$/.test(String(args[0]));
            if (tracked) window.__dashboardRequestsPending++;
            return original.apply(this, args).finally(() => {
                if (tracked) window.__dashboardRequestsPending--;
            });
        };
    })();""")
    page.route("**/refresh-info", refresh_response)
    page.route("**/next-up", next_response)
    # Force the manual fetch baseline even before the C4 initial hydration fix.
    page.goto(live_server, wait_until="domcontentloaded")
    with page.expect_response("**/next-up"):
        page.locator("#dashboardRefreshBtn").click()
    expect(page.locator("#heroNowValue")).to_have_text("Weather 1")
    expect(page.locator("#heroNextValue")).to_have_text("Countdown 1")
    page.wait_for_function("() => window.__dashboardRequestsPending === 0")
    state.update(generation=2, refresh_status=503, next_status=503)
    for _ in range(3):
        with page.expect_response(
            lambda response: response.url.endswith("/next-up")
            and response.status == 503
        ) as response:
            page.locator("#dashboardRefreshBtn").click()
        assert response.value.status == 503
        page.wait_for_function("() => window.__dashboardRequestsPending === 0")
    expect(page.locator("#heroNowValue")).to_have_text("Weather 1")
    expect(page.locator("#heroNextValue")).to_have_text("Countdown 1")
    expect(page.locator("#connectivityWarning")).to_be_visible()
    state["next_status"] = 200
    with page.expect_response("**/next-up"):
        page.locator("#dashboardRefreshBtn").click()
    expect(page.locator("#heroNextValue")).to_have_text("Countdown 2")
    expect(page.locator("#heroNowValue")).to_have_text("Weather 1")
    expect(page.locator("#connectivityWarning")).to_be_visible()
    state["refresh_status"] = 200
    with page.expect_response("**/refresh-info"):
        page.locator("#dashboardRefreshBtn").click()
    expect(page.locator("#heroNowValue")).to_have_text("Weather 2")
    expect(page.locator("#connectivityWarning")).to_be_hidden()
    assert errors == []
