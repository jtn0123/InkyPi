# pyright: reportMissingImports=false
"""Regression test for JTN-681 — clock face picker silent click handler.

The Layer-3 click sweep (:mod:`tests.integration.test_click_sweep`) flagged
all four `.image-option` buttons on `/plugin/clock` as producing no observable
DOM change. Root cause: ``initClockFacePicker`` scoped its lookup of the
``primaryColor`` / ``secondaryColor`` inputs to the widget wrapper, but those
fields live in a sibling schema section on the plugin form. The early-return
guard (``if (!hidden || !primary || !secondary || !options.length) return``)
fired, so no click handler was ever attached and the initial ``.selected``
state was never applied.

This test exercises the handler directly so the regression is caught even if
the click sweep's observer heuristics ever drift.
"""

from __future__ import annotations

import os

import pytest
from tests.integration.browser_helpers import stub_leaflet

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)


def test_clock_face_picker_applies_selected_and_updates_colors(
    live_server, browser_page
):
    """Clicking a clock face button toggles `.selected` and syncs color inputs."""
    page = browser_page
    stub_leaflet(page)
    page.goto(
        f"{live_server}/plugin/clock",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_selector("#settingsForm", timeout=10000)
    page.wait_for_timeout(300)

    # Initial state: the hidden input should match the default face AND the
    # matching `.image-option` should carry the `.selected` class. Prior to
    # the fix neither was true because initClockFacePicker bailed out early.
    state = page.evaluate("""() => {
            const opts = document.querySelectorAll('#clock-face-selection .image-option');
            const hidden = document.querySelector('#selected-clock-face');
            return {
                hiddenValue: hidden?.value,
                selectedLabels: Array.from(opts)
                    .filter(o => o.classList.contains('selected'))
                    .map(o => o.dataset.faceName),
            };
        }""")
    assert state["hiddenValue"], "hidden selectedClockFace input has no value"
    assert state["selectedLabels"] == [state["hiddenValue"]], (
        "on load, the clock-face button matching the hidden input should be "
        f"marked .selected; got {state['selectedLabels']}"
    )

    # Clicking a different face must: toggle the `.selected` class over, sync
    # the hidden input value, AND push the face's preset colors into the
    # primaryColor/secondaryColor inputs that live in a sibling section.
    result = page.evaluate("""() => {
            const opts = Array.from(document.querySelectorAll('#clock-face-selection .image-option'));
            const target = opts.find(o => !o.classList.contains('selected'));
            if (!target) return {error: 'no unselected target'};
            target.click();
            return {
                targetFace: target.dataset.faceName,
                expectedPrimary: target.dataset.primaryColor,
                expectedSecondary: target.dataset.secondaryColor,
                selectedAfter: opts
                    .filter(o => o.classList.contains('selected'))
                    .map(o => o.dataset.faceName),
                hiddenAfter: document.querySelector('#selected-clock-face')?.value,
                primaryAfter: document.querySelector("[name='primaryColor']")?.value,
                secondaryAfter: document.querySelector("[name='secondaryColor']")?.value,
            };
        }""")

    assert "error" not in result, result
    assert result["selectedAfter"] == [result["targetFace"]], (
        "clicking a face button must move the .selected class exclusively to "
        f"that option; got {result['selectedAfter']}"
    )
    assert result["hiddenAfter"] == result["targetFace"]
    # Color inputs normalize hex values to lowercase; compare case-insensitively.
    assert (
        result["primaryAfter"].lower() == result["expectedPrimary"].lower()
    ), f"primaryColor not synced: {result}"
    assert (
        result["secondaryAfter"].lower() == result["expectedSecondary"].lower()
    ), f"secondaryColor not synced: {result}"
