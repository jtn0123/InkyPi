"""Tests for JTN-311 and JTN-312: calendar plugin button bug fixes.

JTN-311: Remove calendar button must be disabled (not a silent no-op) when
         only one calendar row is present.
JTN-312: Last progress button must call a handler that makes progress visible,
         not leave the panel hidden due to the HTML `hidden` attribute.
"""

# ---------------------------------------------------------------------------
# JTN-311: Remove calendar button disabled when only one row
# ---------------------------------------------------------------------------


def test_plugin_schema_exposes_sync_remove_button_states(client):
    """JTN-311: plugin_schema.js must define syncRemoveButtonStates."""
    resp = client.get("/static/scripts/plugin_schema.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "syncRemoveButtonStates" in js, (
        "plugin_schema.js must define syncRemoveButtonStates so remove buttons "
        "are disabled when only one calendar row remains (JTN-311)"
    )


def test_sync_remove_button_states_disables_on_single_row(client):
    """JTN-311: syncRemoveButtonStates must set disabled=true when count <= 1."""
    resp = client.get("/static/scripts/plugin_schema.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # The function must disable buttons when there is only one row.
    assert "btn.disabled = onlyOne" in js or "disabled = onlyOne" in js, (
        "syncRemoveButtonStates must disable remove buttons when only one row "
        "is present (JTN-311)"
    )


def test_sync_remove_button_states_sets_tooltip(client):
    """JTN-311: syncRemoveButtonStates must set a tooltip explaining why removal is blocked."""
    resp = client.get("/static/scripts/plugin_schema.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "Add another calendar before removing this one" in js, (
        "syncRemoveButtonStates must set a title/tooltip explaining why the "
        "Remove button is disabled (JTN-311)"
    )


def test_sync_remove_called_on_init_and_add(client):
    """JTN-311: syncRemoveButtonStates must be called during initCalendarRepeater
    (on page load) and when a new calendar row is added."""
    resp = client.get("/static/scripts/plugin_schema.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # At least two call-sites within initCalendarRepeater (init + add handler)
    count = js.count("syncRemoveButtonStates(list)")
    assert count >= 2, (
        f"syncRemoveButtonStates(list) should be called at least twice "
        f"(on init and on add), found {count} call(s) (JTN-311)"
    )


def test_handle_remove_click_no_shake_animation(client):
    """JTN-311: handleRemoveClick must not show the shake animation as feedback —
    the button is disabled instead, so the shake branch is unreachable."""
    resp = client.get("/static/scripts/plugin_schema.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # The shake class was the old silent-fail UX; it should be gone now.
    assert '"shake"' not in js and "'shake'" not in js, (
        "handleRemoveClick must not use shake animation — button is disabled "
        "instead to clearly communicate the constraint (JTN-311)"
    )


def test_calendar_page_renders_remove_button(client):
    """JTN-311: The rendered calendar plugin page must include a remove button."""
    resp = client.get("/plugin/calendar")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert (
        "remove-btn" in body
    ), "Calendar plugin page must render a remove button for calendar rows (JTN-311)"
    assert (
        'aria-label="Remove calendar"' in body
    ), "Remove button must have an accessible aria-label (JTN-311)"


# ---------------------------------------------------------------------------
# JTN-312: Last progress button shows progress panel
# ---------------------------------------------------------------------------


def test_show_last_progress_uses_set_hidden(client):
    """JTN-312: showLastProgress must use setHidden(progress, false) to reveal
    the progress panel, not style.display which is overridden by the `hidden`
    HTML attribute."""
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "setHidden(progress, false)" in js, (
        "showLastProgress must call setHidden(progress, false) to clear the "
        "HTML hidden attribute; using progress.style.display alone is a no-op "
        "when the hidden attribute is present (JTN-312)"
    )


def test_show_last_progress_does_not_use_style_display(client):
    """JTN-312: showLastProgress must not rely on style.display to show the
    progress block — the HTML `hidden` attribute overrides inline styles."""
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Verify the old broken pattern is gone
    assert 'progress.style.display = "block"' not in js, (
        "showLastProgress must not use progress.style.display = 'block'; "
        "use setHidden(progress, false) instead (JTN-312)"
    )


def test_show_last_progress_btn_present_on_calendar_page(client):
    """JTN-312: The rendered calendar plugin page must include the Last progress button."""
    resp = client.get("/plugin/calendar")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert (
        'id="showLastProgressBtn"' in body
    ), "Calendar plugin page must render showLastProgressBtn (JTN-312)"


def test_show_last_progress_no_data_shows_modal(client):
    """JTN-312: When localStorage has no data, showLastProgress must call
    showResponseModal with a user-visible message, not silently fail."""
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "No recent progress to show" in js, (
        "showLastProgress must display 'No recent progress to show' via "
        "showResponseModal when localStorage has no data (JTN-312)"
    )


def test_request_progress_block_present_on_calendar_page(client):
    """JTN-312: The rendered calendar plugin page must include the requestProgress
    block that showLastProgress reveals."""
    resp = client.get("/plugin/calendar")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert 'id="requestProgress"' in body, (
        "Calendar plugin page must render requestProgress block so "
        "showLastProgress has an element to reveal (JTN-312)"
    )
