"""Tests for HTML5 client-side validation enforcement on the Settings Save button (JTN-350).

Background
----------
Before the fix, ``settings_page.js`` only checked dirty-state in ``checkDirty``
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

JS_PATH = Path("src/static/scripts/settings_page.js")
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


def test_device_name_declares_client_side_length_cap():
    """JTN-780: the browser must cap deviceName at the server's 64-char limit.

    Before this fix the server enforced a 64-char cap (JTN-746) but the
    template omitted ``maxlength``, so a user could paste hundreds of
    characters and only discover the problem via a 422 response. Pin the
    ``maxlength="64"`` attribute here so the two validation layers cannot
    drift apart silently.
    """
    html = _read_html()
    device_line = next(line for line in html.splitlines() if 'id="deviceName"' in line)
    assert 'maxlength="64"' in device_line, (
        'deviceName must declare maxlength="64" to mirror the server-side '
        "cap from JTN-746 — otherwise the browser silently accepts input "
        "that the server will reject with 422"
    )


def test_device_name_declares_control_char_pattern():
    """JTN-780: deviceName must forbid control chars (except tab) client-side.

    The server rejects names containing characters in Unicode category ``Cc``
    except ``\\t``. The HTML ``pattern`` attribute must mirror that set so
    the browser surfaces :invalid before the request reaches the server.
    """
    html = _read_html()
    device_line = next(line for line in html.splitlines() if 'id="deviceName"' in line)
    assert "pattern=" in device_line, (
        "deviceName must declare a pattern attribute so pasted control "
        "characters fail HTML5 validation instead of silently 422-ing on Save"
    )
    # The regex must forbid \x00-\x08 and \x0A-\x1F (i.e. everything up to
    # 0x1F except \t=0x09) plus DEL and C1 controls. Tab must remain allowed
    # because the server accepts it (see test_device_name_tab_is_allowed).
    assert (
        r"\u0000-\u0008" in device_line
    ), "pattern must exclude NUL through backspace (U+0000–U+0008)"
    assert r"\u000A-\u001F" in device_line, (
        "pattern must exclude LF through unit-separator (U+000A–U+001F) "
        "while leaving tab (U+0009) allowed to match the server"
    )
    assert r"\u007F" in device_line, "pattern must exclude DEL (U+007F)"
    assert (
        "title=" in device_line
    ), "pattern inputs should carry a title= for the native validation popup"


def test_handle_action_surfaces_field_level_validation_errors_inline():
    """JTN-780: server validation errors must render inline, not just in a toast.

    The ``_field_error`` helper in ``src/blueprints/settings/_config.py``
    emits ``{code: "validation_error", details: {field: <name>}}``. The
    handler must surface that message on the matching input so the user sees
    which field failed — a dismissable toast alone is not sufficient.
    """
    js = _read_js()
    assert 'result.code === "validation_error"' in js, (
        "handleAction must branch on the validation_error code so it can "
        "route the error message to the field that failed"
    )
    assert (
        "result.details.field" in js
    ), "handleAction must read details.field to target the inline error"
    assert "fs.setFieldError(" in js, (
        "handleAction must call FormState.setFieldError so the validation "
        "message lands next to the bad input (JTN-780)"
    )


def test_handle_action_preserves_bad_input_on_field_level_error():
    """JTN-780: when a field-level error is surfaced, don't erase the bad value.

    Pre-fix, every non-OK response restored the form from the last-known-good
    snapshot. That wiped the user's invalid input alongside the inline error,
    making the error message reference text the user could no longer see. The
    snapshot restore must be gated so field-level errors preserve user input.
    """
    js = _read_js()
    # There must be a guard that skips the snapshot restore when we've
    # already surfaced a field-level error.
    assert "fieldLevelError" in js, (
        "handleAction must track whether a field-level error was surfaced "
        "so the snapshot restore can be skipped (JTN-780)"
    )
    assert "if (!fieldLevelError)" in js, (
        "restoreFormFromSnapshot must be gated on !fieldLevelError so the "
        "user's bad input is preserved alongside the inline error message"
    )
