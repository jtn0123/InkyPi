# pyright: reportMissingImports=false
"""Form round-trip persistence tests (JTN-690).

Each test captures the current values on a form, fills known-good test
values, submits, navigates away to a different route, navigates back,
and asserts the fields are re-populated with the submitted values. The
fixture always restores the original baseline so the test is idempotent
even if it fails mid-way.

This layer catches the "POST returns 200 but nothing was actually
saved" class of bug — a silent persistence regression that none of the
existing UI audit layers (handler audit, click-sweep, client-log
tripwire, a11y) would surface.

The `live_server` fixture is backed by a `tmp_path` device config
(see ``tests/conftest.py::device_config_dev``), so these tests never
touch the developer's real config file — but the save/restore
round-trip is still performed explicitly so the test also validates on
a shared config file (the state goes through the real POST handler and
comes back through the real GET template render).
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402

# ---------------------------------------------------------------------------
# Per-field helpers
# ---------------------------------------------------------------------------


def _expand_all_collapsibles(page) -> None:
    """Force every ``.collapsible-content`` visible so hidden inputs are reachable."""
    page.evaluate("""() => {
            document.querySelectorAll('.collapsible-content').forEach((el) => {
                el.hidden = false;
                el.removeAttribute('hidden');
                el.style.display = 'block';
            });
            document.querySelectorAll('[data-collapsible-toggle]').forEach((btn) => {
                btn.setAttribute('aria-expanded', 'true');
            });
        }""")


def _read_field(page, field_id: str, *, kind: str) -> str | bool:
    """Return the current value for a field by id."""
    loc = page.locator(f"#{field_id}")
    loc.wait_for(state="attached", timeout=5000)
    if kind == "checkbox":
        # ``is_checked`` works on attached-but-hidden inputs too, but we
        # also fall back to reading the DOM property directly to avoid
        # any visibility-based retry.
        return bool(
            page.evaluate(
                "(sel) => !!document.querySelector(sel)?.checked",
                f"#{field_id}",
            )
        )
    if kind == "radio":
        # ``#{field_id}`` is the first radio in the group by convention;
        # the group's checked value is the value of whichever sibling
        # radio (same ``name``) carries ``checked``.
        return page.evaluate(
            """(sel) => {
                const anchor = document.querySelector(sel);
                if (!anchor || !anchor.name) return "";
                const checked = document.querySelector(
                    `input[type="radio"][name="${anchor.name}"]:checked`
                );
                return checked ? checked.value : "";
            }""",
            f"#{field_id}",
        )
    return loc.input_value()


def _write_field(page, field_id: str, value, *, kind: str) -> None:
    """Set ``field_id`` to ``value`` using the appropriate input primitive.

    Uses direct DOM manipulation + dispatched events rather than
    Playwright's interaction primitives, because many settings inputs
    live inside collapsed ``<div hidden>`` sections and Playwright
    treats those as non-actionable. We explicitly expand all
    collapsibles before each write, but go through ``evaluate`` anyway
    to keep the helper robust to future layout changes.
    """
    _expand_all_collapsibles(page)
    loc = page.locator(f"#{field_id}")
    loc.wait_for(state="attached", timeout=5000)
    if kind == "text":
        page.evaluate(
            """([sel, val]) => {
                const el = document.querySelector(sel);
                el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            [f"#{field_id}", str(value)],
        )
    elif kind == "select":
        loc.select_option(str(value))
    elif kind == "slider":
        page.evaluate(
            """([sel, val]) => {
                const el = document.querySelector(sel);
                el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            [f"#{field_id}", str(value)],
        )
    elif kind == "checkbox":
        page.evaluate(
            """([sel, checked]) => {
                const el = document.querySelector(sel);
                if (el.checked !== checked) {
                    el.checked = checked;
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }""",
            [f"#{field_id}", bool(value)],
        )
    elif kind == "radio":
        # Select the sibling radio matching ``value`` in the group anchored
        # at ``#{field_id}``. Dispatching ``change`` triggers the form
        # dirty-state tracker that gates the Save button.
        page.evaluate(
            """([sel, val]) => {
                const anchor = document.querySelector(sel);
                if (!anchor || !anchor.name) return;
                const target = document.querySelector(
                    `input[type="radio"][name="${anchor.name}"][value="${val}"]`
                );
                if (target) {
                    target.checked = true;
                    target.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }""",
            [f"#{field_id}", str(value)],
        )
    else:
        raise ValueError(f"Unknown field kind: {kind}")


def _save_settings(page) -> None:
    _expand_all_collapsibles(page)
    save_btn = page.locator("#saveSettingsBtn")
    save_btn.wait_for(state="attached", timeout=5000)
    # Click via evaluate so visibility checks don't trip us up if the
    # button lives outside the active settings side-nav section.
    page.evaluate("document.getElementById('saveSettingsBtn').click()")
    # Wait for the POST to complete.
    page.wait_for_timeout(1500)


# ---------------------------------------------------------------------------
# Round-trip driver
# ---------------------------------------------------------------------------


# Tuple layout: (field_id, kind, test_value)
# kind in {"text", "select", "slider", "checkbox", "radio"}
SETTINGS_FIELDS = [
    ("deviceName", "text", "RoundTripDevice"),
    ("timezone", "text", "US/Pacific"),
    # Orientation was migrated from <select> to a segmented-radio control;
    # ``#orientation`` is the first radio in the group (value=horizontal),
    # and the ``radio`` kind knows how to pick any sibling by ``value``.
    ("orientation", "radio", "vertical"),
    ("saturation", "slider", "1.4"),
    ("invertImage", "checkbox", True),
]


@contextmanager
def _restore_after(page, live_server, fields):
    """Capture baseline for ``fields`` now, yield, then restore on exit."""
    navigate_and_wait(page, live_server, "/settings")
    baseline = {fid: _read_field(page, fid, kind=kind) for fid, kind, _ in fields}
    try:
        yield baseline
    finally:
        try:
            navigate_and_wait(page, live_server, "/settings")
            for fid, kind, _ in fields:
                _write_field(page, fid, baseline[fid], kind=kind)
            _save_settings(page)
        except Exception:
            # Teardown restore is best-effort; the `live_server` config is
            # already isolated per-test via tmp_path, so a restore failure
            # cannot leak into the developer's real config.
            pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_settings_form_roundtrip(live_server, browser_page):
    """Submit /settings values, navigate away, return, confirm persistence."""
    page = browser_page

    with _restore_after(page, live_server, SETTINGS_FIELDS):
        # 1-3: navigate + fill with known-good values.
        navigate_and_wait(page, live_server, "/settings")
        for fid, kind, value in SETTINGS_FIELDS:
            _write_field(page, fid, value, kind=kind)

        # 4: submit.
        _save_settings(page)

        # 5: navigate away to a different route, then back. This exercises
        # the full re-render path (template pulls from on-disk config)
        # rather than any client-side in-memory state.
        navigate_and_wait(page, live_server, "/")
        navigate_and_wait(page, live_server, "/settings")

        # 6: assert the submitted values are re-populated.
        for fid, kind, expected in SETTINGS_FIELDS:
            actual = _read_field(page, fid, kind=kind)
            if kind == "checkbox":
                assert actual is bool(expected), (
                    f"{fid}: expected {expected!r}, got {actual!r} after "
                    "save + navigate-away + reload"
                )
            else:
                assert str(actual) == str(expected), (
                    f"{fid}: expected {expected!r}, got {actual!r} after "
                    "save + navigate-away + reload"
                )


def test_settings_form_roundtrip_uncheck_invert(live_server, browser_page):
    """Checkbox round-trip specifically for the unchecked state.

    HTML form submissions omit unchecked checkboxes from the payload — a
    common source of "setting un-toggle didn't stick" bugs. This test
    toggles the checkbox on, saves, then off, saves, and asserts that
    the off state re-populates after a round-trip navigation.
    """
    page = browser_page
    fields = [("invertImage", "checkbox", False)]

    with _restore_after(page, live_server, fields):
        # First turn it on and save so we're definitely starting from
        # the opposite state.
        navigate_and_wait(page, live_server, "/settings")
        _write_field(page, "invertImage", True, kind="checkbox")
        _save_settings(page)

        # Now turn it off, save, navigate away, return.
        navigate_and_wait(page, live_server, "/settings")
        _write_field(page, "invertImage", False, kind="checkbox")
        _save_settings(page)

        navigate_and_wait(page, live_server, "/")
        navigate_and_wait(page, live_server, "/settings")

        actual = _read_field(page, "invertImage", kind="checkbox")
        assert actual is False, (
            "invertImage: expected False after save + navigate-away + "
            f"reload, got {actual!r} — POST may have omitted the "
            "unchecked checkbox and the server kept the previous value."
        )
