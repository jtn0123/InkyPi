# pyright: reportMissingImports=false
"""Interactive-element overlap / collision detector (Layer 3, Part C).

For each page in :data:`PAGES_TO_CHECK` and each viewport in
:data:`VIEWPORTS` this test:

1. Loads the page and waits for its ready marker.
2. Enumerates every visible interactive element (``button``, ``a``,
   ``input``, ``[role=button]``, ``[data-*-action]``) that has a non-zero
   bounding rect and is actually clickable (visibility visible, not
   ``pointer-events: none``, not ``aria-hidden``, not disabled).
3. For every pair of candidates, computes overlap area. A pair is flagged
   as a collision when ``overlap / min(area_a, area_b) > OVERLAP_THRESHOLD``
   **and** neither element is an ancestor/descendant of the other (nested
   buttons / icons inside buttons are legitimate).
4. Fails the test with a descriptive message listing the colliding
   selectors so the regression is obvious.

This catches the "this button is under the modal header" class of visual
bug without the maintenance cost of pixel-diff baselines. It runs at both
desktop (1280x900) and mobile (360x800) viewports to cover responsive
reflow bugs.

Gating: covered by the standard ``SKIP_UI`` / ``SKIP_BROWSER`` gates in
``tests/conftest.py``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


@dataclass(frozen=True)
class OverlapPage:
    """One page to check, with a marker selector we wait for before probing."""

    label: str
    path: str
    ready_marker: str


@dataclass(frozen=True)
class Viewport:
    label: str
    width: int
    height: int


PAGES_TO_CHECK: tuple[OverlapPage, ...] = (
    OverlapPage("home", "/", "#previewImage"),
    OverlapPage("settings", "/settings", ".settings-console-layout"),
    OverlapPage("history", "/history", "#storage-block"),
    OverlapPage("playlist", "/playlist", "#newPlaylistBtn"),
    OverlapPage("plugin_clock", "/plugin/clock", "#settingsForm"),
    OverlapPage("api_keys", "/api-keys", "#saveApiKeysBtn"),
)

VIEWPORTS: tuple[Viewport, ...] = (
    Viewport("desktop", 1280, 900),
    Viewport("mobile", 360, 800),
)

# Pair is flagged when overlap / min(area_a, area_b) exceeds this fraction.
# 0.25 is a conservative choice: tiny icons inside buttons still fail this
# threshold on their parent, but ancestor/descendant pairs are filtered out
# before the threshold is applied so that's not a false positive source.
OVERLAP_THRESHOLD = 0.25

# (page_label, viewport_label) combinations we've already triaged and filed
# separate Linear issues for. Each entry MUST link to a tracking issue so
# the xfail self-documents.
_XFAIL_COMBOS: dict[tuple[str, str], str] = {}


# Enumerate candidates and return each rect plus an ancestor chain of data
# markers so we can filter ancestor/descendant pairs in Python.
_ENUMERATE_JS = r"""
() => {
  const selectors = [
    'button', 'a', 'input', '[role=button]',
    '[data-plugin-action]', '[data-api-action]',
    '[data-settings-tab]', '[data-history-action]',
    '[data-collapsible-toggle]',
    '[data-playlist-toggle]', '[data-clock-action]',
  ];

  const isClickable = (el) => {
    if (!el.isConnected) return false;
    if (el.getAttribute('aria-hidden') === 'true') return false;
    if (el.disabled) return false;
    if (el.getAttribute('aria-disabled') === 'true') return false;
    // Walk up ancestors checking aria-hidden / inert / pointer-events.
    for (let node = el; node && node !== document.documentElement; node = node.parentElement) {
      if (node.getAttribute && node.getAttribute('aria-hidden') === 'true') return false;
      if (node.hasAttribute && node.hasAttribute('inert')) return false;
      const style = window.getComputedStyle(node);
      if (style.display === 'none') return false;
      if (style.visibility === 'hidden' || style.visibility === 'collapse') return false;
      if (parseFloat(style.opacity) === 0) return false;
      if (style.pointerEvents === 'none') return false;
    }
    return true;
  };

  // Tag each matching element with a stable attribute so we can later
  // refer to it in failure messages and reason about ancestry.
  const tagged = new Set();
  let idx = 0;
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      if (!tagged.has(el)) {
        el.setAttribute('data-overlap-id', '__overlap_' + idx++);
        tagged.add(el);
      }
    }
  }

  const descriptors = [];
  for (const el of tagged) {
    if (!isClickable(el)) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    // Skip inputs the user can't really "click" as a button (hidden,
    // checkbox/radio are legitimate tiny overlaps with labels).
    if (el.tagName === 'INPUT') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (type === 'hidden') continue;
    }

    // Build a string marker path from the element up to <body> using our
    // assigned data-overlap-id attributes. A pair of descriptors is an
    // ancestor/descendant pair iff one's marker appears in the other's
    // ancestorMarkers list.
    const ancestorMarkers = [];
    for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
      const m = node.getAttribute && node.getAttribute('data-overlap-id');
      if (m) ancestorMarkers.push(m);
    }

    const id = el.getAttribute('data-overlap-id');
    const label =
      (el.innerText || el.getAttribute('aria-label') || el.title ||
        el.getAttribute('name') || el.getAttribute('type') || '').trim().slice(0, 60);
    descriptors.push({
      id,
      tag: el.tagName.toLowerCase(),
      label,
      ancestorMarkers,
      rect: {
        x: rect.x, y: rect.y, width: rect.width, height: rect.height,
        right: rect.right, bottom: rect.bottom,
      },
    });
  }
  return descriptors;
}
"""


def _overlap_fraction(a: dict, b: dict) -> float:
    """Return overlap / min(area_a, area_b); 0 if no overlap."""
    ax1, ay1 = a["x"], a["y"]
    ax2, ay2 = a["right"], a["bottom"]
    bx1, by1 = b["x"], b["y"]
    bx2, by2 = b["right"], b["bottom"]
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = ix2 - ix1
    ih = iy2 - iy1
    if iw <= 0 or ih <= 0:
        return 0.0
    overlap_area = iw * ih
    area_a = max(a["width"] * a["height"], 1e-6)
    area_b = max(b["width"] * b["height"], 1e-6)
    return overlap_area / min(area_a, area_b)


def _is_ancestor_related(a: dict, b: dict) -> bool:
    """True iff a is an ancestor of b or vice-versa."""
    if a["id"] in b["ancestorMarkers"]:
        return True
    return b["id"] in a["ancestorMarkers"]


def _find_collisions(descriptors: list[dict]) -> list[tuple[dict, dict, float]]:
    collisions: list[tuple[dict, dict, float]] = []
    n = len(descriptors)
    for i in range(n):
        for j in range(i + 1, n):
            a = descriptors[i]
            b = descriptors[j]
            if _is_ancestor_related(a, b):
                continue
            frac = _overlap_fraction(a["rect"], b["rect"])
            if frac > OVERLAP_THRESHOLD:
                collisions.append((a, b, frac))
    return collisions


def _format_collision(a: dict, b: dict, frac: float) -> str:
    def describe(d: dict) -> str:
        rect = d["rect"]
        return (
            f"<{d['tag']} '{d['label']}' "
            f"@({rect['x']:.0f},{rect['y']:.0f} "
            f"{rect['width']:.0f}x{rect['height']:.0f})>"
        )

    return f"  {describe(a)}  <-{frac:.0%}->  {describe(b)}"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=lambda v: v.label)
@pytest.mark.parametrize("page_spec", PAGES_TO_CHECK, ids=lambda p: p.label)
def test_interactive_overlap(live_server, page_spec: OverlapPage, viewport: Viewport):
    """Flag pairs of clickables whose bounding boxes visually collide."""
    from playwright.sync_api import sync_playwright
    from tests.integration.browser_helpers import stub_leaflet

    combo_key = (page_spec.label, viewport.label)
    if combo_key in _XFAIL_COMBOS:
        pytest.xfail(_XFAIL_COMBOS[combo_key])

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": viewport.width, "height": viewport.height}
        )
        try:
            stub_leaflet(page)
            page.goto(
                f"{live_server}{page_spec.path}",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            page.wait_for_selector(page_spec.ready_marker, timeout=10000)
            # Allow late layout shifts (e.g. web-font swap, async widgets) to
            # settle before we freeze the bounding rects.
            page.wait_for_timeout(400)

            descriptors = page.evaluate(_ENUMERATE_JS)
        finally:
            browser.close()

    assert descriptors, (
        f"{page_spec.path} @ {viewport.label}: no interactive candidates "
        f"discovered — selectors may be stale."
    )

    collisions = _find_collisions(descriptors)
    if collisions:
        # Limit formatted output to the worst 10 pairs so CI failures stay
        # readable; sort by overlap fraction descending.
        collisions.sort(key=lambda c: c[2], reverse=True)
        top = collisions[:10]
        formatted = "\n".join(_format_collision(a, b, f) for a, b, f in top)
        pytest.fail(
            f"{page_spec.path} @ {viewport.label}: "
            f"{len(collisions)} interactive-element collision(s) "
            f"exceeding {OVERLAP_THRESHOLD:.0%} of the smaller element. "
            f"Worst offenders:\n{formatted}"
        )
