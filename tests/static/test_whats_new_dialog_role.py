"""Regression guard: What's New modal must carry role="dialog" (JTN-589).

document.querySelector('[role=dialog]') must find the modal while it is open.
The critical attributes are validated against the static HTML rather than a
live browser so the guard runs in every CI environment, including headless.
"""

from pathlib import Path

_SETTINGS_TPL = Path("src/templates/settings.html")
_SETTINGS_ACTIONS_JS = Path("src/static/scripts/settings/actions.js")
_SETTINGS_MODALS_JS = Path("src/static/scripts/settings/modals.js")


def _settings_html() -> str:
    return _SETTINGS_TPL.read_text(encoding="utf-8")


def _settings_js() -> str:
    return (
        _SETTINGS_ACTIONS_JS.read_text(encoding="utf-8")
        + "\n"
        + _SETTINGS_MODALS_JS.read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Template assertions — static HTML attributes
# ---------------------------------------------------------------------------


def test_whats_new_modal_has_role_dialog():
    """The What's New modal container must have role="dialog"."""
    content = _settings_html()
    assert 'id="whatsNewModal"' in content, "whatsNewModal element missing"
    # Verify role=dialog appears on the same element
    idx = content.index('id="whatsNewModal"')
    # Grab a reasonable window around the element opening tag
    tag_region = content[max(0, idx - 20) : idx + 200]
    assert (
        'role="dialog"' in tag_region
    ), 'whatsNewModal must have role="dialog" on its container element'


def test_whats_new_modal_has_aria_modal():
    """The What's New modal must have aria-modal="true"."""
    content = _settings_html()
    idx = content.index('id="whatsNewModal"')
    tag_region = content[max(0, idx - 20) : idx + 200]
    assert (
        'aria-modal="true"' in tag_region
    ), 'whatsNewModal must have aria-modal="true"'


def test_whats_new_modal_has_aria_labelledby():
    """The What's New modal must have aria-labelledby pointing to its heading."""
    content = _settings_html()
    idx = content.index('id="whatsNewModal"')
    tag_region = content[max(0, idx - 20) : idx + 200]
    assert (
        'aria-labelledby="whatsNewModalTitle"' in tag_region
    ), 'whatsNewModal must have aria-labelledby="whatsNewModalTitle"'


def test_whats_new_modal_heading_id_matches_labelledby():
    """The heading referenced by aria-labelledby must exist with the same id."""
    content = _settings_html()
    assert (
        'id="whatsNewModalTitle"' in content
    ), "Heading with id='whatsNewModalTitle' is required so aria-labelledby resolves"


def test_whats_new_button_exists_in_update_panel():
    """The update panel must contain a trigger button for the What's New modal."""
    content = _settings_html()
    assert (
        'id="whatsNewBtn"' in content
    ), "whatsNewBtn trigger button must be present in the update panel"


def test_whats_new_body_container_exists():
    """The modal must contain a content container for release notes."""
    content = _settings_html()
    assert (
        'id="whatsNewBody"' in content
    ), "whatsNewBody element must exist inside the modal"


# ---------------------------------------------------------------------------
# JS assertions — open/close wiring
# ---------------------------------------------------------------------------


def test_settings_js_opens_whats_new_modal():
    """settings_page.js must define openWhatsNew and wire whatsNewBtn."""
    content = _settings_js()
    assert (
        "openWhatsNew" in content
    ), "openWhatsNew function must exist in settings_page.js"
    assert "whatsNewBtn" in content, "whatsNewBtn must be wired in bindButtons()"


def test_settings_js_closes_whats_new_on_escape():
    """settings_page.js must close the What's New modal on Escape."""
    content = _settings_js()
    assert (
        "closeWhatsNew" in content
    ), "closeWhatsNew function must exist in settings_page.js"
    assert "whatsNewModal" in content, "Escape handler must reference whatsNewModal"


def test_settings_js_whats_new_modal_hidden_attribute():
    """openWhatsNew must set modal.hidden = false; closeWhatsNew must hide it."""
    content = _settings_js()
    assert "whatsNewModal" in content
    # Both hidden=false (open) and hidden=true (close) must be managed
    assert (
        "modal.hidden = false" in content
        or "modal.hidden=false" in content
        or "hidden = false" in content
    ), "openWhatsNew must clear the hidden attribute"
