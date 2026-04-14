# pyright: reportMissingImports=false
"""Per-plugin Update Preview smoke test (JTN-691).

For each plugin in :data:`PLUGIN_FORM_INPUTS` this test:

1. Navigates to ``/plugin/<plugin_id>``.
2. Fills minimum-viable inputs from the per-plugin fixture dict.
3. Clicks the primary ``data-plugin-action="update_now"`` button
   ("Update Preview").
4. Asserts the ``#previewImage`` ``src`` actually changed after the click —
   the client-side ``refreshPreviewImage()`` cache-busts with ``?t=<ts>`` on
   successful ``/update_now``, so an unchanged src means the handler silently
   no-opped.
5. Inherits the client-log tripwire from ``conftest.py`` — any
   ``console.warn``/``console.error`` during the test automatically fails it.

This layer catches the class of bug surfaced in JTN-681 (clock face picker
click produced 200 responses but no visible change), which the existing
click-sweep missed because its DOM-mutation heuristic xfails on the clock
page.

Scope is deliberately small (3 plugins). Add coverage by extending
``PLUGIN_FORM_INPUTS`` in ``fixtures/plugin_inputs.py``.
"""

from __future__ import annotations

import os

import pytest
from tests.integration.browser_helpers import RuntimeCollector, stub_leaflet
from tests.integration.fixtures.plugin_inputs import (
    PLUGIN_FORM_INPUTS,
    fill_form_inputs,
)

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


# Playwright wait budgets. The update_now POST is synchronous on the dev
# server path (refresh task off), so the preview src flip happens ~250 ms
# after the POST returns (see plugin_page.js::handleAction).
_UPDATE_PREVIEW_TIMEOUT_MS = 15000


def _preview_src(page) -> str | None:
    """Return the current ``#previewImage`` src (or None if missing)."""
    return page.evaluate(
        "() => document.getElementById('previewImage')?.getAttribute('src') || null"
    )


@pytest.mark.parametrize(
    "plugin_id",
    sorted(PLUGIN_FORM_INPUTS.keys()),
    ids=lambda pid: pid,
)
def test_update_preview_changes_image_src(
    live_server, browser_page, flask_app, monkeypatch, plugin_id: str
):
    """Update Preview must flip ``#previewImage`` src for each plugin.

    We force the refresh task OFF so ``/update_now`` takes the direct path
    and stub the display driver so no physical hardware is touched. The
    plugin's real ``generate_image`` still runs, which is the whole point —
    we are verifying the plugin-level preview loop produces an observable
    UI change, not mocking it away.
    """
    # Direct update_now path — skip the background refresh queue.
    flask_app.config["REFRESH_TASK"].running = False

    # Stub the physical display so the real DisplayManager._save_history_entry
    # still runs (sidecar JSON, preview file write) without hitting hardware.
    dm = flask_app.config["DISPLAY_MANAGER"]
    monkeypatch.setattr(dm.display, "display_image", lambda *a, **kw: None)

    page = browser_page
    stub_leaflet(page)
    collector = RuntimeCollector(page, live_server)

    page.goto(
        f"{live_server}/plugin/{plugin_id}",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_selector("#settingsForm", timeout=10000)
    page.wait_for_selector("#previewImage", timeout=10000)

    fill_form_inputs(page, PLUGIN_FORM_INPUTS[plugin_id])

    before_src = _preview_src(page)
    assert (
        before_src is not None
    ), f"{plugin_id}: #previewImage missing src attribute on load"

    update_btn = page.locator('[data-plugin-action="update_now"]').first
    assert (
        update_btn.count() > 0
    ), f"{plugin_id}: no Update Preview button on /plugin/{plugin_id}"
    update_btn.wait_for(state="visible", timeout=5000)
    # Click with `force=True` in case the workflow-mode panel keeps the
    # button briefly covered by a transition — matches the click-sweep
    # pattern and avoids flakes on slow CI boxes.
    update_btn.click(timeout=5000, force=True)

    # Wait for refreshPreviewImage() to swap in the cache-busted src.
    # The handler posts to /update_now, then on success schedules a 250 ms
    # setTimeout before updating the src — budget generously for CI.
    page.wait_for_function(
        """
        (prev) => {
          const img = document.getElementById('previewImage');
          return img && img.getAttribute('src') !== prev;
        }
        """,
        arg=before_src,
        timeout=_UPDATE_PREVIEW_TIMEOUT_MS,
    )

    after_src = _preview_src(page)
    assert after_src and after_src != before_src, (
        f"{plugin_id}: #previewImage src did not change after Update Preview "
        f"(before={before_src!r}, after={after_src!r}) — handler likely "
        "silently no-opped."
    )

    # Runtime tripwires: no JS errors / 5xx during the click. The autouse
    # client_log_capture fixture in conftest.py handles console.warn/error.
    assert not collector.page_errors, (
        f"{plugin_id}: pageerror during Update Preview: " f"{collector.page_errors[:3]}"
    )
    assert not collector.console_errors, (
        f"{plugin_id}: console.error during Update Preview: "
        f"{collector.console_errors[:3]}"
    )
    server_5xx = [
        r for r in collector.response_failures if 500 <= int(r.get("status", 0)) < 600
    ]
    assert not server_5xx, (
        f"{plugin_id}: Update Preview triggered 5xx response(s): " f"{server_5xx[:3]}"
    )
