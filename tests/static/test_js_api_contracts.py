"""Static checks verifying JavaScript files are served and expose expected APIs.

Consolidated from: test_api_validator_js.py, test_enhanced_progress_js.py,
test_icons_loader_js.py, test_lightbox_js.py, test_response_modal_js.py,
test_response_modal_more.py, test_theme_js.py
"""

from pathlib import Path

from flask.testing import FlaskClient

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "scripts"


def _plugin_page_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            _SCRIPTS_DIR / "plugin_page" / "shared.js",
            _SCRIPTS_DIR / "plugin_page" / "progress.js",
            _SCRIPTS_DIR / "plugin_page.js",
        ]
    )


# --- Progress timing labels ---


def test_plugin_progress_keeps_ms_metric_labels(client: FlaskClient) -> None:
    """Progress summaries keep millisecond timing labels visible in the UI."""
    resp = client.get("/static/scripts/plugin_form.js")
    assert resp.status_code == 200
    plugin_js = resp.get_data(as_text=True)

    assert "fmtElapsed(elapsedMs)" in plugin_js
    assert "${step.elapsed_ms} ms" in plugin_js
    assert "${label} ${val} ms" in plugin_js


# --- Lightbox ---


def test_lightbox_script_exists(client: FlaskClient) -> None:
    resp = client.get("/static/scripts/lightbox.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    tokens = [
        "window.Lightbox",
        "openLightbox",
        "closeLightbox",
        "toggleNativeSizing",
        "bind(selector",
    ]
    for token in tokens:
        assert token in js

    assert "modal.id" in js and "imagePreviewModal" in js


def test_lightbox_click_timer_disambiguates_single_double_click(
    client: FlaskClient,
) -> None:
    """JTN-262: Single click should close, double-click should toggle native sizing.

    The fix uses a click timer so the first click of a double-click does not
    close the lightbox before the second click arrives.  Verify the timer
    pattern is present and the separate dblclick listener is gone.
    """
    resp = client.get("/static/scripts/lightbox.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Timer variable must exist at module scope
    assert "let clickTimer = null" in js

    # The unified handler that checks / clears the timer
    assert "imgClickHandler" in js
    assert "clearTimeout(clickTimer)" in js
    assert "clickTimer = setTimeout" in js

    # The handler must be registered as a click listener on the img
    assert "img.addEventListener('click', imgClickHandler)" in js

    # The old separate dblclick listener must not be present
    assert "addEventListener('dblclick'" not in js


# --- Response Modal ---


def test_response_modal_script_exists(client: FlaskClient) -> None:
    resp = client.get("/static/scripts/response_modal.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Core functions
    for token in [
        "function ensureToastContainer()",
        "function dismissStaleErrors()",
        "function showToast(status, message, duration = TOAST_DURATION_MS)",
        "function closeToast(toastId)",
        "function showResponseModal(status, message)",
        "async function handleJsonResponse(response, options = {})",
        "function getErrorMessage(status, endpoint)",
        "function showError(message, duration)",
    ]:
        assert token in js

    # Other scripts call these by bare name; the file publishes them.
    for name in ["showToast", "showResponseModal", "showError", "handleJsonResponse"]:
        assert f"globalThis.{name} = {name};" in js

    # Auto-dismiss constants
    assert "TOAST_ERROR_DURATION_MS" in js


def test_handle_json_response_presence(client: FlaskClient) -> None:
    resp = client.get("/static/scripts/response_modal.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Check that handleJsonResponse includes request_id and maps codes
    assert "handleJsonResponse" in js
    assert "request_id" in js
    assert "getErrorMessage" in js
    # Common messages present
    assert "Server error" in js
    assert "Resource not found" in js or "Not found" in js


# --- Theme ---


def test_theme_script_exists(client: FlaskClient) -> None:
    resp = client.get("/static/scripts/theme.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Basic behaviors present
    assert "localStorage.getItem('theme')" in js
    assert "document.documentElement.setAttribute('data-theme'" in js
    assert "getPreferredTheme()" in js
    assert "applyTheme(theme)" in js
    assert "themeToggle" in js


def test_playlist_script_handles_invalid_stored_message_json(
    client: FlaskClient,
) -> None:
    resp = client.get("/static/scripts/playlist/display.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert 'const storedMessage = sessionStorage.getItem("storedMessage");' in js
    assert "const { type, text } = JSON.parse(storedMessage);" in js
    assert "try {" in js
    assert 'sessionStorage.removeItem("storedMessage");' in js


def test_csrf_script_preserves_existing_headers_without_empty_object_copy(
    client: FlaskClient,
) -> None:
    resp = client.get("/static/scripts/csrf.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "init.headers = init.headers ? { ...init.headers } : {};" in js
    assert "{ ...(init.headers || {}) }" not in js


def test_plugin_page_script_uses_globalthis_for_plugin_hooks(
    client: FlaskClient,
) -> None:
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    js = _plugin_page_source()

    assert "function validateAddToPlaylistAction(action)" in js
    assert 'typeof globalThis.validatePluginSettings === "function"' in js
    assert "globalThis.PluginForm" in js


def test_show_last_progress_does_not_use_global_fallback_key(
    client: FlaskClient,
) -> None:
    """Verify showLastProgress does not fall back to the bare global key.

    JTN-246: the global 'INKYPI_LAST_PROGRESS' key is shared across all plugins,
    so using it as a fallback in showLastProgress can surface progress data from
    a completely different plugin. Only plugin-scoped keys must be in the chain.
    """
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    js = _plugin_page_source()

    # The plugin-specific key prefix must still be present
    assert "INKYPI_LAST_PROGRESS:plugin:" in js

    # Extract the showLastProgress function body to check its keys array
    fn_start = js.find("function showLastProgress()")
    assert fn_start != -1, "showLastProgress function not found"
    fn_body = js[fn_start : fn_start + 600]

    # The bare global key must NOT appear in the showLastProgress keys array
    assert (
        '"INKYPI_LAST_PROGRESS"' not in fn_body
    ), "showLastProgress must not include the bare global fallback key"


# --- URL encoding ---


def test_playlist_script_url_encodes_playlist_names_in_fetch_calls(
    client: FlaskClient,
) -> None:
    """JTN-234: Playlist names must be URL-encoded before appending to fetch URLs.

    Playlist names can contain spaces and special characters.  Without encoding
    the URL becomes malformed and the server receives a garbled path segment.
    """
    form_resp = client.get("/static/scripts/playlist/form.js")
    modal_resp = client.get("/static/scripts/playlist/modals.js")
    assert form_resp.status_code == 200
    assert modal_resp.status_code == 200
    form_js = form_resp.get_data(as_text=True)
    modal_js = modal_resp.get_data(as_text=True)

    # update_playlist_base_url must use encodeURIComponent, not raw concatenation
    assert "update_playlist_base_url + encodeURIComponent(oldName)" in form_js

    # Every delete_playlist fetch must use encodeURIComponent. The confirm
    # dialog is the only one: the edit dialog's Delete opens it.
    for js in (form_js, modal_js):
        assert js.count("delete_playlist_base_url +") == js.count(
            "delete_playlist_base_url + encodeURIComponent("
        )
    assert "delete_playlist_base_url + encodeURIComponent(name)" in modal_js


# --- API Keys dirty tracking (JTN-225) ---


def test_api_keys_page_js_dirty_tracking_present(client: FlaskClient) -> None:
    """JTN-225: api_keys_page.js must implement dirty tracking so Save starts disabled."""
    resp = client.get("/static/scripts/api_keys_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Dirty-state variables and helpers must be present
    assert "let _isDirty = false" in js
    assert "function markDirty()" in js
    assert "function markClean()" in js

    # markDirty enables Save; markClean disables it
    assert "saveBtn.disabled = false" in js
    assert "saveBtn.disabled = true" in js

    # Save button must be disabled at init
    assert "saveBtn.disabled = true" in js

    # saveKeys must guard against no-op clicks
    assert "No changes to save" in js

    # Structural mutations (addRow, deleteRow, clearField) must call markDirty
    assert js.count("markDirty()") >= 4

    # After a successful save, markClean must be called
    assert js.count("markClean()") >= 2


def test_api_keys_template_save_button_starts_disabled(client: FlaskClient) -> None:
    """JTN-225: The rendered /settings/api-keys page must have Save disabled by default."""
    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # The Save button element must carry the disabled attribute in the raw HTML
    assert 'id="saveApiKeysBtn"' in body
    # Confirm the disabled attribute is present on that button in the HTML
    save_btn_idx = body.index('id="saveApiKeysBtn"')
    surrounding = body[max(0, save_btn_idx - 20) : save_btn_idx + 120]
    assert (
        "disabled" in surrounding
    ), "Save button on /settings/api-keys must have disabled attribute in rendered HTML"
