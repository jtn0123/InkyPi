"""Device action confirmation dialogs (JTN-621).

On a Pi Zero 2 W, an accidental tap on Reboot or Shutdown in Settings
immediately makes the device unreachable with no physical recovery until
power cycle. Both actions must be gated behind a confirmation modal.
"""

from pathlib import Path


def _read_settings_html(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _read_settings_js(client):
    resp = client.get("/static/scripts/settings_page.js")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Template — confirmation modals exist
# ---------------------------------------------------------------------------


def test_reboot_confirm_modal_rendered(client):
    """The reboot confirmation modal must be present in settings.html."""
    html = _read_settings_html(client)
    assert (
        'id="rebootConfirmModal"' in html
    ), "Reboot confirmation modal missing from settings page"
    assert 'id="confirmRebootBtn"' in html
    assert 'id="cancelRebootBtn"' in html


def test_shutdown_confirm_modal_rendered(client):
    """The shutdown confirmation modal must be present in settings.html."""
    html = _read_settings_html(client)
    assert (
        'id="shutdownConfirmModal"' in html
    ), "Shutdown confirmation modal missing from settings page"
    assert 'id="confirmShutdownBtn"' in html
    assert 'id="cancelShutdownBtn"' in html


def test_confirm_modals_have_destructive_copy(client):
    """Modals must clearly warn that physical access is required to recover."""
    html = _read_settings_html(client)
    # Reboot warns about UI unavailability.
    assert (
        "physical access" in html.lower()
    ), "Confirmation modals must warn about needing physical access to recover"


def test_confirm_modals_use_role_dialog(client):
    """Modals must use role=dialog and aria-modal for accessibility."""
    html = _read_settings_html(client)
    # Simple presence check — both modals share the pattern.
    for modal_id in ("rebootConfirmModal", "shutdownConfirmModal"):
        idx = html.find(f'id="{modal_id}"')
        assert idx != -1
        # role=dialog and aria-modal should be on the same opening tag.
        opening = html[idx : idx + 400]
        assert 'role="dialog"' in opening, f"{modal_id} must have role=dialog"
        assert 'aria-modal="true"' in opening, f"{modal_id} must be aria-modal"


# ---------------------------------------------------------------------------
# JS — click handlers open modal instead of firing action immediately
# ---------------------------------------------------------------------------


def test_reboot_button_click_opens_confirm_modal_not_shutdown(client):
    """The rebootBtn click handler must NOT call handleShutdown directly —
    it must open the confirmation modal instead."""
    js = _read_settings_js(client)
    # The old pattern fired handleShutdown(true) directly from the click.
    # After the fix, the click opens the confirmation modal.
    assert (
        '"rebootBtn")?.addEventListener("click", openRebootConfirm)' in js
        or 'getElementById("rebootBtn")?.addEventListener("click", openRebootConfirm)'
        in js
    ), "rebootBtn must open confirmation modal, not fire handleShutdown directly"

    # Make sure the old anti-pattern is gone.
    assert (
        '"rebootBtn")?.addEventListener("click", () => handleShutdown(true))' not in js
    ), "rebootBtn still wired to fire handleShutdown directly — no confirmation!"


def test_shutdown_button_click_opens_confirm_modal_not_shutdown(client):
    """The shutdownBtn click handler must NOT call handleShutdown directly."""
    js = _read_settings_js(client)
    assert (
        '"shutdownBtn")?.addEventListener("click", openShutdownConfirm)' in js
    ), "shutdownBtn must open confirmation modal, not fire handleShutdown directly"

    assert (
        '"shutdownBtn")?.addEventListener("click", () => handleShutdown(false))'
        not in js
    ), "shutdownBtn still wired to fire handleShutdown directly — no confirmation!"


def test_confirm_buttons_wired_to_handle_shutdown(client):
    """The confirm-action buttons inside the modals must be what actually
    invokes handleShutdown."""
    js = _read_settings_js(client)
    assert "confirmRebootBtn" in js, "confirmRebootBtn not wired up"
    assert "confirmShutdownBtn" in js, "confirmShutdownBtn not wired up"
    assert "handleShutdown(true)" in js
    assert "handleShutdown(false)" in js


def test_cancel_buttons_close_modals(client):
    """Cancel buttons must close the respective modal."""
    js = _read_settings_js(client)
    assert "cancelRebootBtn" in js
    assert "cancelShutdownBtn" in js
    assert "closeRebootConfirm" in js
    assert "closeShutdownConfirm" in js


# ---------------------------------------------------------------------------
# Sanity — file on disk (belt-and-braces; matches JTN-247 style)
# ---------------------------------------------------------------------------


def test_settings_js_on_disk_has_confirm_handlers():
    js = Path("src/static/scripts/settings_page.js").read_text()
    assert "openRebootConfirm" in js
    assert "openShutdownConfirm" in js
    assert "closeRebootConfirm" in js
    assert "closeShutdownConfirm" in js
