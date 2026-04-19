"""Tests for HTML5 client-side validation enforcement on the Settings Save button (JTN-350).

Background
----------
Before the fix, the settings page JS only checked dirty-state in ``checkDirty``
and ``handleAction`` shipped the form to the server without ever calling
``form.checkValidity()``. Users could clear ``deviceName`` (a ``required``
field) or set ``interval=-5`` (which has ``min="1"``) and the only feedback
they received was a server-side error toast — never the browser's native
HTML5 validation popup.

These static-analysis tests pin the fix in place by verifying that:

1. ``checkDirty`` calls ``checkValidity`` (or its helper) so the button
   remains disabled while the form is invalid.
2. ``handleAction`` calls ``checkValidity`` and ``reportValidity`` to trigger
   the native browser balloon and bail out before contacting the server.
3. The ``settings.html`` template still declares the HTML5 constraints that
   the JS now enforces (regression guard for the inputs the bug exercised).
"""

from pathlib import Path

JS_PATH = Path("src/static/scripts/settings/form.js")
HTML_PATH = Path("src/templates/settings.html")


def _read_js() -> str:
    return JS_PATH.read_text()


def _read_html() -> str:
    return HTML_PATH.read_text()


def test_check_dirty_enforces_form_validity():
    """JTN-350: Save must stay disabled while ``form.checkValidity()`` is false.

    The dirty-check is the gate that enables the Save button as the user
    edits the form. After JTN-350 it must also require validity, otherwise
    the button enables on the first keystroke even when ``deviceName`` is
    blank or ``interval`` is negative.
    """
    js = _read_js()
    # The fix introduces an isFormValid helper that wraps form.checkValidity().
    assert "isFormValid" in js, "Expected an isFormValid helper guarding Save"
    assert "form.checkValidity()" in js, (
        "checkDirty must consult form.checkValidity() so the Save button "
        "stays disabled while the form violates HTML5 constraints"
    )
    # And the disabled assignment must combine dirty AND validity.
    assert "dirty && isFormValid()" in js, (
        "Save button must be enabled only when the form is BOTH dirty and "
        "valid; otherwise users can still click Save with bad input"
    )


def test_handle_action_calls_report_validity_before_submit():
    """JTN-350: handleAction must trigger the browser's native popup on click.

    Even when the disabled gate is bypassed (e.g. by programmatic click),
    handleAction must call reportValidity() to show the native :invalid
    balloon and return early before fetching the save endpoint.
    """
    js = _read_js()
    assert "form.reportValidity()" in js, (
        "handleAction must call form.reportValidity() so users see the "
        "native HTML5 validation popup on Save click"
    )
    # The reportValidity call must precede the fetch — verify ordering.
    report_idx = js.find("form.reportValidity()")
    fetch_idx = js.find("config.saveSettingsUrl")
    assert report_idx != -1 and fetch_idx != -1
    assert report_idx < fetch_idx, (
        "reportValidity must run BEFORE the save fetch so the server is "
        "never contacted with invalid form data"
    )


def test_handle_action_focuses_first_invalid_field():
    """The first ``:invalid`` field should receive focus when Save is blocked."""
    js = _read_js()
    assert ":invalid" in js, (
        "handleAction should query for ':invalid' to focus the first "
        "invalid field after blocking submission"
    )


def test_settings_form_declares_required_constraints():
    """Regression guard: the constraints the JS now enforces must still exist.

    If a future refactor strips ``required`` from ``deviceName`` or ``min="1"``
    from ``interval``, the JS gate becomes a no-op and JTN-350 silently
    regresses. Pin the constraints here so that change is forced to be
    deliberate.
    """
    html = _read_html()
    # deviceName must remain required
    assert 'id="deviceName"' in html
    assert 'name="deviceName"' in html
    device_line = next(line for line in html.splitlines() if 'id="deviceName"' in line)
    assert "required" in device_line, "deviceName must remain required"

    # interval must remain required with min="1"
    interval_line = next(line for line in html.splitlines() if 'id="interval"' in line)
    assert "required" in interval_line, "interval must remain required"
    assert 'min="1"' in interval_line, 'interval must keep min="1"'
