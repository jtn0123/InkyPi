# pyright: reportMissingImports=false
"""Tests for UI enhancement CSS and styling."""

from pathlib import Path

# CSS is now split into @import partials; read all partials from disk
_STYLES_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "styles"


def _read_all_css() -> str:
    """Concatenate all CSS partials referenced by main.css."""
    parts = [
        p.read_text(encoding="utf-8")
        for p in sorted(_STYLES_DIR.glob("partials/_*.css"))
    ]
    return "\n".join(parts)


def test_main_css_contains_progressive_disclosure_styles(client):
    """Test that main.css contains progressive disclosure styling."""
    css_content = _read_all_css()

    # Check for progressive disclosure CSS classes
    assert ".settings-mode-selector" in css_content
    assert ".mode-button" in css_content
    assert ".mode-button.active" in css_content
    assert ".settings-section.basic-only" in css_content
    assert ".settings-section.advanced-only" in css_content


def test_main_css_contains_form_enhancement_styles(client):
    """Test that main.css contains form enhancement styling."""
    css_content = _read_all_css()

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
    css_content = _read_all_css()

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
    css_content = _read_all_css()

    # Check for tooltip system
    assert ".tooltip" in css_content
    assert ".tooltip-text" in css_content
    assert ".help-icon" in css_content
    assert "visibility: hidden" in css_content
    assert "visibility: visible" in css_content


def test_main_css_contains_wizard_styles(client):
    """Test that main.css contains wizard styling."""
    css_content = _read_all_css()

    # Check for wizard styling
    assert ".setup-wizard" in css_content
    assert ".wizard-step" in css_content
    assert ".wizard-navigation" in css_content
    assert ".wizard-progress" in css_content
    assert ".wizard-step-indicator" in css_content
    assert ".wizard-step-dot" in css_content


def test_main_css_contains_live_preview_styles(client):
    """Test that main.css contains live preview styling."""
    css_content = _read_all_css()

    # Check for live preview system
    assert ".live-preview-overlay" in css_content
    assert ".live-preview-header" in css_content
    assert ".live-preview-content" in css_content
    assert ".preview-section" in css_content
    assert ".preview-current" in css_content
    assert ".preview-modified" in css_content


def test_main_css_contains_workflow_and_management_shells(client):
    css_content = _read_all_css()

    assert ".workflow-layout" in css_content
    assert ".dashboard-hero" in css_content
    assert ".settings-grid" in css_content
    assert ".logs-viewer" in css_content
    assert ".settings-console-layout" in css_content
    assert ".settings-side-nav" in css_content
    assert ".danger-zone" in css_content
    # JTN-649 — history danger zone has a divider + label + unknown-source style
    assert ".danger-zone-divider" in css_content
    assert ".danger-zone-label" in css_content
    assert ".history-source-unknown" in css_content
    assert ".playlist-toggle-button" in css_content
    assert ".modal-sheet" in css_content
    assert "body.modal-open" in css_content
    assert ".title-stack" in css_content
    assert ".history-card-body" in css_content
    assert ".compact-repeater" in css_content


def test_primary_templates_reduce_inline_handlers():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "templates"
    for template_name in (
        "plugin.html",
        "settings.html",
        "inky.html",
        "history.html",
        "api_keys.html",
        "playlist.html",
    ):
        content = (root / template_name).read_text()
        assert "onclick=" not in content
        assert "window.onclick" not in content
        assert "skip-nav" not in content
        assert "Skip to main content" not in content
        assert "Skip to settings content" not in content


def test_main_css_contains_enhanced_button_styles(client):
    """Test that main.css contains enhanced button styling."""
    css_content = _read_all_css()

    # Check for button enhancements
    assert ".action-button" in css_content
    assert ".action-button.is-secondary" in css_content
    assert ".action-button.compact" in css_content
    assert ".button-group" in css_content


def test_main_css_contains_toggle_styles(client):
    """Test that main.css contains enhanced toggle styling."""
    css_content = _read_all_css()

    # Check for toggle switch styling
    assert ".toggle-container" in css_content
    assert 'input[type="checkbox"].toggle-checkbox' in css_content
    assert ".toggle-checkbox:checked + .toggle-label" in css_content
    assert ".toggle-checkbox:focus-visible + .toggle-label" in css_content
    assert ".toggle-label::before" in css_content
    assert "appearance: none" in css_content
    assert "opacity: 0" in css_content
    assert "pointer-events: none" in css_content
    assert ".form-group.nowrap:not(.toggle-row) > *" in css_content


def test_main_css_contains_responsive_design(client):
    """Test that main.css contains responsive design improvements."""
    css_content = _read_all_css()

    # Check for mobile responsive styles
    assert "@media (max-width: 768px)" in css_content
    assert "flex-direction: column" in css_content
    assert "width: 100%" in css_content

    # Check for mobile-specific adjustments
    assert ".form-group.nowrap" in css_content


def test_main_css_contains_animation_styles(client):
    """Test that main.css contains animation and transition styling."""
    css_content = _read_all_css()

    # Check for animations
    assert "@keyframes slideInFromRight" in css_content
    assert "@keyframes slideInFromBottom" in css_content
    assert "animation:" in css_content
    assert "transition:" in css_content


def test_main_css_contains_theme_variables(client):
    """Test that main.css properly uses theme variables."""
    css_content = _read_all_css()

    # Check for CSS custom properties usage
    assert "var(--text)" in css_content
    assert "var(--surface)" in css_content
    assert "var(--surface-border)" in css_content
    assert "var(--accent)" in css_content
    assert "var(--muted)" in css_content

    # Check for dark theme support
    assert '[data-theme="dark"]' in css_content
    assert "--primary:" in css_content
    assert "--primary-hover:" in css_content
    assert "--text-muted:" in css_content
    assert "--text-secondary:" in css_content
    assert "--modal-overlay:" in css_content
    assert "--modal-bg:" in css_content
    assert "--border-color:" in css_content
    assert "--shadow-medium:" in css_content
    assert "--close-btn-color:" in css_content
    assert "--close-btn-hover:" in css_content


def test_main_css_contains_spacing_improvements(client):
    """Test that main.css contains improved spacing system."""
    css_content = _read_all_css()

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
    css_content = _read_all_css()

    # Check for focus styles
    assert ":focus" in css_content
    assert "outline:" in css_content
    assert "box-shadow:" in css_content

    # Check for contrast improvements
    assert "color: var(--text)" in css_content
    assert "background: var(--surface)" in css_content


def test_main_css_contains_status_badges(client):
    """Test that main.css contains status badge styling."""
    css_content = _read_all_css()

    # Check for status badge system
    assert ".status-badge" in css_content
    assert ".status-badge.success" in css_content
    assert ".status-badge.warning" in css_content
    assert ".status-badge.error" in css_content


def test_main_css_contains_color_picker_improvements(client):
    """Test that main.css contains color picker improvements."""
    css_content = _read_all_css()

    # Check for color picker styling
    assert ".color-picker" in css_content
    assert ".color-picker:hover" in css_content
    assert "border-radius: 8px" in css_content


def test_main_css_contains_select_improvements(client):
    """Test that main.css contains select element improvements."""
    css_content = _read_all_css()

    # Check for select styling
    assert "select.form-input" in css_content
    assert "appearance: none" in css_content
    assert "background-image:" in css_content
    assert "background-position: right" in css_content


def test_main_css_contains_grid_improvements(client):
    """Test that main.css contains grid layout improvements."""
    css_content = _read_all_css()

    # Check for grid system
    assert ".sections-grid" in css_content
    assert ".sections-grid.two-col" in css_content
    assert "grid-template-columns" in css_content
    assert "@media (max-width: 900px)" in css_content


def test_main_css_contains_preview_overlay_theming(client):
    """Test that main.css contains proper theming for preview overlay."""
    css_content = _read_all_css()

    # Check for dark theme preview overlay
    assert '[data-theme="dark"] .live-preview-overlay' in css_content
    assert "backdrop-filter: blur" in css_content
    assert "rgba(" in css_content

    # Check for preview close button theming
    assert ".preview-close" in css_content
    assert ".preview-close:hover" in css_content


def test_main_css_contains_mobile_preview_adjustments(client):
    """Test that main.css contains mobile adjustments for preview."""
    css_content = _read_all_css()

    # Check for mobile preview adjustments
    mobile_preview_section = css_content.find(
        "/* Mobile adjustments for live preview */"
    )
    if mobile_preview_section != -1:
        mobile_section = css_content[
            mobile_preview_section : mobile_preview_section + 1000
        ]
        assert "bottom: 20px" in mobile_section
        assert "flex-direction: row" in mobile_section


def test_main_css_typography_hierarchy(client):
    """Test that main.css contains proper typography hierarchy."""
    css_content = _read_all_css()

    # Check for typography improvements
    assert "/* Enhanced Typography Hierarchy */" in css_content
    assert "font-weight: 700" in css_content
    assert "font-weight: 600" in css_content
    assert "letter-spacing:" in css_content
    assert "line-height:" in css_content


def test_main_css_contains_enhanced_skeleton_styles(client):
    """Test that main.css contains enhanced skeleton loading styles."""
    css_content = _read_all_css()

    # Check for plugin-specific skeleton patterns
    assert ".plugin-skeleton" in css_content
    assert ".plugin-skeleton-weather" in css_content
    assert ".plugin-skeleton-calendar" in css_content
    assert ".plugin-skeleton-image" in css_content
    assert ".plugin-skeleton-text" in css_content

    # Check for skeleton components
    assert ".skeleton-weather-header" in css_content
    assert ".skeleton-weather-icon" in css_content
    assert ".skeleton-calendar-grid" in css_content
    assert ".skeleton-image-main" in css_content

    # Check for progress skeleton
    assert ".progress-skeleton" in css_content
    assert ".skeleton-progress-steps" in css_content
    assert ".skeleton-step-indicator" in css_content


def test_main_css_contains_enhanced_progress_styles(client):
    """Test that main.css contains enhanced progress display styles."""
    css_content = _read_all_css()

    # Check for enhanced progress display
    assert ".enhanced-progress-header" in css_content
    assert ".progress-title-section" in css_content
    assert ".progress-subtitle" in css_content
    assert ".enhanced-progress-bar-section" in css_content
    assert ".enhanced-progress-fill" in css_content

    # Check for step indicators
    assert ".enhanced-progress-steps" in css_content
    assert ".enhanced-step" in css_content
    assert ".enhanced-step.active" in css_content
    assert ".enhanced-step.completed" in css_content
    assert ".enhanced-step.failed" in css_content

    # Check for progress details
    assert ".enhanced-progress-details" in css_content
    assert ".enhanced-progress-log" in css_content
    assert ".log-entry" in css_content
    assert "var(--primary)" in css_content
    assert "var(--text-muted)" in css_content


def test_main_css_contains_api_validation_styles(client):
    """Test that main.css contains API validation indicator styles."""
    css_content = _read_all_css()

    # Check for API validation indicators
    assert ".api-validation-indicator" in css_content
    assert ".validation-status" in css_content
    assert ".status-icon" in css_content
    assert ".status-text" in css_content

    # Check for validation states
    assert ".validation-status.status-idle" in css_content
    assert ".validation-status.status-validating" in css_content
    assert ".validation-status.status-success" in css_content
    assert ".validation-status.status-error" in css_content

    # Check for validation details
    assert ".validation-details" in css_content
    assert ".detail-item" in css_content
    assert ".detail-label" in css_content
    assert ".detail-value" in css_content

    # Check for spin animation
    assert "@keyframes spin" in css_content
    assert "var(--primary-bg)" in css_content
    assert "var(--text-muted)" in css_content


def test_main_css_contains_top_level_theme_normalization_helpers(client):
    css_content = _read_all_css()

    assert ".storage-meter" in css_content
    assert ".storage-meter-fill" in css_content
    assert ".logs-icon" in css_content
    assert ".playlist-thumbnail-modal" in css_content
    assert ".playlist-thumbnail-content" in css_content
    assert ".playlist-thumbnail-info" in css_content


def test_main_css_contains_operation_status_styles(client):
    """Test that main.css contains operation status indicator styles."""
    css_content = _read_all_css()

    # Check for operation status container
    assert ".operation-status-container" in css_content
    assert ".status-header" in css_content
    assert ".status-summary" in css_content
    assert ".status-count" in css_content
    assert ".status-rate" in css_content

    # Check for operation items
    assert ".operation-item" in css_content
    assert ".operation-header" in css_content
    assert ".operation-icon" in css_content
    assert ".operation-description" in css_content
    assert ".operation-time" in css_content

    # Check for operation states
    assert ".operation-item.status-in_progress" in css_content
    assert ".operation-item.status-completed" in css_content
    assert ".operation-item.status-failed" in css_content
    assert ".operation-item.status-cancelled" in css_content

    # Check for operation progress
    assert ".operation-progress" in css_content
    assert ".operation-step" in css_content
    assert ".operation-error" in css_content

    # Check for mobile optimizations
    assert "@media (max-width: 640px)" in css_content


def test_main_css_contains_status_color_variables(client):
    """Test that main.css contains status color variables."""
    css_content = _read_all_css()

    # Check for status color variables
    assert "--success-bg:" in css_content
    assert "--error-bg:" in css_content
    assert "--primary-bg:" in css_content

    # Check for dark theme variants
    assert '[data-theme="dark"]' in css_content and "--success-bg:" in css_content
    assert '[data-theme="dark"]' in css_content and "--error-bg:" in css_content
    assert '[data-theme="dark"]' in css_content and "--primary-bg:" in css_content


def test_main_css_contains_shimmer_animation(client):
    """Test that main.css contains shimmer animation for skeletons."""
    css_content = _read_all_css()

    # Check for shimmer animation
    assert "@keyframes shimmer" in css_content
    assert "background-position: 100% 0" in css_content
    assert "background-position: -100% 0" in css_content

    # Check that skeletons use shimmer animation
    assert "animation: shimmer" in css_content
    assert "background-size: 400% 100%" in css_content
