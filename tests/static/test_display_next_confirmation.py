"""Display Next confirmation dialog (JTN-630).

The "Display Next" button on each playlist card used to fire immediately
with no confirmation and no success/error feedback, leaving the user
unsure whether the action was sent. It must now open a confirmation modal
(matching the Delete Playlist pattern) and surface a success toast so the
user has positive feedback.
"""

from __future__ import annotations


def _read_playlist_html(client) -> str:
    resp = client.get("/playlist")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _read_playlist_js(client) -> str:
    resp = client.get("/static/scripts/playlist.js")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Template — confirmation modal exists and is accessible
# ---------------------------------------------------------------------------


def test_display_next_confirm_modal_rendered(client):
    """The display next confirmation modal must be present in playlist.html."""
    html = _read_playlist_html(client)
    assert (
        'id="displayNextConfirmModal"' in html
    ), "Display Next confirmation modal missing from playlist page"
    assert 'id="confirmDisplayNextBtn"' in html
    assert 'id="cancelDisplayNextBtn"' in html


def test_display_next_modal_uses_role_dialog(client):
    html = _read_playlist_html(client)
    idx = html.find('id="displayNextConfirmModal"')
    assert idx != -1
    opening = html[idx : idx + 400]
    assert 'role="dialog"' in opening
    assert 'aria-modal="true"' in opening


def test_display_next_modal_has_labelledby(client):
    html = _read_playlist_html(client)
    idx = html.find('id="displayNextConfirmModal"')
    assert idx != -1
    opening = html[idx : idx + 400]
    assert 'aria-labelledby="displayNextConfirmTitle"' in opening
    # The referenced heading must exist in the DOM.
    assert 'id="displayNextConfirmTitle"' in html


# ---------------------------------------------------------------------------
# JS — click handler opens modal instead of firing action immediately
# ---------------------------------------------------------------------------


def test_run_next_btn_opens_confirm_modal_not_fire_directly(client):
    """The delegated run-next action must open the confirmation modal,
    not invoke displayNextInPlaylist immediately."""
    js = _read_playlist_js(client)
    assert (
        'action === "confirm-display-next"' in js
        or "action === 'confirm-display-next'" in js
    ), "delegated playlist handler must branch on confirm-display-next"
    assert (
        "openDisplayNextConfirmModal(name, actionButton)" in js
    ), "confirm-display-next action must open the confirmation modal with the trigger button"


def test_display_next_helper_exists_and_is_async(client):
    """The helper that actually performs the fetch stays available for the
    confirm button and for the public window.* API (used by other callers
    and by tests)."""
    js = _read_playlist_js(client)
    assert "async function displayNextInPlaylist(name)" in js
    assert "window.displayNextInPlaylist = displayNextInPlaylist" in js
    assert "window.openDisplayNextConfirmModal = openDisplayNextConfirmModal" in js


def test_display_next_success_surfaces_toast(client):
    """On success, the user must see positive feedback (toast) — previously
    there was only a silent reload, per JTN-630."""
    js = _read_playlist_js(client)
    assert "showResponseModal('success'" in js, (
        "Display Next success path must call showResponseModal('success', ...) "
        "so the user has positive feedback — this is the JTN-630 fix"
    )


def test_display_next_cancel_button_wired(client):
    """Cancel button on the confirm modal must close the modal."""
    js = _read_playlist_js(client)
    assert (
        "getElementById('cancelDisplayNextBtn')?.addEventListener('click', "
        "closeDisplayNextConfirmModal)" in js
    )


def test_display_next_modal_registered_for_escape_and_backdrop(client):
    """The confirm modal must participate in the shared Escape/backdrop-close
    plumbing used by the other playlist modals."""
    js = _read_playlist_js(client)
    # Backdrop click closes it.
    assert (
        "event.target?.id === 'displayNextConfirmModal'" in js
    ), "displayNextConfirmModal must close on backdrop click"
    # It is tracked by getOpenModalId so Escape works.
    assert "'displayNextConfirmModal'," in js
