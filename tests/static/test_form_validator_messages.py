"""JTN-378: form validation messages must name the invalid field.

Replaces the generic "1 field needs fixing before saving" toast with a
label-specific message ("Prompt is required") and focuses the first
invalid input. The fix lives in form_validator.js (shared helper) and
plugin_page.js (the Save Settings / Add to Playlist caller).
"""


def test_form_validator_exposes_detailed_api(client):
    resp = client.get("/static/scripts/form_validator.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # New public helpers for label-aware validation.
    assert "validateAllInputsDetailed" in js
    assert "function getInputLabel(input)" in js
    assert "function buildValidationMessage(result)" in js
    assert "function focusFirstInvalid(form)" in js

    # Still exported on window.FormValidator for plugin_page.js callers.
    for name in (
        "validateAllInputsDetailed:",
        "getInputLabel:",
        "buildValidationMessage:",
        "focusFirstInvalid:",
    ):
        assert name in js, f"window.FormValidator must export {name.rstrip(':')}"


def test_form_validator_message_shapes(client):
    resp = client.get("/static/scripts/form_validator.js")
    js = resp.get_data(as_text=True)

    # Single-field wording: "<label> is required" / "<label> is invalid".
    assert '" is required"' in js
    assert '" is invalid"' in js
    # Multi-field wording: "<label> is required (and N more)".
    assert '" (and "' in js and '" more)"' in js


def test_form_validator_label_lookup_order(client):
    """Label lookup must prefer data-label, then aria-label, then <label for>,
    then a wrapping label, then the titlecased name, then 'This field'."""
    resp = client.get("/static/scripts/form_validator.js")
    js = resp.get_data(as_text=True)

    # data-label is checked first so authors can override.
    assert 'getAttribute("data-label")' in js
    # aria-label fallback.
    assert 'getAttribute("aria-label")' in js
    # label[for=id] lookup.
    assert 'label[for="' in js
    # Wrapping label fallback.
    assert 'input.closest("label")' in js
    # Final fallback.
    assert '"This field"' in js


def test_form_validator_includes_required_textareas(client):
    """textarea[required] was missing from the selector — JTN-378 also closes
    that gap so required textareas (e.g. AI Text prompt) are validated too."""
    resp = client.get("/static/scripts/form_validator.js")
    js = resp.get_data(as_text=True)

    assert "textarea[required]" in js


def test_plugin_page_uses_detailed_validator(client):
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Both Save Settings and Add to Playlist paths must route through the
    # detailed helper + the shared message builder.
    assert "validateAllInputsDetailed(settingsForm)" in js
    assert "validateAllInputsDetailed(scheduleForm)" in js
    assert "buildValidationMessage(result)" in js
    assert "buildValidationMessage(scheduleResult)" in js
    assert "focusFirstInvalid(settingsForm)" in js
    assert "focusFirstInvalid(scheduleForm)" in js

    # The old generic count-only messages must be gone so they can't regress.
    assert '" fields need" : " field needs"' not in js
    assert "fields need' : ' field needs'" not in js


def test_ai_image_prompt_field_has_label_for_textprompt(client):
    """JTN-378: the AI Image Prompt field must render a <label for="textPrompt">
    so getInputLabel() can name it in validation toasts."""
    resp = client.get("/plugin/ai_image")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # The schema renderer emits a <label for="{field.id | default(field.name)}">.
    assert 'for="textPrompt"' in html
    assert 'name="textPrompt"' in html


# ---------------------------------------------------------------------------
# JTN-349: specific validation reasons (not just "is invalid") for numbers/URLs
# ---------------------------------------------------------------------------


def test_form_validator_has_classify_invalid_reasons(client):
    """classifyInvalid should distinguish required/invalid_url/number reasons."""
    resp = client.get("/static/scripts/form_validator.js")
    js = resp.get_data(as_text=True)

    # The classifyInvalid switch now returns specific reason codes.
    for reason in (
        '"required"',
        '"not_a_number"',
        '"below_min"',
        '"above_max"',
        '"invalid_url"',
        '"invalid"',
    ):
        assert reason in js, f"classifyInvalid should emit reason {reason}"


def test_form_validator_describe_reason_exposed(client):
    """describeReason must be exposed on window.FormValidator for other scripts."""
    resp = client.get("/static/scripts/form_validator.js")
    js = resp.get_data(as_text=True)

    assert "describeReason:" in js
    assert "function describeReason(input, reason)" in js


def test_form_validator_describe_reason_messages(client):
    """Each reason code should produce a distinct human-readable suffix."""
    resp = client.get("/static/scripts/form_validator.js")
    js = resp.get_data(as_text=True)

    # Each reason should have a distinct case-label message
    assert '" must be a number"' in js
    assert '" must be at least "' in js
    assert '" must be at most "' in js
    assert '" must be a valid URL"' in js
    assert '" is required"' in js
    assert '" is invalid"' in js


def test_calendar_repeater_has_unique_url_label(client):
    """Each calendar URL input in the template must have a unique label id."""
    resp = client.get("/plugin/calendar")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Template rendering: label for calendarURL0 with visually-hidden class
    assert 'for="calendarURL0"' in html
    assert 'aria-label="Calendar URL 1"' in html
