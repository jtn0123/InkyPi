"""The status badge polls the diagnostics summary, and only while the tab shows (G10).

``fetch`` is stubbed to record every URL the badge asks for, the page's
visibility is faked so a test can hide and show it, and Playwright's clock
drives the 30-second poll timer.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import Page

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.skipif(
        os.getenv("SKIP_BROWSER", "").lower() in ("1", "true")
        or os.getenv("SKIP_UI", "").lower() in ("1", "true"),
        reason="Browser/UI tests skipped by env",
    ),
]

SCRIPT = Path(__file__).resolve().parents[2] / "src/static/scripts/status_badge.js"
SUMMARY_URL = "/api/diagnostics?summary=1"
POLL_MS = 30_000

# window.__diag lists the URLs fetched; window.__health is what the stub
# reports as plugin health. window.__setVisibility(state) hides or shows the
# page the way switching tabs does.
STUBS = """
window.__diag = [];
window.__health = {};
window.fetch = async (url) => {
  window.__diag.push(String(url));
  const body = {
    refresh_task: { last_error: null },
    plugin_health: window.__health,
    last_update_failure: null,
    recent_client_log_errors: { count_5m: 0, warn_count_5m: 0 },
    summary: true,
  };
  return new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' }
  });
};
Object.defineProperty(document, 'visibilityState', {
  configurable: true, get: () => window.__visibility,
});
Object.defineProperty(document, 'hidden', {
  configurable: true, get: () => window.__visibility !== 'visible',
});
window.__setVisibility = (state) => {
  window.__visibility = state;
  document.dispatchEvent(new Event('visibilitychange'));
};
"""


def _open(page: Page, *, visibility: str = "visible") -> None:
    page.clock.install()
    page.set_content("<body></body>")
    page.add_script_tag(content=STUBS)
    page.evaluate("(state) => { window.__visibility = state; }", visibility)
    page.add_script_tag(content=SCRIPT.read_text(encoding="utf-8"))


def _polls(page: Page) -> list[str]:
    polls: list[str] = page.evaluate("() => window.__diag")
    return polls


def _set_visibility(page: Page, state: str) -> None:
    page.evaluate("(state) => window.__setVisibility(state)", state)


def test_the_badge_polls_the_summary_every_30_seconds(browser_page: Page) -> None:
    _open(browser_page)
    assert _polls(browser_page) == [SUMMARY_URL]

    browser_page.clock.run_for(POLL_MS)
    browser_page.clock.run_for(POLL_MS)

    assert _polls(browser_page) == [SUMMARY_URL] * 3


def test_a_hidden_tab_stops_polling_and_resumes_when_shown(
    browser_page: Page,
) -> None:
    _open(browser_page)
    assert len(_polls(browser_page)) == 1

    _set_visibility(browser_page, "hidden")
    browser_page.clock.run_for(4 * POLL_MS)
    assert len(_polls(browser_page)) == 1

    # Shown again: poll at once, then every 30 s on a single timer.
    _set_visibility(browser_page, "visible")
    assert len(_polls(browser_page)) == 2
    browser_page.clock.run_for(POLL_MS)
    assert _polls(browser_page) == [SUMMARY_URL] * 3


def test_a_page_opened_in_a_hidden_tab_waits_until_shown(browser_page: Page) -> None:
    _open(browser_page, visibility="hidden")
    browser_page.clock.run_for(2 * POLL_MS)
    assert _polls(browser_page) == []

    _set_visibility(browser_page, "visible")
    assert _polls(browser_page) == [SUMMARY_URL]
    browser_page.clock.run_for(POLL_MS)
    assert len(_polls(browser_page)) == 2


def test_raw_diagnostics_still_opens_the_full_payload(browser_page: Page) -> None:
    _open(browser_page, visibility="hidden")
    browser_page.evaluate("() => { window.__health = { clock: 'fail' }; }")
    _set_visibility(browser_page, "visible")
    browser_page.wait_for_function(
        "() => document.getElementById('statusBadge').dataset.state === 'error'"
    )

    browser_page.locator("#statusBadge").click()

    raw = browser_page.locator("#statusBadgePopover a[target='_blank']")
    assert raw.inner_text() == "Raw diagnostics"
    assert raw.get_attribute("href") == "/api/diagnostics"
