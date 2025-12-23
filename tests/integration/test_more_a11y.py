"""
Accessibility (A11y) Tests

WHY THESE TESTS REQUIRE SPECIAL ENVIRONMENT:
================================================================================
These tests verify WCAG 2.1 accessibility compliance using automated tools.
They are skipped in standard environments (SKIP_A11Y=1) because they require:

1. **Playwright Browser Automation**:
   - Requires Chromium/Firefox/WebKit browser binaries
   - Needs playwright Python package + browser downloads (~300MB)
   - Cannot run in headless CI without browser installation

2. **Axe-core Accessibility Engine**:
   - Loads axe-core JavaScript library (4.8.2+) via CDN
   - Performs 90+ automated WCAG checks including:
     * ARIA roles and attributes
     * Semantic HTML structure (headings, landmarks, lists)
     * Form labels and descriptions
     * Color contrast ratios
     * Keyboard navigation order
     * Screen reader compatibility
   - Requires JavaScript execution environment

3. **Environment Requirements**:
   - Browser binaries installed (playwright install)
   - Network access to CDN for axe-core
   - Sufficient memory for browser instance (~200MB)
   - X11/Wayland display OR headless mode

WHAT THESE TESTS VERIFY:
- Plugin settings pages are navigable via keyboard
- Form inputs have proper labels and ARIA attributes
- Color contrast meets WCAG AA standards (4.5:1 for text)
- Semantic HTML structure for screen readers
- No accessibility violations in Inky

Pi web interface

TO RUN THESE TESTS:
1. Install Playwright: pip install playwright
2. Install browsers: playwright install chromium
3. Unset SKIP_A11Y: unset SKIP_A11Y or SKIP_A11Y=0 pytest tests/integration/test_more_a11y.py
"""

import os

import pytest


@pytest.mark.skipif(
    os.getenv("SKIP_A11Y", "").lower() in ("1", "true"),
    reason="A11y checks skipped by env",
)
def test_plugin_settings_accessibility(client):
    pw = pytest.importorskip("playwright.sync_api", reason="playwright not available")
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.8.2/axe.min.js")
        result = page.evaluate("() => axe.run(document)")
        browser.close()
    assert not (result.get("violations") or []), "Plugin page a11y violations detected"


@pytest.mark.skipif(
    os.getenv("SKIP_A11Y", "").lower() in ("1", "true"),
    reason="A11y checks skipped by env",
)
def test_settings_page_accessibility(client):
    pw = pytest.importorskip("playwright.sync_api", reason="playwright not available")
    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.8.2/axe.min.js")
        result = page.evaluate("() => axe.run(document)")
        browser.close()
    assert not (result.get("violations") or []), "Settings page a11y violations detected"


@pytest.mark.skipif(
    os.getenv("SKIP_A11Y", "").lower() in ("1", "true"),
    reason="A11y checks skipped by env",
)
def test_history_page_accessibility(client):
    pw = pytest.importorskip("playwright.sync_api", reason="playwright not available")
    resp = client.get("/history")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.8.2/axe.min.js")
        result = page.evaluate("() => axe.run(document)")
        browser.close()
    assert not (result.get("violations") or []), "History page a11y violations detected"


