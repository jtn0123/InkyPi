# pyright: reportMissingImports=false
"""Shared fixtures for Playwright-based integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Flakiness retry (JTN-705).
#
# Integration tests exercise Playwright, refresh loops, and cross-process
# state that can flake for reasons unrelated to the code under test (network
# blips, compositor jitter, file-watch races). One retry dramatically lowers
# false-positive noise while still surfacing real regressions — a test that
# fails twice in a row is almost certainly a genuine bug.
#
# IMPORTANT: reruns are scoped to ``tests/integration/`` ONLY. Unit tests
# must stay deterministic: if a unit test flakes, that is a bug we want to
# see on the first failure, not paper over with a silent retry. The hook
# below explicitly gates on the collection path so retries cannot leak into
# other suites even if this conftest is imported indirectly.
#
# pytest-rerunfailures prints a rerun summary in the terminal report by
# default (``R`` progress dots and a "rerun" count in the summary line), so
# CI captures repeated flakes without extra configuration.
# ---------------------------------------------------------------------------

_INTEGRATION_TESTS_DIR = Path(__file__).resolve().parent
_RERUNS = 1
_RERUNS_DELAY_SECONDS = 1


def pytest_collection_modifyitems(items):
    """Apply ``@pytest.mark.flaky(reruns=1, ...)`` to integration tests only.

    Gating on the resolved file path (not the pytest ``nodeid``) guarantees
    we only retry tests physically located under ``tests/integration/`` even
    if another suite imports this conftest or if pytest is invoked from a
    different cwd. Tests that already declare an explicit ``flaky`` marker
    are left alone so they can opt in to a higher retry count.
    """
    flaky_marker = pytest.mark.flaky(reruns=_RERUNS, reruns_delay=_RERUNS_DELAY_SECONDS)
    for item in items:
        try:
            item_path = Path(str(item.fspath)).resolve()
        except (OSError, ValueError):
            continue
        try:
            item_path.relative_to(_INTEGRATION_TESTS_DIR)
        except ValueError:
            # Not under tests/integration/ — do not attach a retry.
            continue
        if item.get_closest_marker("flaky") is not None:
            continue
        item.add_marker(flaky_marker)


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
