"""Static checks verifying JavaScript files are served and expose expected APIs.

Consolidated from: test_api_validator_js.py, test_enhanced_progress_js.py,
test_icons_loader_js.py, test_lightbox_js.py, test_response_modal_js.py,
test_response_modal_more.py, test_theme_js.py
"""

# --- API Validator ---


def test_api_validator_script_exists(client):
    resp = client.get("/static/scripts/api_validator.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Classes exposed
    assert "class APIValidator" in js
    assert "class APIValidationUI" in js
    assert "window.APIValidator" in js
    assert "window.APIValidationUI" in js

    # Core methods on APIValidator
    for token in [
        "async validateEndpoint(url, options = {})",
        "async _performValidation(url, options)",
        "_categorizeError(error)",
        "async validateMultiple(endpoints)",
        "clearCache()",
        "getCachedResult(url)",
    ]:
        assert token in js

    # UI helper methods
    for token in [
        "createValidationIndicator(input, options = {})",
        "async validateInput(input, indicator, options = {})",
        "updateIndicator(indicator, status, text)",
        "showValidationDetails(indicator, result)",
        "validateNow(input)",
        "addValidationToInputs(selector, options = {})",
    ]:
        assert token in js


def test_api_validator_no_custom_user_agent(client):
    """JTN-261: Custom User-Agent header triggers CORS preflight, failing external API checks.

    User-Agent is not CORS-safelisted and is a forbidden header in the Fetch spec.
    The validator must not set it in fetch calls.
    """
    resp = client.get("/static/scripts/api_validator.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "user-agent" not in js.lower(), (
        "Custom User-Agent header must not be set in fetch calls — "
        "it triggers CORS preflight and is forbidden by the Fetch spec."
    )


# --- Enhanced Progress ---


def test_enhanced_progress_script_exists(client):
    resp = client.get("/static/scripts/enhanced_progress.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Class and globals
    assert "class EnhancedProgressDisplay" in js
    assert "window.EnhancedProgressDisplay" in js
    assert "window.createEnhancedProgress" in js

    # Core methods
    for token in [
        "initializeElements()",
        "start(steps = [], title = 'Processing...')",
        "nextStep(description = '', substeps = [])",
        "updateStep(stepName, description = '', progress = 0, substeps = [])",
        "updateProgress(progress)",
        "complete(message = 'Operation completed', success = true)",
        "fail(error = 'Operation failed')",
        "renderSteps()",
        "updateStepVisual(stepIndex)",
        "getTimingSummary()",
    ]:
        assert token in js

    # Key UI elements rendered
    assert "enhanced-progress-header" in js
    assert "enhanced-progress-fill" in js
    assert "enhanced-progress-steps" in js
    assert "enhanced-progress-log" in js


# --- Icons Loader ---


def test_icons_loader_script_exists(client):
    resp = client.get("/static/scripts/icons_loader.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # It should be a no-op but present
    assert "no-op" in js or "no op" in js or "does nothing" in js


# --- Lightbox ---


def test_lightbox_script_exists(client):
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


def test_lightbox_click_timer_disambiguates_single_double_click(client):
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


def test_response_modal_script_exists(client):
    resp = client.get("/static/scripts/response_modal.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Core functions
    for token in [
        "function ensureToastContainer()",
        "function dismissStaleErrors()",
        "function showToast(status, message, duration = TOAST_DURATION_MS)",
        "function closeToast(toastId)",
        "function showResponseModal(status, message, useToast = true)",
        "function closeResponseModal()",
        "async function handleJsonResponse(response, options = {})",
        "function getErrorMessage(status, endpoint)",
        "function showSuccess(message, duration)",
        "function showError(message, duration)",
        "function showWarning(message, duration)",
        "function showInfo(message, duration)",
    ]:
        assert token in js

    # Auto-dismiss constants
    assert "TOAST_ERROR_DURATION_MS" in js


def test_handle_json_response_presence(client):
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


def test_theme_script_exists(client):
    resp = client.get("/static/scripts/theme.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Basic behaviors present
    assert "localStorage.getItem('theme')" in js
    assert "document.documentElement.setAttribute('data-theme'" in js
    assert "getPreferredTheme()" in js
    assert "applyTheme(theme)" in js
    assert "themeToggle" in js


def test_playlist_script_handles_invalid_stored_message_json(client):
    resp = client.get("/static/scripts/playlist.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert 'const storedMessage = sessionStorage.getItem("storedMessage");' in js
    assert "const { type, text } = JSON.parse(storedMessage);" in js
    assert "try {" in js
    assert 'sessionStorage.removeItem("storedMessage");' in js


def test_image_modal_script_guards_missing_container(client):
    resp = client.get("/static/scripts/image_modal.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "const imageContainer = document.querySelector('.image-container');" in js
    assert "if (!imageContainer) return;" in js
    assert "const img = imageContainer.querySelector('img');" in js
    assert "if (!img) return;" in js


def test_csrf_script_preserves_existing_headers_without_empty_object_copy(client):
    resp = client.get("/static/scripts/csrf.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "init.headers = init.headers ? { ...init.headers } : {};" in js
    assert "{ ...(init.headers || {}) }" not in js


def test_history_page_script_uses_outer_scope_modal_helper(client):
    resp = client.get("/static/scripts/history_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "function getOpenHistoryModal()" in js
    assert "const openModal = getOpenHistoryModal();" in js


def test_plugin_page_script_uses_globalthis_for_plugin_hooks(client):
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "function validateAddToPlaylistAction(action)" in js
    assert 'typeof globalThis.validatePluginSettings === "function"' in js
    assert "globalThis.PluginForm" in js


def test_show_last_progress_does_not_use_global_fallback_key(client):
    """Verify showLastProgress does not fall back to the bare global key.

    JTN-246: the global 'INKYPI_LAST_PROGRESS' key is shared across all plugins,
    so using it as a fallback in showLastProgress can surface progress data from
    a completely different plugin. Only plugin-scoped keys must be in the chain.
    """
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

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


# --- XSS / innerHTML safety ---


def test_enhanced_progress_escapes_step_names_in_innerhtml(client):
    """Verify step names from SSE events are HTML-escaped before innerHTML injection.

    JTN-242: step names are server-supplied strings and must be escaped to prevent XSS.
    The escapeHtml helper must exist at module level and be applied in renderSteps.
    """
    resp = client.get("/static/scripts/enhanced_progress.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # escapeHtml helper must be defined as a standalone function
    assert "function escapeHtml(" in js

    # renderSteps must use escapeHtml on the step value
    assert "escapeHtml(step)" in js

    # Bare unescaped interpolation must NOT appear for step-name rendering
    assert '"step-name">${step}<' not in js


def test_skeleton_loader_escapes_step_names_in_innerhtml(client):
    """Verify step names passed to createProgressSkeleton are HTML-escaped.

    JTN-242: step names are caller-supplied strings and must be escaped to prevent XSS.
    The static escapeHtml helper must exist on SkeletonLoader and be applied in the template.
    """
    resp = client.get("/static/scripts/skeleton_loader.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # escapeHtml must be defined as a static method on SkeletonLoader
    assert "static escapeHtml(" in js

    # The progress-step template must use SkeletonLoader.escapeHtml
    assert "SkeletonLoader.escapeHtml(step)" in js

    # Bare unescaped interpolation must NOT appear for skeleton-step-text rendering
    assert '"skeleton-step-text">${step}<' not in js


# --- URL encoding ---


def test_playlist_script_url_encodes_playlist_names_in_fetch_calls(client):
    """JTN-234: Playlist names must be URL-encoded before appending to fetch URLs.

    Playlist names can contain spaces and special characters.  Without encoding
    the URL becomes malformed and the server receives a garbled path segment.
    """
    resp = client.get("/static/scripts/playlist.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # update_playlist_base_url must use encodeURIComponent, not raw concatenation
    assert "update_playlist_base_url + encodeURIComponent(oldName)" in js

    # Both delete_playlist fetch sites must use encodeURIComponent
    assert js.count("delete_playlist_base_url + encodeURIComponent(") >= 2


# --- API Keys dirty tracking (JTN-225) ---


def test_api_keys_page_js_dirty_tracking_present(client):
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


def test_api_keys_template_save_button_starts_disabled(client):
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
