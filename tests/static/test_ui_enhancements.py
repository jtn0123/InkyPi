# pyright: reportMissingImports=false
"""Tests for UI enhancement CSS and styling."""

import re
from pathlib import Path

from flask.testing import FlaskClient

# CSS is now split into @import partials; read all partials from disk
_STYLES_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "styles"
TOGGLE_CSS = _STYLES_DIR / "partials" / "_toggle.css"
FORM_CSS = _STYLES_DIR / "partials" / "_form.css"


def _read_all_css() -> str:
    """Concatenate all CSS partials referenced by main.css."""
    parts = [
        p.read_text(encoding="utf-8")
        for p in sorted(_STYLES_DIR.glob("partials/_*.css"))
    ]
    return "\n".join(parts)


def _css_block(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}", css)
    assert match, f"{selector} rule missing"
    return match.group("body")


def test_main_css_contains_form_enhancement_styles(client: FlaskClient) -> None:
    """Test that main.css contains form enhancement styling."""
    css_content = _read_all_css()

    # Check for enhanced form styling
    assert ".form-input" in css_content
    assert ".form-label" in css_content

    # Check for form input improvements
    assert "min-height: 44px" in css_content


def test_main_css_contains_workflow_and_management_shells(client: FlaskClient) -> None:
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


def test_primary_templates_reduce_inline_handlers() -> None:
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


def test_main_css_contains_enhanced_button_styles(client: FlaskClient) -> None:
    """Test that main.css contains enhanced button styling."""
    css_content = _read_all_css()

    # Check for button enhancements
    assert ".action-button" in css_content
    assert ".action-button.is-secondary" in css_content
    assert ".action-button.compact" in css_content


def test_main_css_contains_toggle_styles(client: FlaskClient) -> None:
    """Test that main.css contains enhanced toggle styling."""
    css_content = _read_all_css()
    toggle_css = TOGGLE_CSS.read_text(encoding="utf-8")
    form_css = FORM_CSS.read_text(encoding="utf-8")
    toggle_input = _css_block(toggle_css, 'input[type="checkbox"].toggle-checkbox')

    # Check for toggle switch styling
    assert ".toggle-container" in css_content
    assert 'input[type="checkbox"].toggle-checkbox' in css_content
    assert ".toggle-checkbox:checked + .toggle-label" in css_content
    assert ".toggle-checkbox:focus-visible + .toggle-label" in css_content
    assert ".toggle-label::before" in css_content
    assert "appearance: none" in toggle_input
    assert "opacity: 0" in toggle_input
    assert "z-index: 1" in toggle_input
    assert "pointer-events: none" in toggle_css
    assert ".form-group.nowrap:not(.toggle-row) > *" in form_css


def test_main_css_contains_responsive_design(client: FlaskClient) -> None:
    """Test that main.css contains responsive design improvements."""
    css_content = _read_all_css()

    # Check for mobile responsive styles
    assert "@media (max-width: 768px)" in css_content
    assert "flex-direction: column" in css_content
    assert "width: 100%" in css_content

    # Check for mobile-specific adjustments
    assert ".form-group.nowrap" in css_content


def test_main_css_contains_animation_styles(client: FlaskClient) -> None:
    """Test that main.css contains animation and transition styling."""
    css_content = _read_all_css()

    # Check for animations
    assert "animation:" in css_content
    assert "transition:" in css_content


def test_main_css_contains_theme_variables(client: FlaskClient) -> None:
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


def test_main_css_contains_spacing_improvements(client: FlaskClient) -> None:
    """Test that main.css contains improved spacing system."""
    css_content = _read_all_css()

    # Check for spacing system
    assert "margin-top: 16px" in css_content
    assert "margin-top: 20px" in css_content

    # Check for reduced excessive spacing
    assert ".form-group:last-child" in css_content
    assert "margin-bottom: 0" in css_content


def test_main_css_contains_accessibility_improvements(client: FlaskClient) -> None:
    """Test that main.css contains accessibility improvements."""
    css_content = _read_all_css()

    # Check for focus styles
    assert ":focus" in css_content
    assert "outline:" in css_content
    assert "box-shadow:" in css_content

    # Check for contrast improvements
    assert "color: var(--text)" in css_content
    assert "background: var(--surface)" in css_content


def test_main_css_contains_status_badges(client: FlaskClient) -> None:
    """Test that main.css contains status badge styling."""
    css_content = _read_all_css()

    # Check for status badge system
    assert ".status-badge" in css_content


def test_main_css_contains_color_picker_improvements(client: FlaskClient) -> None:
    """Test that main.css contains color picker improvements."""
    css_content = _read_all_css()

    # Check for color picker styling
    assert ".color-picker" in css_content
    assert "border-radius: 8px" in css_content


def test_main_css_contains_select_improvements(client: FlaskClient) -> None:
    """Test that main.css contains select element improvements."""
    css_content = _read_all_css()

    # Check for select styling
    assert "select.form-input" in css_content
    assert "appearance: none" in css_content
    assert "background-image:" in css_content
    assert "background-position: right" in css_content


def test_main_css_contains_grid_improvements(client: FlaskClient) -> None:
    """Test that main.css contains grid layout improvements."""
    css_content = _read_all_css()

    # Check for grid system
    assert ".sections-grid" in css_content
    assert ".sections-grid.two-col" in css_content
    assert "grid-template-columns" in css_content
    assert "@media (max-width: 900px)" in css_content


def test_main_css_typography_hierarchy(client: FlaskClient) -> None:
    """Test that main.css contains proper typography hierarchy."""
    css_content = _read_all_css()

    # Check for typography improvements
    assert "font-weight: 700" in css_content
    assert "font-weight: 600" in css_content
    assert "letter-spacing:" in css_content
    assert "line-height:" in css_content


def test_main_css_contains_top_level_theme_normalization_helpers(
    client: FlaskClient,
) -> None:
    css_content = _read_all_css()

    assert ".storage-meter" in css_content
    assert ".storage-meter-fill" in css_content
    assert ".logs-icon" in css_content
    assert ".playlist-thumbnail-modal" in css_content
    assert ".playlist-thumbnail-content" in css_content
    assert ".playlist-thumbnail-info" in css_content


def test_main_css_contains_status_color_variables(client: FlaskClient) -> None:
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


def test_main_css_contains_shimmer_animation(client: FlaskClient) -> None:
    """Test that main.css contains shimmer animation for skeletons."""
    css_content = _read_all_css()

    # Check for shimmer animation
    assert "@keyframes shimmer" in css_content
    assert "background-position: 100% 0" in css_content
    assert "background-position: -100% 0" in css_content

    # Check that skeletons use shimmer animation
    assert "animation: shimmer" in css_content
    assert "background-size: 400% 100%" in css_content
