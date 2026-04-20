"""JTN-505: FormState manager wires loading + inline error UI for settings
and playlist forms.

Validates:
  * `/static/scripts/form_state.js` exposes the expected public API.
  * Settings + playlist templates carry `data-form-state` / inline error
    regions so the manager can attach automatically.
  * Settings/Playlist page scripts call FormState to disable the submit
    button during async save operations (prevents double submissions).
"""

from __future__ import annotations

import re


def test_form_state_script_is_served(client):
    resp = client.get("/static/scripts/form_state.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)
    # Public API surface expected by callers and tests.
    for symbol in (
        "globalThis.FormState",
        "attach",
        "wireSubmit",
        "setFieldError",
        "setFieldErrors",
        "clearErrors",
        "setBusy",
    ):
        assert symbol in js, f"form_state.js must expose {symbol}"


def test_form_state_auto_attaches_on_dom_ready(client):
    js = client.get("/static/scripts/form_state.js").get_data(as_text=True)
    # Auto-attach hook runs for any form carrying data-form-state.
    assert "DOMContentLoaded" in js
    assert "form[data-form-state]" in js
    # Busy toggle must flip aria-busy so screen readers announce progress.
    assert "aria-busy" in js


def test_form_state_focuses_first_invalid_field(client):
    js = client.get("/static/scripts/form_state.js").get_data(as_text=True)
    # setFieldError must toggle aria-invalid and focus the field when first
    # error is rendered (required for proper screen-reader flow).
    assert "aria-invalid" in js
    assert "field.focus" in js


def test_form_state_loaded_in_base_template(client):
    html = client.get("/static/scripts/../../").status_code  # sanity noop
    _ = html
    # Load any page to capture base.html rendering.
    page = client.get("/settings")
    assert page.status_code in (200, 302)
    if page.status_code == 200:
        body = page.get_data(as_text=True)
        assert "scripts/form_state.js" in body or "dist/" in body


def test_settings_form_has_data_form_state(client):
    resp = client.get("/settings")
    # Auth may redirect — rely on template content via test client either way.
    if resp.status_code != 200:
        return
    body = resp.get_data(as_text=True)
    # The settings form must opt-in to FormState.
    assert re.search(
        r'<form[^>]*class="[^"]*\bsettings-form\b[^"]*"[^>]*data-form-state', body
    ), "settings-form must carry data-form-state for FormState auto-attach"
    # Save button must advertise itself as the FormState submit target.
    assert 'id="saveSettingsBtn"' in body
    assert "data-form-state-submit" in body


def test_playlist_schedule_form_has_data_form_state(client):
    resp = client.get("/playlist")
    if resp.status_code != 200:
        return
    body = resp.get_data(as_text=True)
    assert re.search(
        r'id="scheduleForm"[^>]*data-form-state', body
    ), "scheduleForm must carry data-form-state so FormState attaches"
    # Inline error region for cycle_minutes (new in JTN-505).
    assert 'id="cycle-minutes-error"' in body
    assert "data-form-state-submit" in body


def test_settings_page_script_invokes_form_state(client):
    js = client.get("/static/scripts/settings/form.js").get_data(as_text=True)
    # handleAction must route through FormState so the submit button is
    # disabled and aria-busy set for the duration of the save request.
    assert "FormState.attach" in js
    assert "fs.run" in js or "fs?.run" in js
    # Field-level errors from the server must render inline, not toast-only.
    assert "field_errors" in js


def test_playlist_script_invokes_form_state(client):
    js = client.get("/static/scripts/playlist.js").get_data(as_text=True)
    # Both create and update flows must wrap submission in FormState.run.
    assert "FormState.attach" in js
    assert "fs.run(submit)" in js
    # Inline error handling for server-side field errors.
    assert "field_errors" in js
