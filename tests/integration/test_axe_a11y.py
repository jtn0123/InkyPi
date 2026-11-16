"""
Axe-core accessibility scans for every main route.

These tests load each page in a real Playwright browser, inject axe-core, and
assert zero violations. A rule that can't be fixed yet may be allowed for a
route in _KNOWN_VIOLATIONS with a TODO reference, and the test fails once an
allowed rule stops firing, so a fixed rule can't come back unnoticed.

Gate: SKIP_BROWSER=1 or SKIP_A11Y=1 causes pytest to skip collection entirely
(handled by conftest.pytest_ignore_collect).

To run:
    playwright install chromium
    SKIP_A11Y=0 PYTHONPATH=src pytest tests/integration/test_axe_a11y.py -q
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

# ── Routes to scan ──────────────────────────────────────────────────────────
_ROUTES: list[tuple[str, str]] = [
    ("home", "/"),
    ("settings", "/settings"),
    ("playlist", "/playlist"),
    ("history", "/history"),
    ("api_keys", "/settings/api-keys"),
    ("plugin_clock", "/plugin/clock"),
]

# ── Known violations allowed per route ──────────────────────────────────────
# Maps a route name to the axe rule ids it may still violate, each with a
# TODO ticket. Empty: every rule passes on every route. The test fails when an
# allowed rule no longer fires, so remove an entry as soon as its fix lands.
_KNOWN_VIOLATIONS: dict[str, set[str]] = {}


def _load_axe_js() -> str:
    axe_path = Path(__file__).resolve().parent.parent / "fixtures" / "axe.min.js"
    return axe_path.read_text(encoding="utf-8")


@pytest.mark.skipif(
    os.getenv("SKIP_A11Y", "").lower() in ("1", "true"),
    reason="A11y checks skipped by env",
)
@pytest.mark.parametrize("route_name,route_path", _ROUTES, ids=[r[0] for r in _ROUTES])
def test_axe_scan(live_server: str, route_name: Any, route_path: Any) -> None:
    """Run axe-core against *route_path* and fail on unknown violations."""
    from playwright.sync_api import sync_playwright
    from tests.integration.browser_helpers import (
        RequestTracker,
        assert_axe_allowlist,
        wait_for_page_settled,
    )

    axe_js = _load_axe_js()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            requests = RequestTracker(page)
            page.goto(
                f"{live_server}{route_path}",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            page.wait_for_selector("[data-page-shell]", timeout=10_000)
            # Contrast checks read rendered colours, so wait out the page's
            # fade-in and the data its scripts fetch.
            wait_for_page_settled(page, requests)

            # Inject axe-core and run the scan
            page.add_script_tag(content=axe_js)
            result = page.evaluate("() => axe.run(document)")
        finally:
            browser.close()

    assert_axe_allowlist(result, _KNOWN_VIOLATIONS.get(route_name, set()), route_name)
