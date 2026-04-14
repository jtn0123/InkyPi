# pyright: reportMissingImports=false
"""Runtime click-sweep (Layer 3, Part B).

For each page in :data:`PAGES_TO_SWEEP` this test:

1. Loads the page with a :class:`RuntimeCollector` attached so console errors,
   uncaught exceptions and critical HTTP failures are captured.
2. Enumerates every visible ``<button>``, ``<a>`` and ``[data-*-action]``
   element that *isn't* flagged ``data-test-skip-click="true"``.
3. Clicks each element and waits briefly (250 ms) for the UI to settle.
4. Asserts that **no** click produced a JS ``pageerror`` or ``console.error``
   and that *something observable changed* — URL, a DOM mutation, a network
   request firing, or a modal opening — so handlers that silently no-op are
   surfaced.

Destructive controls (Delete / Reset / Shutdown / Clear-All) are tagged
``data-test-skip-click="true"`` in their templates with an HTML comment
explaining why. See the PR description for the full list.

Gating: the module is covered by the existing ``SKIP_UI`` / ``SKIP_BROWSER``
gates in ``tests/conftest.py`` — Playwright is only exercised when both
browser test groups are enabled and Chromium is installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
from tests.integration.browser_helpers import RuntimeCollector, stub_leaflet

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


@dataclass(frozen=True)
class SweepPage:
    """One page to sweep, with a marker selector we wait for before clicking."""

    label: str
    path: str
    ready_marker: str


PAGES_TO_SWEEP: tuple[SweepPage, ...] = (
    SweepPage("home", "/", "#previewImage"),
    SweepPage("settings", "/settings", ".settings-console-layout"),
    SweepPage("history", "/history", "#storage-block"),
    SweepPage("playlist", "/playlist", "#newPlaylistBtn"),
    SweepPage("plugin_clock", "/plugin/clock", "#settingsForm"),
    SweepPage("api_keys", "/api-keys", "#saveApiKeysBtn"),
)

# Time (ms) to wait after each click for DOM / network to settle. Keep
# deliberately short — the sweep fires dozens of clicks per page.
_CLICK_SETTLE_MS = 250

# Max clickable candidates to exercise per page. Pages like ``/api-keys`` can
# list dozens of preset buttons; once the first batch has proven handlers
# fire, testing every one wastes wall-time for no extra signal.
_MAX_CLICKS_PER_PAGE = 25

# Selectors that are valid clickables but we don't want to walk — they open
# external resources, destabilise the suite, or require a real backend.
_SKIP_SELECTORS: tuple[str, ...] = (
    '[data-test-skip-click="true"]',
    '[target="_blank"]',
    'a[href^="mailto:"]',
    'a[href^="tel:"]',
    'a[href^="http://"]',
    'a[href^="https://"]',
    "a[download]",
    # Skip-links are intentionally offscreen until focused; clicking them via
    # Playwright fails with "element is outside of the viewport" and they're
    # exercised by the dedicated accessibility tests.
    ".skip-link",
    # Submit buttons trigger form submission — covered by the e2e form tests
    # and often navigate away mid-sweep.
    'button[type="submit"]',
)

# Pages where the initial sweep surfaced bugs that the L2 batch-fix PR will
# address. Marked xfail so the harness ships green today and starts locking
# in once the fixes land. Each entry MUST link to a tracking Linear issue.
_XFAIL_PAGES: dict[str, str] = {}

# Viewports to sweep. Desktop is the original coverage; mobile (360×800)
# catches buttons/handlers that only break at narrow widths where menus
# collapse, sidebars become drawers, and clickables may overlap or hide.
_VIEWPORTS: tuple[tuple[str, str], ...] = (
    ("desktop", "browser_page"),
    ("mobile", "mobile_page"),
)

# Per-(label, viewport) xfails for mobile-only regressions. Keep empty
# until a mobile-specific break is triaged into Linear — new entries must
# link to a JTN issue so they get cleaned up.
_MOBILE_XFAIL_PAGES: dict[str, str] = {}


_ENUMERATE_JS = """
(skipSelectors) => {
  const currentPath = window.location.pathname;
  const isVisible = (el) => {
    if (!el.isConnected) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return false;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    if (parseFloat(style.opacity) === 0) return false;
    return true;
  };

  const skipMatches = (el) =>
    skipSelectors.some((sel) => {
      try { return el.matches(sel) || el.closest(sel); }
      catch (_) { return false; }
    });

  const candidates = new Set();
  const selectors = ['button', 'a', '[data-plugin-action]', '[data-api-action]',
                     '[data-settings-tab]', '[data-history-action]',
                     '[data-collapsible-toggle]', '[data-workflow-mode]',
                     '[data-playlist-toggle]'];
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) candidates.add(el);
  }

  const descriptors = [];
  let idx = 0;
  for (const el of candidates) {
    if (!isVisible(el)) continue;
    if (skipMatches(el)) continue;
    // Skip disabled controls — clicking them is a no-op by design.
    if (el.disabled) continue;
    if (el.getAttribute('aria-disabled') === 'true') continue;
    // Give each candidate a stable id attribute we can look up later.
    const marker = `__clicksweep_${idx++}`;
    el.setAttribute('data-clicksweep-id', marker);
    const hrefAttr = el.getAttribute('href');
    // "Already at target state" heuristics — clicking one of these is a
    // legitimate no-op and should not count as a silent failure. Two cases:
    // * An anchor whose href is the current pathname (logo/home links).
    // * A selector-style button already flagged selected/active.
    const isSameLink =
      el.tagName === 'A' && hrefAttr && (hrefAttr === currentPath ||
        hrefAttr === currentPath + '/' || hrefAttr === '#');
    const isAlreadySelected =
      el.classList.contains('selected') || el.classList.contains('active') ||
      el.getAttribute('aria-pressed') === 'true' ||
      el.getAttribute('aria-current') === 'page';
    descriptors.push({
      id: marker,
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || el.getAttribute('aria-label') || el.title || '').trim().slice(0, 60),
      hasAction:
        !!(el.dataset && (el.dataset.pluginAction || el.dataset.apiAction ||
                          el.dataset.historyAction || el.dataset.settingsTab)),
      href: hrefAttr || null,
      tolerateNoChange: isSameLink || isAlreadySelected,
    });
  }
  return descriptors;
}
"""


_INSTALL_OBSERVER_JS = """
() => {
  window.__clicksweepMutations = 0;
  const obs = new MutationObserver((records) => {
    window.__clicksweepMutations += records.length;
  });
  obs.observe(document.documentElement, {
    childList: true, subtree: true, attributes: true, characterData: true,
  });
  window.__clicksweepObserver = obs;
  // Monkey-patch fetch + XHR so we can count outbound requests fired by clicks.
  window.__clicksweepRequests = 0;
  const origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function (...args) {
      window.__clicksweepRequests += 1;
      return origFetch.apply(this, args);
    };
  }
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    window.__clicksweepRequests += 1;
    return origSend.apply(this, args);
  };
  // Stash a marker in window.name so we can tell a full-document navigation
  // from a SPA-style URL change — a `location.reload()` click will wipe all
  // window state including this marker.
  window.name = "__clicksweep_marker__";
}
"""


_SNAPSHOT_JS = """
() => ({
  url: window.location.href,
  mutations: window.__clicksweepMutations || 0,
  requests: window.__clicksweepRequests || 0,
  openModal: !!document.querySelector(
    '.modal:not([hidden]), dialog[open], [aria-modal="true"]:not([hidden])'
  ),
  // Window `name` is wiped by full-document navigations (reload or goto) —
  // if our marker is gone, the click caused a fresh document to load.
  markerPresent: window.name === "__clicksweep_marker__",
})
"""


def _install_observer(page) -> None:
    page.evaluate(_INSTALL_OBSERVER_JS)


def _snapshot(page) -> dict:
    return page.evaluate(_SNAPSHOT_JS)


def _observable_change(before: dict, after: dict) -> bool:
    """True iff *something* visibly changed between the two snapshots."""
    if before["url"] != after["url"]:
        return True
    if after["mutations"] > before["mutations"]:
        return True
    if after["requests"] > before["requests"]:
        return True
    if not before["openModal"] and after["openModal"]:
        return True
    # Full-document navigation (e.g. location.reload(), anchor clicks that
    # re-request the current URL) blows away window.name, which is our
    # signal that the handler actually fired.
    return bool(before.get("markerPresent") and not after.get("markerPresent"))


def _enumerate_candidates(page) -> list[dict]:
    return page.evaluate(_ENUMERATE_JS, list(_SKIP_SELECTORS))


def _click_one(page, descriptor: dict) -> tuple[dict, dict]:
    """Click a single candidate and return (before, after) snapshots.

    We try Playwright's native ``click`` first (picks up default event
    sequencing) and fall back to dispatching a synthetic click via
    ``element.click()`` in page context when Playwright rejects the click
    on visibility grounds. We asserted visibility ourselves during
    enumeration, so this is a safe escape hatch.
    """
    before = _snapshot(page)
    selector = f"[data-clicksweep-id='{descriptor['id']}']"
    locator = page.locator(selector).first
    try:
        locator.click(timeout=2000, force=True, no_wait_after=True)
    except Exception as exc:  # noqa: BLE001 — we catalogue, don't rethrow
        # Fall back to element.click() via evaluate — this dispatches a
        # trusted-looking click without Playwright's visibility/viewport
        # assertions, which matches the intent of "did the handler fire?".
        try:
            page.evaluate("(sel) => document.querySelector(sel)?.click()", selector)
        except Exception as inner:  # noqa: BLE001
            return before, {
                **before,
                "click_error": f"{exc}; fallback also failed: {inner}",
            }
    # Give navigations a chance to commit so reload/anchor clicks reach a
    # stable state before we snapshot.
    try:
        page.wait_for_load_state("domcontentloaded", timeout=500)
    except Exception:  # noqa: BLE001 — no navigation in flight is expected
        pass
    page.wait_for_timeout(_CLICK_SETTLE_MS)
    after = _snapshot(page)
    return before, after


def _reset_page_state(page, base_url: str, sweep: SweepPage) -> None:
    """Return to the sweep's starting URL without re-attaching observers."""
    current = page.url
    if not current.endswith(sweep.path) and sweep.path not in current:
        page.goto(
            f"{base_url}{sweep.path}",
            wait_until="domcontentloaded",
            timeout=15000,
        )
        page.wait_for_selector(sweep.ready_marker, timeout=10000)
    # Re-install the observer: a navigation would have blown it away, and
    # we want a clean mutation counter between clicks regardless.
    _install_observer(page)


@pytest.mark.parametrize(
    "viewport,page_fixture",
    _VIEWPORTS,
    ids=[vp[0] for vp in _VIEWPORTS],
)
@pytest.mark.parametrize("sweep", PAGES_TO_SWEEP, ids=lambda sweep: sweep.label)
def test_click_sweep(
    live_server, request, sweep: SweepPage, viewport: str, page_fixture: str
):
    """Click every visible clickable on the page; assert no silent failures.

    Parametrized over viewport: ``desktop`` (1280×900) and ``mobile``
    (360×800). Mobile reflows can hide or overlap controls and catch
    handlers that only break at narrow widths.
    """
    if sweep.label in _XFAIL_PAGES:
        pytest.xfail(_XFAIL_PAGES[sweep.label])
    mobile_key = f"{sweep.label}:{viewport}"
    if viewport == "mobile" and mobile_key in _MOBILE_XFAIL_PAGES:
        pytest.xfail(_MOBILE_XFAIL_PAGES[mobile_key])

    page = request.getfixturevalue(page_fixture)
    stub_leaflet(page)
    collector = RuntimeCollector(page, live_server)

    page.goto(
        f"{live_server}{sweep.path}",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_selector(sweep.ready_marker, timeout=10000)
    page.wait_for_timeout(300)
    _install_observer(page)

    descriptors = _enumerate_candidates(page)
    assert descriptors, f"no clickable candidates discovered on {sweep.path}"

    # Pre-navigation state for quick regression: if a click navigates away,
    # we restore the sweep page before the next click instead of clicking
    # controls that no longer exist on a different page.
    clicks_performed = 0
    silent_failures: list[str] = []
    click_errors: list[str] = []

    for descriptor in descriptors[:_MAX_CLICKS_PER_PAGE]:
        # Re-resolve: a previous click may have re-rendered the DOM.
        locator = page.locator(f"[data-clicksweep-id='{descriptor['id']}']").first
        if locator.count() == 0:
            continue
        before, after = _click_one(page, descriptor)
        clicks_performed += 1
        if "click_error" in after:
            click_errors.append(
                f"{descriptor['tag']} '{descriptor['text']}': {after['click_error']}"
            )
            _reset_page_state(page, live_server, sweep)
            continue
        if not _observable_change(before, after) and not descriptor.get(
            "tolerateNoChange"
        ):
            silent_failures.append(
                f"{descriptor['tag']} '{descriptor['text']}' "
                f"(action={descriptor.get('hasAction')}, href={descriptor.get('href')})"
            )
        # If the click navigated away (to another page on our origin), bring
        # us back so the rest of the sweep runs against the intended page.
        if before["url"] != after["url"]:
            _reset_page_state(page, live_server, sweep)

    assert clicks_performed > 0, (
        f"{sweep.path}: enumerated {len(descriptors)} candidates but clicked "
        f"none — selectors likely stale."
    )

    # Bubble up runtime signals captured by the collector.
    assert not collector.page_errors, (
        f"{sweep.path}: pageerror(s) during click sweep: "
        f"{collector.page_errors[:5]}"
    )
    assert not collector.console_errors, (
        f"{sweep.path}: console.error during click sweep: "
        f"{collector.console_errors[:5]}"
    )
    server_5xx = [
        r for r in collector.response_failures if 500 <= int(r.get("status", 0)) < 600
    ]
    assert (
        not server_5xx
    ), f"{sweep.path}: click sweep triggered 5xx response(s): {server_5xx[:5]}"

    # Silent no-op clicks are the *point* of this test — fail loudly so
    # they show up in CI. If a page needs a grace period while L2 cleans
    # up handlers, add it to ``_XFAIL_PAGES`` above with a JTN-??? link.
    assert not silent_failures, (
        f"{sweep.path}: {len(silent_failures)} click(s) produced no observable "
        f"change (URL/DOM/network/modal). Candidates: {silent_failures[:10]}"
    )

    # Click errors (Playwright timeouts etc.) are rarer than silent no-ops
    # but still worth surfacing — usually means the element moved during
    # the click and the locator couldn't land.
    assert (
        not click_errors
    ), f"{sweep.path}: {len(click_errors)} click(s) errored: {click_errors[:5]}"
