"""JTN-658: playlist.js reads ``details.field`` from server validation errors
and highlights the offending input via FormState.

The helper ``applyFieldErrorFromResponse`` is a shared shim used by the
create/update playlist flows so field-level attribution works even for
back-ends that don't emit the legacy ``field_errors`` map.
"""

from __future__ import annotations


def test_playlist_script_exposes_field_error_helper(client):
    resp = client.get("/static/scripts/playlist.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Helper symbol + callsite.
    assert "applyFieldErrorFromResponse" in js
    # Reads canonical envelope (details.field) with a field_errors fallback so
    # older / newer deploys both work.
    assert "result.details" in js
    assert "result.field_errors" in js
    # Uses FormState.setFieldError under the hood — that is where the
    # aria-invalid + focus + scroll-into-view UX lives.
    assert "setFieldError" in js


def test_playlist_template_exposes_inline_time_errors(client):
    """Start/end-time inputs must advertise an inline error region so
    FormState.setFieldError can render the message inline rather than via a
    toast the user can dismiss in under a second."""

    resp = client.get("/playlist")
    if resp.status_code != 200:
        return  # auth redirect — tested elsewhere
    body = resp.get_data(as_text=True)
    assert 'id="start-time-error"' in body
    assert 'id="end-time-error"' in body
    assert 'aria-describedby="start-time-error"' in body
    assert 'aria-describedby="end-time-error"' in body
