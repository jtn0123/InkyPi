# pyright: reportMissingImports=false
"""Visual-regression snapshot tests for key pages (JTN-700).

Unlike ``tests/integration/test_layout_overlap.py`` — which asserts only that
interactive elements don't physically overlap — these tests capture a pixel
screenshot of each key page at two viewports and diff it against a stored
baseline PNG.  This catches CSS regressions (spacing, alignment, color,
cut-off buttons) that all currently-green JS-level checks would happily
ignore.

Scope
-----
* Pages: dashboard (``/``), settings (``/settings``), history (``/history``),
  playlist (``/playlist``).
* Viewports: desktop (1280x900) and mobile (360x800).
* 4 x 2 = 8 parametrized combinations, each with its own baseline PNG.

Gating
------
The test is triple-gated so it never blocks contributors without a
reproducible rendering stack:

1. ``SKIP_VISUAL=1`` — opt-out for environments where baselines are known
   to be non-reproducible (e.g. local macOS dev where Chromium font
   fallback differs from CI Linux).
2. ``REQUIRE_BROWSER_SMOKE=1`` — the same gate the plugin snapshot suite
   uses; keeps visual snapshots out of the main ``Tests (pytest)`` matrix
   and limited to the ``Browser smoke`` CI job that installs Chromium.
3. Playwright Chromium must be launchable — probed at module import so
   environments without the browser cleanly skip rather than error at
   fixture setup time.

Tolerance
---------
Page screenshots are inherently noisier than the plugin golden-files
because they include anti-aliased text that drifts slightly between
Chromium builds and because backend state is only *mostly* deterministic.
Accordingly the layout snapshots use a more permissive tolerance than
plugin snapshots:

* ``VISUAL_CHANNEL_THRESHOLD`` (default ``12``): per-channel RGB delta
  below which a pixel is considered unchanged.
* ``VISUAL_MAX_CHANGED_PCT`` (default ``1.5``): up to 1.5% of pixels may
  exceed the channel threshold before the snapshot is considered a
  regression.

Both are overridable via environment variables of the same name so CI
lanes with different stability characteristics can tune without code
changes.  With a padding nudge of 4px on a key element, the real-world
changed-pixel percentage is ~3-5%, well above the 1.5% ceiling — the
acceptance test in the PR description verifies this empirically.

Updating baselines
------------------
Run inside the same Ubuntu 24.04 container the ``Browser smoke`` CI job
uses (see ``tests/snapshots/README.md`` for the docker one-liner), with
``--update-snapshots``.  The ``scripts/update_snapshots.py`` wrapper also
regenerates these baselines alongside the plugin ones.

Baselines live under ``tests/snapshots/layout/<page>/<page>_<viewport>.png``.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_TRUTHY = {"1", "true", "yes"}


def _env_bool(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Module-level skip decisions
# ---------------------------------------------------------------------------

_SKIP_VISUAL = _env_bool("SKIP_VISUAL")
_REQUIRE_BROWSER_SMOKE = _env_bool("REQUIRE_BROWSER_SMOKE")
_UPDATE_MODE = _env_bool("SNAPSHOT_UPDATE")


@lru_cache(maxsize=1)
def _playwright_chromium_available() -> bool:
    """Return True only when a real Chromium binary is launchable."""
    try:  # pragma: no cover - best-effort probe
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            browser.close()
        return True
    except Exception:
        return False


def _skip_reason() -> str | None:
    if _SKIP_VISUAL:
        return (
            "Visual-regression snapshots skipped via SKIP_VISUAL=1 "
            "(see tests/integration/test_visual_regression.py)."
        )
    if not _REQUIRE_BROWSER_SMOKE:
        return (
            "Visual-regression snapshots require Chromium + stable fonts. "
            "Set REQUIRE_BROWSER_SMOKE=1 to opt in (see tests/snapshots/README.md)."
        )
    if not _playwright_chromium_available():
        return (
            "Playwright Chromium is not installed. Run "
            "`python -m playwright install chromium` to enable visual snapshots."
        )
    return None


pytestmark = pytest.mark.skipif(
    _skip_reason() is not None, reason=_skip_reason() or "visual regression gate"
)


# ---------------------------------------------------------------------------
# Page / viewport matrix
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisualPage:
    """One page to snapshot, with a marker selector we wait for before firing."""

    label: str
    path: str
    ready_marker: str


@dataclass(frozen=True)
class Viewport:
    label: str
    width: int
    height: int


PAGES: tuple[VisualPage, ...] = (
    VisualPage("dashboard", "/", "#previewImage"),
    VisualPage("settings", "/settings", ".settings-console-layout"),
    VisualPage("history", "/history", "#storage-block"),
    VisualPage("playlist", "/playlist", "#newPlaylistBtn"),
)

VIEWPORTS: tuple[Viewport, ...] = (
    Viewport("desktop", 1280, 900),
    Viewport("mobile", 360, 800),
)


# ---------------------------------------------------------------------------
# Baseline storage + diff
# ---------------------------------------------------------------------------

_SNAPSHOT_ROOT = Path(__file__).resolve().parents[1] / "snapshots" / "layout"
_ACTUAL_ROOT = _SNAPSHOT_ROOT / "actual"


def _baseline_path(page: str, viewport: str) -> Path:
    return _SNAPSHOT_ROOT / page / f"{page}_{viewport}.png"


def _artifact_paths(page: str, viewport: str) -> tuple[Path, Path, Path]:
    base = _ACTUAL_ROOT / page / f"{page}_{viewport}"
    return (
        base.with_suffix(".png"),
        base.with_suffix(".diff.png"),
        base.with_suffix(".diff.json"),
    )


def _channel_threshold() -> int:
    return max(0, _env_int("VISUAL_CHANNEL_THRESHOLD", 12))


def _max_changed_pct() -> float:
    # Percent, not fraction; 1.5 means up to 1.5% of pixels may exceed threshold.
    return max(0.0, _env_float("VISUAL_MAX_CHANGED_PCT", 1.5))


@dataclass(frozen=True)
class _DiffStats:
    total_pixels: int
    changed_pixels: int
    changed_pct: float
    max_channel_delta: int
    expected_size: tuple[int, int]
    actual_size: tuple[int, int]
    resized_actual: bool
    changed_mask: np.ndarray


def _compute_diff(
    expected: Image.Image, actual: Image.Image, threshold: int
) -> _DiffStats:
    exp = expected.convert("RGB")
    act = actual.convert("RGB")
    resized = False
    if act.size != exp.size:
        act = act.resize(exp.size, Image.Resampling.BICUBIC)
        resized = True

    exp_arr = np.asarray(exp, dtype=np.int16)
    act_arr = np.asarray(act, dtype=np.int16)
    channel_delta = np.abs(exp_arr - act_arr)
    per_pixel_max = channel_delta.max(axis=2)
    mask = per_pixel_max > threshold

    total = int(mask.size)
    changed = int(mask.sum())
    return _DiffStats(
        total_pixels=total,
        changed_pixels=changed,
        changed_pct=(changed / total * 100.0) if total else 0.0,
        max_channel_delta=int(per_pixel_max.max()) if total else 0,
        expected_size=expected.size,
        actual_size=actual.size,
        resized_actual=resized,
        changed_mask=mask,
    )


def _build_diff_overlay(expected: Image.Image, mask: np.ndarray) -> Image.Image:
    base = expected.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (255, 0, 0, 0))
    alpha = Image.fromarray((mask.astype(np.uint8) * 160), mode="L")
    overlay.putalpha(alpha)
    return Image.alpha_composite(base, overlay).convert("RGB")


def _assert_layout_snapshot(image: Image.Image, page: str, viewport: str) -> None:
    baseline = _baseline_path(page, viewport)
    actual_png, diff_png, stats_json = _artifact_paths(page, viewport)

    if _UPDATE_MODE:
        baseline.parent.mkdir(parents=True, exist_ok=True)
        image.save(baseline, format="PNG")
        return

    if not baseline.exists():
        raise FileNotFoundError(
            f"No baseline for layout/{page}/{page}_{viewport}. "
            f"Expected PNG at: {baseline}\n"
            "Run `pytest tests/integration/test_visual_regression.py "
            "--update-snapshots` to capture baselines."
        )

    with Image.open(baseline) as loaded:
        expected = loaded.copy()

    threshold = _channel_threshold()
    max_pct = _max_changed_pct()
    stats = _compute_diff(expected, image, threshold)

    size_mismatch = stats.expected_size != stats.actual_size
    within_tolerance = stats.changed_pct <= max_pct
    if not size_mismatch and within_tolerance:
        return

    actual_png.parent.mkdir(parents=True, exist_ok=True)
    image.save(actual_png, format="PNG")
    _build_diff_overlay(expected, stats.changed_mask).save(diff_png, format="PNG")
    stats_json.write_text(
        json.dumps(
            {
                "page": page,
                "viewport": viewport,
                "threshold": threshold,
                "max_changed_pct": max_pct,
                "total_pixels": stats.total_pixels,
                "changed_pixels": stats.changed_pixels,
                "changed_pct": round(stats.changed_pct, 6),
                "max_channel_delta": stats.max_channel_delta,
                "expected_size": list(stats.expected_size),
                "actual_size": list(stats.actual_size),
                "resized_actual_for_diff": stats.resized_actual,
                "size_mismatch": size_mismatch,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    reasons: list[str] = []
    if size_mismatch:
        reasons.append(
            f"size mismatch expected={stats.expected_size} actual={stats.actual_size}"
        )
    if not within_tolerance:
        reasons.append(
            f"{stats.changed_pct:.4f}% changed pixels exceeds allowed "
            f"{max_pct:.4f}% (threshold={threshold})"
        )

    raise AssertionError(
        f"Layout snapshot mismatch for {page}/{viewport}: "
        + "; ".join(reasons)
        + f"\n  Baseline : {baseline}\n"
        f"  Actual   : {actual_png}\n"
        f"  Diff     : {diff_png}\n"
        f"  Stats    : {stats_json}\n"
        "If this change is intentional, run `pytest "
        "tests/integration/test_visual_regression.py --update-snapshots`."
    )


# ---------------------------------------------------------------------------
# Determinism helpers
# ---------------------------------------------------------------------------

# CSS injected after DOM ready to mask volatile content (clocks, countdowns,
# refresh timestamps, the live preview image) so screenshots capture the
# *layout* rather than the current backend state. Dynamic regions collapse
# to a flat neutral fill that still occupies the same space — padding,
# alignment, and surrounding element positions remain visible.
_DETERMINISM_CSS = """
  /* Disable all animations / transitions so screenshots don't race a
     fade-in or skeleton pulse. */
  *, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    caret-color: transparent !important;
  }
  /* Hide the scrollbar so window width == effective render width. */
  html, body { scrollbar-width: none !important; }
  html::-webkit-scrollbar, body::-webkit-scrollbar { display: none !important; }

  /* Mask the live-preview image: its bytes depend on current backend
     state and change on every refresh. Replace with a solid rectangle
     that still occupies the original rect. */
  #previewImage {
    visibility: hidden !important;
    background: #dfe3ea !important;
    min-height: 1px !important;
  }
  #previewImage + * { /* keeps sibling layout intact */ }

  /* Status / "now showing" / "next up" blocks surface timestamps,
     playlist names, and plugin instance ids that change per-run.
     Hide their inner text but keep the container so spacing holds. */
  #statusRow [aria-live="polite"] > *,
  #imageMeta,
  #connectivityWarning { color: transparent !important; }
  #statusRow [aria-live="polite"] > *::after,
  #imageMeta::after {
    content: "" !important;
  }

  /* Refresh-info + next-up widgets render "in 2m 14s" etc. */
  [data-refresh-countdown],
  [data-eta],
  .refresh-countdown,
  .next-up-countdown { color: transparent !important; }

  /* History page: the storage card shows live disk-usage stats ("23.0%
     FREE", "7.18 GB remaining of 31.32 GB total") plus a proportional
     meter fill. Both vary massively between a local dev machine and the
     GitHub runner (e.g. 23% local vs 61% CI), so mask their content but
     keep the container rectangles to preserve layout. */
  #storage-text { color: transparent !important; }
  .page-summary .status-chip:not(.info) { color: transparent !important; }
  #storage-bar-inner {
    /* Pin the fill to a deterministic width + flat color so the meter's
       rendered shape matches across hosts regardless of actual disk
       usage. Overrides the inline --meter-width style. */
    width: 50% !important;
    background: #dfe3ea !important;
    background-image: none !important;
  }
"""


def _stub_network(page) -> None:
    """Prevent CDN / external requests that could jitter the layout.

    Reuses the leaflet stub from browser_helpers for settings pages that
    embed a map, and blanket-fails any remaining external requests so a
    flaky network doesn't poison the baseline.
    """
    from tests.integration.browser_helpers import stub_leaflet

    stub_leaflet(page)

    def _abort_external(route):
        url = route.request.url
        if url.startswith(("http://127.0.0.1", "http://localhost")):
            route.continue_()
            return
        if url.startswith(("data:", "blob:")):
            route.continue_()
            return
        # External request during a layout snapshot — abort silently so
        # the page still renders without waiting for the timeout.
        route.abort()

    page.route("**/*", _abort_external)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=lambda v: v.label)
@pytest.mark.parametrize("page_spec", PAGES, ids=lambda p: p.label)
def test_visual_regression(live_server, page_spec: VisualPage, viewport: Viewport):
    """Diff a page screenshot against its stored layout baseline.

    One test per (page, viewport) pair — pytest parametrize ids produce
    human-readable node names like ``test_visual_regression[dashboard-desktop]``
    so individual regressions are easy to rerun.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # device_scale_factor=1 pins DPI so macOS retina runs don't double
        # the image dimensions vs Linux CI.
        context = browser.new_context(
            viewport={"width": viewport.width, "height": viewport.height},
            device_scale_factor=1,
            reduced_motion="reduce",
        )
        page = context.new_page()
        try:
            _stub_network(page)
            page.goto(
                f"{live_server}{page_spec.path}",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            page.wait_for_selector(page_spec.ready_marker, timeout=10000)

            # Inject determinism CSS AFTER the page shell has loaded so
            # nothing in base.html gets a chance to override our !important
            # rules.
            page.add_style_tag(content=_DETERMINISM_CSS)

            # Allow late layout (webfont swap, plugin grid population,
            # settings tabs) to settle. The existing layout-overlap test
            # waits 400ms; we wait slightly longer since screenshots are
            # more sensitive to mid-flight reflow.
            page.wait_for_timeout(600)
            # Belt-and-suspenders: wait for fonts to finish loading.
            page.evaluate("() => document.fonts && document.fonts.ready")

            png_bytes = page.screenshot(full_page=False, type="png")
        finally:
            context.close()
            browser.close()

    image = Image.open(io.BytesIO(png_bytes))
    _assert_layout_snapshot(image, page_spec.label, viewport.label)
