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


