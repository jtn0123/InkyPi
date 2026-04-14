# pyright: reportMissingImports=false
"""Shared fixtures for Playwright-based integration tests."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Client-log tripwire (JTN-680).
#
# Any POST to ``/api/client-log`` during a Playwright test means a
# ``console.warn`` / ``console.error`` fired in the browser and the
# ``client_log_reporter.js`` shim forwarded it to the server. That is
# exactly the class of silent failure Layer 4 aims to surface, so the
# fixture below flips the handler into capture mode and auto-asserts the
# captured list is empty at teardown.
#
# The fixture is autouse so *every* test in ``tests/integration`` gets the
# tripwire — existing browser tests automatically benefit.
# ---------------------------------------------------------------------------

# Meta tag injected into the page so ``client_log_reporter.js`` opts in
# during tests even though base.html does not set it by default.
_CLIENT_LOG_META_INIT_SCRIPT = """
(() => {
  const ensureMeta = (name, content) => {
    if (document.querySelector('meta[name="' + name + '"]')) return;
    const head = document.head || document.getElementsByTagName('head')[0];
    if (!head) return;
    const meta = document.createElement('meta');
    meta.setAttribute('name', name);
    meta.setAttribute('content', content);
    head.insertBefore(meta, head.firstChild);
  };
  const installMetas = () => {
    ensureMeta('client-log-enabled', '1');
    ensureMeta('client-log-test-mode', '1');
  };
  if (document.readyState === 'loading') {
    document.addEventListener('readystatechange', installMetas, { once: true });
  }
  installMetas();
})();
"""


@pytest.fixture(autouse=True)
def client_log_capture(monkeypatch):
    """Enable /api/client-log capture for the duration of the test.

    On teardown, assert the captured list is empty — any POST during the
    test means a ``console.warn``/``console.error`` slipped through and
    should fail the test with the message visible in the failure output.

    The fixture is autouse so existing browser tests pick up the tripwire
    automatically. Tests that intentionally trigger client logs (e.g. the
    dedicated tests in ``tests/test_client_log_forwarding.py``) live
    outside ``tests/integration`` and are unaffected.
    """
    from blueprints.client_log import get_captured_reports, reset_captured_reports

    monkeypatch.setenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", "1")
    reset_captured_reports()

    yield

    reports = get_captured_reports()
    reset_captured_reports()
    if reports:
        formatted = "\n".join(
            f"  [{r.get('level', '?')}] {r.get('message', '')} "
            f"(url={r.get('url', '')})"
            for r in reports
        )
        pytest.fail(
            "Client-log tripwire (JTN-680): "
            f"{len(reports)} console.warn/error report(s) posted to "
            "/api/client-log during this test — browser JS logged errors:\n"
            f"{formatted}"
        )


@pytest.fixture()
def browser_page():
    """Desktop-sized Playwright page (1280x900). Closes browser on teardown."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.add_init_script(_CLIENT_LOG_META_INIT_SCRIPT)
        yield page
        browser.close()


@pytest.fixture()
def mobile_page():
    """Mobile-sized Playwright page (360x800). Closes browser on teardown."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 360, "height": 800})
        page.add_init_script(_CLIENT_LOG_META_INIT_SCRIPT)
        yield page
        browser.close()
