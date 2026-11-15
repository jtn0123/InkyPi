"""Update Now's background render, driven through plugin_form.js in a browser.

The page posts to /update_now, gets 202 with a job id, then polls
/api/job/<id> while /api/progress/stream reports steps. ``fetch`` and
``EventSource`` are stubbed, and Playwright's clock drives the timers, so
each test controls exactly what the server says and when.
"""

import os
from pathlib import Path
from typing import Any

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

SCRIPT = Path(__file__).resolve().parents[2] / "src/static/scripts/plugin_form.js"

PAGE = """
<form id="settingsForm"><input name="plugin_id" value="clock"></form>
<form id="scheduleForm"></form>
<div id="loadingIndicator"></div>
<section id="requestProgress" hidden>
  <p id="requestProgressText"></p>
  <div id="requestProgressBar"></div>
  <progress id="requestProgressBarMeter" max="100"></progress>
  <ol id="requestProgressList"></ol>
  <span id="requestProgressClock"></span>
  <span id="requestProgressElapsed"></span>
</section>
"""

# window.__job is what /api/job/j1 answers; tests change it as the render
# moves on. window.__live(state, extra) emits a progress stream event.
STUBS = """
window.__modals = [];
window.showResponseModal = (kind, message) => window.__modals.push([kind, message]);
window.__polls = 0;
window.__job = { status: 'running' };
window.fetch = async (url) => {
  const json = (body, status) => new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' }
  });
  if (String(url) === '/update_now') return json({ job_id: 'j1' }, 202);
  if (String(url) === '/api/job/j1') { window.__polls++; return json(window.__job, 200); }
  throw new TypeError('unexpected fetch ' + url);
};
class FakeEventSource {
  constructor() { this.listeners = {}; window.__stream = this; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  close() { this.closed = true; }
}
window.EventSource = FakeEventSource;
window.__live = (state, extra) => {
  const payload = Object.assign({ plugin_id: 'clock', state, ts: Date.now() / 1000 }, extra || {});
  (window.__stream.listeners[state] || []).forEach((fn) => fn({ data: JSON.stringify(payload) }));
};
window.__send = () => {
  window.__result = undefined;
  window.PluginForm.sendForm({
    action: 'update_now', urls: { update_now: '/update_now' }, uploadedFiles: {}
  }).then((r) => { window.__result = r; });
};
"""


def _open(page: Page, *, live_stream: bool = True) -> None:
    page.clock.install()
    page.set_content(PAGE)
    page.add_script_tag(content=STUBS)
    if not live_stream:
        page.evaluate("() => { window.EventSource = undefined; }")
    page.add_script_tag(content=SCRIPT.read_text(encoding="utf-8"))
    page.evaluate("() => window.__send()")


def _run(page: Page, ms: int) -> None:
    page.clock.run_for(ms)


def _result(page: Page) -> Any:
    page.wait_for_function("() => window.__result !== undefined", timeout=5000)
    return page.evaluate("() => window.__result")


def _steps(page: Page) -> list[str]:
    return page.locator("#requestProgressList li").all_inner_texts()


def test_finished_render_shows_success_and_timings(browser_page: Page) -> None:
    _open(browser_page, live_stream=False)
    _run(browser_page, 1000)
    assert browser_page.evaluate("() => window.__polls") == 1
    browser_page.evaluate("""() => { window.__job = { status: 'done', result: {
        success: true, message: 'Display updated',
        metrics: { steps: [{ name: 'generate', elapsed_ms: 12 }], request_ms: 40 }
    } }; }""")
    _run(browser_page, 1200)

    assert _result(browser_page)["success"] is True
    assert browser_page.evaluate("() => window.__modals") == [
        ["success", "Success! Display updated"]
    ]
    steps = " | ".join(_steps(browser_page))
    assert "generate 12 ms" in steps
    assert "Request 40 ms" in steps
    assert browser_page.inner_text("#requestProgressText") == "Done"


def test_failed_render_shows_the_error(browser_page: Page) -> None:
    _open(browser_page, live_stream=False)
    browser_page.evaluate(
        "() => { window.__job = { status: 'error', error: 'Calendar unreachable' }; }"
    )
    _run(browser_page, 1000)

    assert _result(browser_page)["success"] is False
    assert browser_page.evaluate("() => window.__modals") == [
        ["failure", "Error! Calendar unreachable"]
    ]
    assert "Failed" in browser_page.inner_text("#requestProgressText")


def test_render_that_never_finishes_says_it_timed_out(browser_page: Page) -> None:
    """The 90 s limit used to end the poll loop silently: no message at all."""
    _open(browser_page, live_stream=False)
    _run(browser_page, 91_000)

    assert _result(browser_page)["success"] is False
    modals = browser_page.evaluate("() => window.__modals")
    assert len(modals) == 1
    assert modals[0][0] == "failure"
    assert modals[0][1].startswith("Request timed out.")


def test_live_steps_slow_polling_and_its_end_collects_the_result(
    browser_page: Page,
) -> None:
    _open(browser_page)
    browser_page.evaluate("() => window.__live('running')")
    _run(browser_page, 1000)
    assert browser_page.evaluate("() => window.__polls") == 1

    # While steps keep arriving, the page polls every 3 s, not every second.
    for _ in range(2):
        browser_page.evaluate("() => window.__live('step', { step: 'Fetching' })")
        _run(browser_page, 1000)
    assert browser_page.evaluate("() => window.__polls") == 1
    assert "Fetching" in _steps(browser_page)[-1]

    # The stream's done event fetches the result straight away.
    browser_page.evaluate("""() => {
        window.__job = { status: 'done', result: { success: true, message: 'Display updated' } };
        window.__live('done');
    }""")
    _run(browser_page, 10)

    assert _result(browser_page)["success"] is True
    assert browser_page.evaluate("() => window.__polls") == 2
    assert browser_page.evaluate("() => window.__stream.closed") is True
