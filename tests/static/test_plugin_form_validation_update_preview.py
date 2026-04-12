"""JTN-648: "Update Preview" must show an app-level toast (not only the
browser's HTML5 bubble) when a required field is empty.

Bug: On ``/plugin/image_url`` and ``/plugin/rss``, clicking "Update Preview"
with an empty required field (or pressing Enter inside the form) triggered
only the browser-native HTML5 constraint bubble — the rest of the validation
UI consistently routes through ``showResponseModal`` and names the failing
field (JTN-378). This ticket closes that gap.

The fix adds an app-level interception in ``plugin_page.js``:
    * listen for the ``invalid`` event in the capture phase on ``#settingsForm``
      and ``#scheduleForm`` and suppress the native bubble;
    * intercept Enter-key submissions on the same forms and route through the
      shared ``FormValidator.validateAllInputsDetailed`` + ``showResponseModal``
      flow so the toast names the failing field (e.g. "Image URL is required",
      "RSS Feed URL is required").

The ``required`` attribute is preserved on the underlying inputs so the
HTML5 bubble still works as a fallback when JS is disabled (progressive
enhancement).
"""

from pathlib import Path

JS_PATH = Path("src/static/scripts/plugin_page.js")


def _read_js() -> str:
    return JS_PATH.read_text()


def test_plugin_page_attaches_invalid_listener_in_capture_phase():
    """The capture-phase ``invalid`` listener is what suppresses the native
    bubble; without it, the browser renders its own popup before any JS
    runs."""
    js = _read_js()

    # Helper name pins the fix in place.
    assert "attachAppLevelValidation" in js, (
        "Expected an attachAppLevelValidation helper that wires the "
        "invalid-event suppression + toast flow onto each form"
    )
    # The listener must run in the capture phase so it fires before the
    # browser's default bubble UI.
    assert '"invalid"' in js
    # addEventListener(..., true) or { capture: true } both satisfy capture-
    # phase intent; this repo uses the positional ``true`` form.
    assert 'addEventListener(\n        "invalid"' in js or "'invalid'" in js
    assert ", true" in js or "capture: true" in js, (
        "invalid listener must be registered in the capture phase so it "
        "beats the browser's native bubble"
    )


def test_plugin_page_routes_submit_through_formvalidator():
    """Enter-key submission bypasses the Update Preview button handler, so
    the form's own submit listener must run the same validator + modal
    flow (otherwise users who press Enter fall back to the native bubble)."""
    js = _read_js()

    assert "validateAllInputsDetailed(form)" in js, (
        "attachAppLevelValidation must call validateAllInputsDetailed so the "
        "toast names the offending field (JTN-378 pattern)"
    )
    assert "buildValidationMessage(result)" in js
    assert "focusFirstInvalid(form)" in js
    # Both settingsForm and scheduleForm must route through the helper.
    assert 'attachAppLevelValidation(document.getElementById("settingsForm"))' in js
    assert 'attachAppLevelValidation(document.getElementById("scheduleForm"))' in js


def test_plugin_page_invalid_handler_prevents_default():
    """The native bubble only stays hidden if the invalid event's default
    action is prevented."""
    js = _read_js()
    # The invalid handler body must call preventDefault to suppress the
    # browser's default bubble UI.
    # Find the invalid branch and assert preventDefault is called before the
    # toast logic.
    idx = js.find('"invalid"')
    assert idx != -1
    window = js[idx : idx + 400]
    assert "event.preventDefault()" in window, (
        "The invalid handler must call event.preventDefault() in the capture "
        "phase or the native HTML5 bubble still renders"
    )


def test_plugin_page_submit_handler_prevents_default():
    """Submit must not navigate — the validator runs inline and the action
    buttons own the actual POST."""
    js = _read_js()
    # Both the settingsForm and scheduleForm submit handlers must prevent
    # default navigation. attachAppLevelValidation does this inside its
    # submit handler.
    assert 'form.addEventListener("submit"' in js
    # The submit handler body uses event.preventDefault().
    submit_idx = js.find('form.addEventListener("submit"')
    assert submit_idx != -1
    window = js[submit_idx : submit_idx + 400]
    assert "event.preventDefault()" in window


def test_image_url_plugin_preserves_required_attribute(client):
    """Progressive enhancement: the ``required`` attribute must survive so the
    HTML5 bubble remains the no-JS fallback. The JS suppresses it only while
    the app is interactive."""
    resp = client.get("/plugin/image_url")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # The schema renderer emits the required attribute for the URL field.
    assert "required" in html
    # Label is available so FormValidator.getInputLabel can produce
    # "Image URL is required" in the toast.
    assert 'for="url"' in html or 'name="url"' in html
    assert "Image URL" in html


def test_rss_plugin_preserves_required_attribute(client):
    """Same progressive-enhancement contract for the RSS Feed URL field."""
    resp = client.get("/plugin/rss")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "required" in html
    assert "RSS Feed URL" in html


def test_plugin_page_uses_shared_response_modal(client):
    """The toast must go through ``showResponseModal`` so it renders in the
    shared error modal (consistent with every other plugin-level error)."""
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # The helper calls the shared modal when a field fails validation.
    assert 'showResponseModal(\n                "failure"' in js or (
        'showResponseModal(\n            "failure"' in js
    ), "app-level toast must go through showResponseModal"
