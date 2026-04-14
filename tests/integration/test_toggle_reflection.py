# pyright: reportMissingImports=false
"""Toggle state-reflection sweep (Layer 3, Part C — JTN-688).

Parallel to :mod:`tests.integration.test_click_sweep` but focused solely on
*toggle-like* interactive elements. For each `[role=switch]`,
`input[type=checkbox]`, `[data-toggle]`, `[data-collapsible-toggle]`,
`[data-playlist-toggle]` and element carrying `aria-pressed`:

1. Record reflected state before click — ``aria-checked``, ``aria-pressed``,
   ``aria-expanded``, ``checked`` property, ``class`` list, ``data-state``.
2. Click the element.
3. Assert at least one of those attrs/props/classes changed.

Toggles that trigger navigation or modal dialogs are filtered out so we only
exercise the *in-place* state-reflection path. Handlers that flip internal
state without updating the DOM are the exact failure mode that slipped the
L3b sweep in JTN-681; this closes that gap.
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

# Wait after each click to let any reflection handler commit to the DOM.
_CLICK_SETTLE_MS = 200

# Cap per page — we expect small toggle counts but a few pages (settings)
# expand to several collapsibles. 30 is comfortably above observed counts.
_MAX_TOGGLES_PER_PAGE = 30

# Enumerate every toggle-like candidate and return a descriptor list.
# Filters out toggles that would navigate away or trigger a modal — those are
# covered by the dedicated click-sweep and modal-lifecycle tests.
_ENUMERATE_JS = """
() => {
  const isVisible = (el) => {
    if (!el.isConnected) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return false;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    if (parseFloat(style.opacity) === 0) return false;
    return true;
  };

  const selectors = [
    '[role="switch"]',
    'input[type="checkbox"]',
    '[data-toggle]',
    '[data-collapsible-toggle]',
    '[data-playlist-toggle]',
    '[aria-pressed]',
  ];
  const candidates = new Set();
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) candidates.add(el);
  }

  const descriptors = [];
  let idx = 0;
  for (const el of candidates) {
    if (!isVisible(el)) continue;
    if (el.disabled) continue;
    if (el.getAttribute('aria-disabled') === 'true') continue;
    // Skip explicit opt-outs the same way click_sweep does.
    if (el.getAttribute('data-test-skip-click') === 'true') continue;
    // Skip toggles that navigate: anchors with real hrefs, or elements
    // whose data-* handlers are known to open modals.
    if (el.tagName === 'A') {
      const href = el.getAttribute('href');
      if (href && href !== '#' && !href.startsWith('#')) continue;
    }
    // File inputs render as checkboxes in some libraries but aren't toggles.
    if (el.tagName === 'INPUT' && el.type !== 'checkbox') continue;
    // Skip things that will open a dialog — out of scope for in-place reflection.
    if (el.hasAttribute('data-modal-open')) continue;
    if (el.hasAttribute('data-open-modal')) continue;

    const marker = `__togglesweep_${idx++}`;
    el.setAttribute('data-togglesweep-id', marker);
    descriptors.push({
      id: marker,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      role: el.getAttribute('role') || '',
      text: (el.innerText || el.getAttribute('aria-label') ||
             el.getAttribute('name') || el.id || el.title || '')
              .trim().slice(0, 60),
    });
  }
  return descriptors;
}
"""


# Capture the reflected-state fields we care about for a given element.
_STATE_JS = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  return {
    ariaChecked: el.getAttribute('aria-checked'),
    ariaPressed: el.getAttribute('aria-pressed'),
    ariaExpanded: el.getAttribute('aria-expanded'),
    checked: (typeof el.checked === 'boolean') ? el.checked : null,
    classList: Array.from(el.classList).sort().join(' '),
    dataState: el.getAttribute('data-state'),
  };
}
"""


def _enumerate(page) -> list[dict]:
    return page.evaluate(_ENUMERATE_JS)


def _state(page, marker: str) -> dict | None:
    return page.evaluate(_STATE_JS, f"[data-togglesweep-id='{marker}']")


def _state_changed(before: dict, after: dict) -> bool:
    """True if any reflected-state field differs between snapshots."""
    for key in (
        "ariaChecked",
        "ariaPressed",
        "ariaExpanded",
        "checked",
        "classList",
        "dataState",
    ):
        if before.get(key) != after.get(key):
            return True
    return False


def _click_toggle(page, descriptor: dict) -> tuple[dict | None, dict | None]:
    marker = descriptor["id"]
    selector = f"[data-togglesweep-id='{marker}']"
    before = _state(page, marker)
    # Dispatch a click via the element itself. This matches the "did the
    # handler fire?" intent and avoids hit-test issues where a sibling
    # overlay (e.g. `.toggle-label` covering `.toggle-checkbox`) intercepts
    # coordinate-based Playwright clicks. Native `element.click()` on an
    # `<input type="checkbox">` flips `checked` then fires `click`/`change`.
    try:
        page.evaluate("(sel) => document.querySelector(sel)?.click()", selector)
    except Exception:  # noqa: BLE001
        # Last-ditch: try Playwright's own click with force=True.
        try:
            page.locator(selector).first.click(
                timeout=2000, force=True, no_wait_after=True
            )
        except Exception:  # noqa: BLE001
            return before, None
    page.wait_for_timeout(_CLICK_SETTLE_MS)
    after = _state(page, marker)
    return before, after


# Pages where the initial sweep uncovered a real state-reflection bug that
# needs a separate fix. Each entry MUST link to a tracking Linear issue.
_XFAIL_PAGES: dict[str, str] = {
    # JTN-692: .playlist-toggle-button is visible on desktop but clicking
    # never changes aria-expanded / label — `setPlaylistExpanded` short-
    # circuits for non-mobile viewports.
    "playlist": (
        "awaiting JTN-692 " "(playlist-toggle-button is a visible no-op on desktop)"
    ),
}


@pytest.mark.parametrize("sweep", PAGES_TO_SWEEP, ids=lambda sweep: sweep.label)
def test_toggle_reflection(live_server, browser_page, sweep: SweepPage):
    """Every toggle on the page must change its reflected DOM state on click."""
    if sweep.label in _XFAIL_PAGES:
        pytest.xfail(_XFAIL_PAGES[sweep.label])

    page = browser_page
    stub_leaflet(page)
    collector = RuntimeCollector(page, live_server)

    page.goto(
        f"{live_server}{sweep.path}",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_selector(sweep.ready_marker, timeout=10000)
    page.wait_for_timeout(300)

    descriptors = _enumerate(page)

    # Some pages (e.g. /history, /api-keys) legitimately have no toggles —
    # that's not a failure, just skip cleanly so the test still documents
    # the coverage intent.
    if not descriptors:
        pytest.skip(f"no toggle-like candidates discovered on {sweep.path}")

    silent_failures: list[str] = []
    click_errors: list[str] = []

    for descriptor in descriptors[:_MAX_TOGGLES_PER_PAGE]:
        locator = page.locator(f"[data-togglesweep-id='{descriptor['id']}']").first
        if locator.count() == 0:
            continue
        before, after = _click_toggle(page, descriptor)
        if before is None or after is None:
            click_errors.append(
                f"{descriptor['tag']}[{descriptor.get('type') or descriptor.get('role')}]"
                f" '{descriptor['text']}': click/state lookup failed"
            )
            continue
        if not _state_changed(before, after):
            silent_failures.append(
                f"{descriptor['tag']}[{descriptor.get('type') or descriptor.get('role')}]"
                f" '{descriptor['text']}': state unchanged "
                f"(before={before}, after={after})"
            )

    # Surface runtime signals the same way click_sweep does so JS errors
    # triggered by toggle handlers fail the test loudly. Resource-load
    # console errors (missing images/scripts) are orthogonal to the
    # state-reflection contract this test covers, so we ignore them — the
    # dedicated route smoke and click-sweep tests catch those.
    assert not collector.page_errors, (
        f"{sweep.path}: pageerror(s) during toggle sweep: "
        f"{collector.page_errors[:5]}"
    )
    js_errors = [
        e for e in collector.console_errors if "Failed to load resource" not in e
    ]
    assert (
        not js_errors
    ), f"{sweep.path}: console.error during toggle sweep: {js_errors[:5]}"

    assert not silent_failures, (
        f"{sweep.path}: {len(silent_failures)} toggle(s) did not reflect "
        f"state change in DOM. Candidates: {silent_failures[:10]}"
    )
    assert not click_errors, (
        f"{sweep.path}: {len(click_errors)} toggle click(s) errored: "
        f"{click_errors[:5]}"
    )
