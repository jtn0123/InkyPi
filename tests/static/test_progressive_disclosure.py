# pyright: reportMissingImports=false
"""Tests for progressive disclosure JavaScript functionality."""

import pytest


def test_progressive_disclosure_script_exists(client):
    """Test that progressive disclosure script is accessible."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for main class definition
    assert "class ProgressiveDisclosure" in script_content
    assert "constructor()" in script_content
    assert "init()" in script_content


def test_progressive_disclosure_contains_mode_selector(client):
    """Test that progressive disclosure script contains mode selector functionality."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for mode selector creation
    assert "createModeSelector()" in script_content
    assert "settings-mode-selector" in script_content
    assert "mode-button" in script_content
    assert "Basic Setup" in script_content
    assert "Advanced Options" in script_content


def test_progressive_disclosure_contains_validation_system(client):
    """Test that progressive disclosure script contains validation functionality."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for validation methods
    assert "setupValidation()" in script_content
    assert "validateField(" in script_content
    assert "addValidationRule(" in script_content
    assert "showValidationMessage(" in script_content

    # Check for validation message types
    assert "validation-message error" in script_content
    assert "validation-message success" in script_content
    assert "validation-message warning" in script_content


def test_progressive_disclosure_contains_tooltip_system(client):
    """Test that progressive disclosure script contains tooltip functionality."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for tooltip methods
    assert "setupTooltips()" in script_content
    assert "showTooltip(" in script_content
    assert "hideTooltip(" in script_content
    assert "data-tooltip" in script_content


def test_progressive_disclosure_contains_wizard_system(client):
    """Test that progressive disclosure script contains wizard functionality."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for wizard methods
    assert "setupWizard()" in script_content
    assert "initializeWizard(" in script_content
    assert "completeWizard(" in script_content

    # Check for wizard navigation
    assert "wizardPrev" in script_content
    assert "wizardNext" in script_content
    assert "wizard-step-dot" in script_content


def test_progressive_disclosure_contains_live_preview(client):
    """Test that progressive disclosure script contains live preview functionality."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for live preview methods
    assert "initLivePreview()" in script_content
    assert "updateLivePreview(" in script_content
    assert "applyPreviewStyles(" in script_content

    # Check for preview overlay
    assert "live-preview-overlay" in script_content
    assert "preview-current" in script_content
    assert "preview-modified" in script_content


def test_progressive_disclosure_contains_form_organization(client):
    """Test that progressive disclosure script contains form organization functionality."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for form organization methods
    assert "organizeFormSections()" in script_content
    assert "settings-section" in script_content
    assert "basic-only" in script_content
    assert "advanced-only" in script_content


def test_progressive_disclosure_contains_event_handling(client):
    """Test that progressive disclosure script contains proper event handling."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for event listeners
    assert "addEventListener" in script_content
    assert "click" in script_content
    assert "input" in script_content
    assert "change" in script_content

    # Check for custom events
    assert "settingsModeChanged" in script_content
    assert "wizardCompleted" in script_content


def test_progressive_disclosure_contains_localStorage_integration(client):
    """Test that progressive disclosure script contains localStorage functionality."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for localStorage usage
    assert "localStorage" in script_content
    assert "inkypi_settings_mode" in script_content
    assert "loadSavedMode()" in script_content


def test_progressive_disclosure_contains_accessibility_features(client):
    """Test that progressive disclosure script contains accessibility features."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for ARIA attributes
    assert "aria-live" in script_content
    assert "aria-disabled" in script_content

    # Check for keyboard navigation
    assert "tabindex" in script_content


def test_progressive_disclosure_contains_error_handling(client):
    """Test that progressive disclosure script contains error handling."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for try-catch blocks
    assert "try {" in script_content
    assert "catch" in script_content

    # Check for localStorage error handling
    assert "localStorage.setItem" in script_content
    assert "// Ignore localStorage errors" in script_content


def test_progressive_disclosure_contains_validation_rules(client):
    """Test that progressive disclosure script contains validation rule examples."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for validation rule structure
    assert "validate: (value)" in script_content
    assert "valid: true" in script_content
    assert "valid: false" in script_content
    assert "message:" in script_content


def test_progressive_disclosure_contains_preview_styling(client):
    """Test that progressive disclosure script contains preview styling functionality."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for style application methods
    assert "applyPreviewStyles(" in script_content
    assert "FormData" in script_content

    # Check for style properties
    assert "backgroundColor" in script_content
    assert "border" in script_content
    assert "padding" in script_content


def test_progressive_disclosure_contains_wizard_completion(client):
    """Test that progressive disclosure script contains wizard completion handling."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for completion logic
    assert "completeWizard(" in script_content
    assert "showResponseModal" in script_content
    assert "Setup wizard completed" in script_content


def test_progressive_disclosure_module_export(client):
    """Test that progressive disclosure script can be used as a module."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for module export
    assert "module.exports" in script_content
    assert "typeof module !== 'undefined'" in script_content


def test_progressive_disclosure_dom_ready_initialization(client):
    """Test that progressive disclosure script initializes on DOM ready."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for DOM ready initialization
    assert "DOMContentLoaded" in script_content
    assert "window.progressiveDisclosure" in script_content
    assert "new ProgressiveDisclosure" in script_content


def test_progressive_disclosure_contains_color_utility(client):
    """Test that progressive disclosure script contains color utility functions."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for color processing
    assert "getHueFromColor(" in script_content
    assert "parseInt" in script_content
    assert "hue-rotate" in script_content


def test_progressive_disclosure_form_field_detection(client):
    """Test that progressive disclosure script can detect form fields properly."""
    resp = client.get("/static/scripts/progressive_disclosure.js")
    assert resp.status_code == 200

    script_content = resp.get_data(as_text=True)

    # Check for form field selectors
    assert ".form-input" in script_content
    assert ".form-field" in script_content
    assert "settings-container" in script_content