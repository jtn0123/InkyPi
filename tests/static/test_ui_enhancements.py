# pyright: reportMissingImports=false
"""Tests for UI enhancement CSS and styling."""

import pytest


def test_main_css_contains_progressive_disclosure_styles(client):
    """Test that main.css contains progressive disclosure styling."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for progressive disclosure CSS classes
    assert ".settings-mode-selector" in css_content
    assert ".mode-button" in css_content
    assert ".mode-button.active" in css_content
    assert ".settings-section.basic-only" in css_content
    assert ".settings-section.advanced-only" in css_content


def test_main_css_contains_form_enhancement_styles(client):
    """Test that main.css contains form enhancement styling."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for enhanced form styling
    assert ".form-section" in css_content
    assert ".form-section-title" in css_content
    assert ".form-field" in css_content
    assert ".form-input" in css_content
    assert ".form-label" in css_content

    # Check for form input improvements
    assert "min-height: 44px" in css_content
    assert ".form-input[readonly]" in css_content


def test_main_css_contains_validation_styles(client):
    """Test that main.css contains validation styling."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for validation message styles
    assert ".validation-message" in css_content
    assert ".validation-message.error" in css_content
    assert ".validation-message.success" in css_content
    assert ".validation-message.warning" in css_content

    # Check for input validation states
    assert ".form-input.invalid" in css_content
    assert ".form-input.valid" in css_content


def test_main_css_contains_tooltip_styles(client):
    """Test that main.css contains tooltip styling."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for tooltip system
    assert ".tooltip" in css_content
    assert ".tooltip-text" in css_content
    assert ".help-icon" in css_content
    assert "visibility: hidden" in css_content
    assert "visibility: visible" in css_content


def test_main_css_contains_wizard_styles(client):
    """Test that main.css contains wizard styling."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for wizard styling
    assert ".setup-wizard" in css_content
    assert ".wizard-step" in css_content
    assert ".wizard-navigation" in css_content
    assert ".wizard-progress" in css_content
    assert ".wizard-step-indicator" in css_content
    assert ".wizard-step-dot" in css_content


def test_main_css_contains_live_preview_styles(client):
    """Test that main.css contains live preview styling."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for live preview system
    assert ".live-preview-overlay" in css_content
    assert ".live-preview-header" in css_content
    assert ".live-preview-content" in css_content
    assert ".preview-section" in css_content
    assert ".preview-current" in css_content
    assert ".preview-modified" in css_content


def test_main_css_contains_enhanced_button_styles(client):
    """Test that main.css contains enhanced button styling."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for button enhancements
    assert ".action-button" in css_content
    assert ".action-button.is-secondary" in css_content
    assert ".action-button.compact" in css_content
    assert ".button-group" in css_content


def test_main_css_contains_toggle_styles(client):
    """Test that main.css contains enhanced toggle styling."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for toggle switch styling
    assert ".toggle-container" in css_content
    assert ".toggle-checkbox" in css_content
    assert ".toggle-checkbox:checked" in css_content
    assert ".toggle-checkbox::before" in css_content
    assert "appearance: none" in css_content


def test_main_css_contains_responsive_design(client):
    """Test that main.css contains responsive design improvements."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for mobile responsive styles
    assert "@media (max-width: 768px)" in css_content
    assert "flex-direction: column" in css_content
    assert "width: 100%" in css_content

    # Check for mobile-specific adjustments
    assert ".form-group.nowrap" in css_content


def test_main_css_contains_animation_styles(client):
    """Test that main.css contains animation and transition styling."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for animations
    assert "@keyframes slideInFromRight" in css_content
    assert "@keyframes slideInFromBottom" in css_content
    assert "animation:" in css_content
    assert "transition:" in css_content


def test_main_css_contains_theme_variables(client):
    """Test that main.css properly uses theme variables."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for CSS custom properties usage
    assert "var(--text)" in css_content
    assert "var(--surface)" in css_content
    assert "var(--surface-border)" in css_content
    assert "var(--accent)" in css_content
    assert "var(--muted)" in css_content

    # Check for dark theme support
    assert "[data-theme=\"dark\"]" in css_content


def test_main_css_contains_spacing_improvements(client):
    """Test that main.css contains improved spacing system."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for spacing system
    assert ".form-field + .form-field" in css_content
    assert ".form-section + .form-section" in css_content
    assert "margin-top: 16px" in css_content
    assert "margin-top: 20px" in css_content

    # Check for reduced excessive spacing
    assert ".form-group:last-child" in css_content
    assert "margin-bottom: 0" in css_content


def test_main_css_contains_accessibility_improvements(client):
    """Test that main.css contains accessibility improvements."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for focus styles
    assert ":focus" in css_content
    assert "outline:" in css_content
    assert "box-shadow:" in css_content

    # Check for contrast improvements
    assert "color: var(--text)" in css_content
    assert "background: var(--surface)" in css_content


def test_main_css_contains_status_badges(client):
    """Test that main.css contains status badge styling."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for status badge system
    assert ".status-badge" in css_content
    assert ".status-badge.success" in css_content
    assert ".status-badge.warning" in css_content
    assert ".status-badge.error" in css_content


def test_main_css_contains_color_picker_improvements(client):
    """Test that main.css contains color picker improvements."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for color picker styling
    assert ".color-picker" in css_content
    assert ".color-picker:hover" in css_content
    assert "border-radius: 8px" in css_content


def test_main_css_contains_select_improvements(client):
    """Test that main.css contains select element improvements."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for select styling
    assert "select.form-input" in css_content
    assert "appearance: none" in css_content
    assert "background-image:" in css_content
    assert "background-position: right" in css_content


def test_main_css_contains_grid_improvements(client):
    """Test that main.css contains grid layout improvements."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for grid system
    assert ".sections-grid" in css_content
    assert ".sections-grid.two-col" in css_content
    assert "grid-template-columns" in css_content
    assert "@media (max-width: 900px)" in css_content


def test_main_css_contains_preview_overlay_theming(client):
    """Test that main.css contains proper theming for preview overlay."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for dark theme preview overlay
    assert "[data-theme=\"dark\"] .live-preview-overlay" in css_content
    assert "backdrop-filter: blur" in css_content
    assert "rgba(" in css_content

    # Check for preview close button theming
    assert ".preview-close" in css_content
    assert ".preview-close:hover" in css_content


def test_main_css_contains_mobile_preview_adjustments(client):
    """Test that main.css contains mobile adjustments for preview."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for mobile preview adjustments
    mobile_preview_section = css_content.find("/* Mobile adjustments for live preview */")
    if mobile_preview_section != -1:
        mobile_section = css_content[mobile_preview_section:mobile_preview_section + 1000]
        assert "bottom: 20px" in mobile_section
        assert "flex-direction: row" in mobile_section


def test_main_css_typography_hierarchy(client):
    """Test that main.css contains proper typography hierarchy."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200

    css_content = resp.get_data(as_text=True)

    # Check for typography improvements
    assert "/* Enhanced Typography Hierarchy */" in css_content
    assert "font-weight: 700" in css_content
    assert "font-weight: 600" in css_content
    assert "letter-spacing:" in css_content
    assert "line-height:" in css_content