"""
Axe-core accessibility scans for every main route.

These tests load each page in a real Playwright browser, inject axe-core, and
assert zero *new* violations.  Known pre-existing violations are whitelisted
with TODO references so they can be burned down incrementally.

Gate: SKIP_BROWSER=1 or SKIP_A11Y=1 causes pytest to skip collection entirely
(handled by conftest.pytest_ignore_collect).

To run:
    playwright install chromium
    SKIP_A11Y=0 PYTHONPATH=src pytest tests/integration/test_axe_a11y.py -q
"""

from __future__ import annotations

import os
from pathlib import Path

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

# ── Known violations whitelisted per-route ──────────────────────────────────
# Each entry maps an axe rule-id to a TODO ticket so regressions are tracked.
_KNOWN_VIOLATIONS: dict[str, set[str]] = {
    # landmark-one-main / region fire because axe sees content outside <main>
    # due to skip-link and modal markup.  TODO(JTN-508): restructure base.html.
    #
    # landmark-banner-is-top-level fires on pages with <header role="banner">
    # nested inside <main>.  TODO(JTN-508): move banner outside <main>.
    #
    # aria-dialog-name fires on the response modal and schedule modal when
    # aria-labelledby points to an empty <p>.  TODO(JTN-509): set modal title.
    #
    # color-contrast fires on some status chips and placeholder text.
    # TODO(JTN-510): audit contrast ratios.
    "home": {
        "landmark-one-main",
        "region",
        "color-contrast",  # TODO(JTN-510)
    },
    "settings": {
        "landmark-one-main",
        "region",
        "landmark-banner-is-top-level",  # TODO(JTN-508)
        "aria-dialog-name",  # TODO(JTN-509)
        "color-contrast",  # TODO(JTN-510)
    },
    "playlist": {
        "landmark-one-main",
        "region",
        "landmark-banner-is-top-level",  # TODO(JTN-508)
        "heading-order",  # TODO(JTN-508): h3 inside empty-state skips h2
        "aria-dialog-name",  # TODO(JTN-509)
        "color-contrast",  # TODO(JTN-510)
    },
    "history": {
        "landmark-one-main",
        "region",
        "landmark-banner-is-top-level",  # TODO(JTN-508)
        "heading-order",  # TODO(JTN-508)
        "aria-dialog-name",  # TODO(JTN-509)
        "color-contrast",  # TODO(JTN-510)
    },
    "api_keys": {
        "landmark-one-main",
        "region",
        "landmark-banner-is-top-level",  # TODO(JTN-508)
        "heading-order",  # TODO(JTN-508)
        "aria-dialog-name",  # TODO(JTN-509)
        "color-contrast",  # TODO(JTN-510)
    },
    "plugin_clock": {
        "landmark-one-main",
        "region",
        "aria-dialog-name",  # TODO(JTN-509)
        "color-contrast",  # TODO(JTN-510)
        "nested-interactive",  # TODO(JTN-511): collapsible button wraps interactive
        "aria-hidden-focus",  # TODO(JTN-511): hidden modal contains focusable elements
    },
}


def _load_axe_js() -> str:
    axe_path = Path(__file__).resolve().parent.parent / "fixtures" / "axe.min.js"
    return axe_path.read_text(encoding="utf-8")


@pytest.mark.skipif(
    os.getenv("SKIP_A11Y", "").lower() in ("1", "true"),
    reason="A11y checks skipped by env",
)
@pytest.mark.parametrize("route_name,route_path", _ROUTES, ids=[r[0] for r in _ROUTES])
def test_axe_scan(live_server, route_name, route_path):
    """Run axe-core against *route_path* and fail on unknown violations."""
    from playwright.sync_api import sync_playwright

    axe_js = _load_axe_js()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(
                f"{live_server}{route_path}",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            page.wait_for_selector("[data-page-shell]", timeout=10_000)
            page.wait_for_timeout(300)

            # Inject axe-core and run the scan
            page.add_script_tag(content=axe_js)
            result = page.evaluate("() => axe.run(document)")
        finally:
            browser.close()

    known = _KNOWN_VIOLATIONS.get(route_name, set())
    new_violations = [
        v for v in (result.get("violations") or []) if v["id"] not in known
    ]

    if new_violations:
        summary = "\n".join(
            f"  - {v['id']} ({v['impact']}): {v['description']}" for v in new_violations
        )
        pytest.fail(f"New a11y violations on {route_name}:\n{summary}")
