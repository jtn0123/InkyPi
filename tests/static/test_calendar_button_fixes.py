"""Tests for JTN-311, JTN-312, and JTN-347 cluster: plugin button bug fixes.

JTN-311: Remove calendar button must be disabled (not a silent no-op) when
         only one calendar row is present.
JTN-312: Last progress button must call a handler that makes progress visible,
         not leave the panel hidden due to the HTML `hidden` attribute.
JTN-347/348/331/332: "Show last progress" button must produce visible feedback
         on Clock, To-Do List, Calendar, and Screenshot plugin pages.
"""

import pytest

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


# ---------------------------------------------------------------------------
# JTN-347/348/331/332: "Show last progress" visible feedback across plugins
# ---------------------------------------------------------------------------


def test_show_last_progress_clears_inline_display_style(client):
    """JTN-347: showLastProgress must clear inline style.display left by
    progress.stop(), otherwise the progress block stays invisible even
    after the hidden attribute is removed."""
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert 'progress.style.display = ""' in js, (
        "showLastProgress must reset progress.style.display to '' so inline "
        "display:none from progress.stop() does not keep the block hidden "
        "(JTN-347)"
    )


def test_progress_stop_does_not_set_display_none(client):
    """JTN-347: progress.stop() must hide via the hidden attribute only,
    not set style.display='none' which conflicts with showLastProgress."""
    resp = client.get("/static/scripts/plugin_form.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Extract the stop function body (between "function stop()" and the next
    # "return" that closes the initProgress IIFE).
    stop_start = js.find("function stop()")
    assert stop_start != -1, "stop function not found in plugin_form.js"
    stop_body = js[stop_start : stop_start + 300]

    assert "style.display = 'none'" not in stop_body, (
        "progress.stop() must not set style.display = 'none'; "
        "use the hidden attribute instead (JTN-347)"
    )


@pytest.mark.parametrize(
    "plugin_id",
    ["clock", "todo_list", "calendar", "screenshot"],
    ids=["JTN-347-clock", "JTN-348-todo", "JTN-331-calendar", "JTN-332-screenshot"],
)
def test_show_last_progress_btn_present_on_plugin_page(client, plugin_id):
    """JTN-347/348/331/332: Each affected plugin page must render the
    showLastProgressBtn so users get visible feedback."""
    resp = client.get(f"/plugin/{plugin_id}")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert (
        'id="showLastProgressBtn"' in body
    ), f"{plugin_id} plugin page must render showLastProgressBtn"


@pytest.mark.parametrize(
    "plugin_id",
    ["clock", "todo_list", "calendar", "screenshot"],
    ids=["JTN-347-clock", "JTN-348-todo", "JTN-331-calendar", "JTN-332-screenshot"],
)
def test_request_progress_block_present_on_plugin_page(client, plugin_id):
    """JTN-347/348/331/332: Each affected plugin page must include the
    requestProgress block that showLastProgress reveals."""
    resp = client.get(f"/plugin/{plugin_id}")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert (
        'id="requestProgress"' in body
    ), f"{plugin_id} plugin page must render requestProgress block"
