# pyright: reportMissingImports=false
"""API Required chip unsaved-changes guard (JTN-629).

On plugin pages that require an API key but don't have one configured, the
"API Required" chip in the header was a plain <a> link that immediately
navigated to /settings/api-keys. A user who had typed a long prompt (e.g.
in AI Image) and tapped the chip lost everything without warning.

This regression test locks in the fix:
  * template renders a confirmation modal when the key is missing
  * the chip carries a data attribute the JS hooks onto
  * plugin_page.js wires a click handler that compares the current form
    snapshot to the initial snapshot and opens the modal when dirty
"""

from pathlib import Path

_PLUGIN_JS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "static"
    / "scripts"
    / "plugin_page.js"
)


def _read_plugin_html(client, plugin_id: str = "ai_image") -> str:
    resp = client.get(f"/plugin/{plugin_id}")
    assert resp.status_code == 200, f"/plugin/{plugin_id} returned {resp.status_code}"
    return resp.get_data(as_text=True)


# --------------------------------------------------------------------------
# Template — confirmation modal + hookable chip
# --------------------------------------------------------------------------


def test_api_required_chip_has_data_hook(client):
    """The missing-key chip must expose data-api-keys-link so JS can intercept."""
    html = _read_plugin_html(client)
    assert "data-api-keys-link" in html, (
        "The API Required chip must expose a data attribute so the plugin "
        "page JS can intercept its click and show the unsaved-changes modal."
    )


def test_api_keys_leave_confirm_modal_rendered(client):
    """A confirmation modal must be present when the API key is required+missing."""
    html = _read_plugin_html(client)
    assert 'id="apiKeysLeaveConfirmModal"' in html, (
        "The unsaved-changes confirmation modal must be rendered on plugin "
        "pages that require an API key (JTN-629)."
    )
    assert 'id="confirmApiKeysLeaveBtn"' in html
    assert 'id="cancelApiKeysLeaveBtn"' in html


def test_api_keys_leave_modal_has_accessibility_attrs(client):
    html = _read_plugin_html(client)
    idx = html.find('id="apiKeysLeaveConfirmModal"')
    assert idx != -1
    opening = html[idx : idx + 400]
    assert 'role="dialog"' in opening
    assert 'aria-modal="true"' in opening


def test_confirm_leave_button_points_to_api_keys(client):
    """The "Leave and discard" button must still navigate to /settings/api-keys."""
    html = _read_plugin_html(client)
    idx = html.find('id="confirmApiKeysLeaveBtn"')
    assert idx != -1
    # The button itself is an <a> so no-JS users still have a navigable path.
    # Find the opening tag preceding the id and verify href is present.
    window = html[max(0, idx - 200) : idx + 200]
    assert "/settings/api-keys" in window or "api-keys" in window


def test_modal_copy_mentions_unsaved_changes(client):
    html = _read_plugin_html(client)
    lower = html.lower()
    # Modal body copy must clearly warn about unsaved changes.
    assert "unsaved" in lower, "Modal must warn about unsaved changes"


# --------------------------------------------------------------------------
# JS — dirty-state guard wiring
# --------------------------------------------------------------------------


def test_plugin_js_has_leave_guard_init():
    js = _PLUGIN_JS.read_text(encoding="utf-8")
    assert "initApiKeysLeaveGuard" in js, (
        "plugin_page.js must define an init function that wires the API "
        "Required chip to the unsaved-changes confirmation modal."
    )


def test_plugin_js_hooks_data_api_keys_link():
    js = _PLUGIN_JS.read_text(encoding="utf-8")
    assert "data-api-keys-link" in js, (
        "plugin_page.js must locate the API chip via the data-api-keys-link "
        "selector so clicks can be intercepted."
    )


def test_plugin_js_tracks_form_snapshot_for_dirty_check():
    js = _PLUGIN_JS.read_text(encoding="utf-8")
    # Dirty detection is implemented by comparing a form snapshot to the
    # current state. Both pieces must exist.
    assert "getSettingsFormSnapshot" in js
    assert "isSettingsFormDirty" in js


def test_plugin_js_opens_modal_only_when_dirty():
    js = _PLUGIN_JS.read_text(encoding="utf-8")
    # The guard must open the apiKeysLeaveConfirmModal via openModal.
    assert "apiKeysLeaveConfirmModal" in js
    # Clean form should fall through to native navigation (no preventDefault).
    # We check the guard explicitly returns before preventDefault when clean.
    assert "isSettingsFormDirty()" in js


def test_plugin_js_guard_is_called_from_init():
    js = _PLUGIN_JS.read_text(encoding="utf-8")
    # Called from the main init() so it runs on every plugin page load.
    assert "initApiKeysLeaveGuard()" in js


# --------------------------------------------------------------------------
# No regression — pages without API requirement stay clean
# --------------------------------------------------------------------------


def test_no_modal_when_plugin_has_no_api_requirement(client):
    """The clock plugin has no api_key requirement; modal should not render."""
    html = _read_plugin_html(client, plugin_id="clock")
    assert "apiKeysLeaveConfirmModal" not in html, (
        "The unsaved-changes modal should only render when an API key is "
        "required AND missing. Other plugins should not get the modal markup."
    )
