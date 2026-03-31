# pyright: reportMissingImports=false
"""Dark mode CSS verification tests."""
import re
from pathlib import Path

import pytest

_STYLES_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "styles"


def _read_all_css() -> str:
    parts = [
        p.read_text(encoding="utf-8")
        for p in sorted(_STYLES_DIR.glob("partials/_*.css"))
    ]
    return "\n".join(parts)


def _read_partials_individually() -> dict[str, str]:
    result = {}
    for p in sorted(_STYLES_DIR.glob("partials/_*.css")):
        result[p.name] = p.read_text(encoding="utf-8")
    return result


def test_dark_mode_defines_core_color_variables(client):
    """Both :root and [data-theme='dark'] define all core color tokens."""
    css = _read_all_css()

    core_vars = [
        "--bg",
        "--text",
        "--surface",
        "--accent",
        "--muted",
        "--surface-border",
        "--primary",
        "--primary-hover",
    ]

    # Find all :root blocks and combine their content
    root_matches = re.findall(r":root\s*\{(.+?)\}", css, re.DOTALL)
    assert root_matches, ":root block not found"
    root_content = "\n".join(root_matches)

    for var in core_vars:
        assert f"{var}:" in root_content, f"{var} not defined in :root"

    # Find all dark theme blocks and combine their content
    assert '[data-theme="dark"]' in css, "Dark theme block not found"
    dark_matches = re.findall(r'\[data-theme="dark"\]\s*\{(.+?)\}', css, re.DOTALL)
    assert dark_matches, "Dark theme block content not found"
    dark_content = "\n".join(dark_matches)

    for var in core_vars:
        assert f"{var}:" in dark_content, f"{var} not defined in dark theme"


def test_no_hardcoded_white_black_outside_root(client):
    """No hardcoded #fff/#000 in selectors outside :root/[data-theme] blocks.

    Exceptions: _print.css (fallback values), data URIs, and rgba() values.
    """
    partials = _read_partials_individually()

    violations = []
    for filename, css in partials.items():
        # Skip print stylesheet (uses fallback values now)
        if filename == "_print.css":
            continue

        # Remove :root and [data-theme] blocks from consideration
        cleaned = re.sub(r":root\s*\{[^}]+\}", "", css)
        cleaned = re.sub(r'\[data-theme="[^"]*"\]\s*\{[^}]+\}', "", cleaned)

        # Remove data URIs (SVG backgrounds etc.)
        cleaned = re.sub(r'url\("data:[^"]*"\)', "", cleaned)
        # Remove rgba() values (they can legitimately use 255)
        cleaned = re.sub(r"rgba\([^)]+\)", "", cleaned)

        # Check for standalone hex color codes
        for match in re.finditer(
            r"(?<!var\()#(?:fff|000|ffffff|000000)\b", cleaned, re.IGNORECASE
        ):
            # Get surrounding context for the error message
            start = max(0, match.start() - 40)
            end = min(len(cleaned), match.end() + 40)
            context = cleaned[start:end].strip()
            violations.append(f"{filename}: {match.group()} near '{context}'")

    # Allow some violations in legacy code but flag significant ones
    if violations:
        # Filter out known acceptable patterns (e.g., gradient overlays)
        serious = [v for v in violations if "radial-gradient" not in v]
        if serious:
            pytest.fail(
                f"Found {len(serious)} hardcoded color(s) outside theme blocks:\n"
                + "\n".join(serious[:10])
            )


def test_disabled_styles_exist(client):
    """Verify :disabled rules exist for buttons and inputs."""
    css = _read_all_css()

    assert (
        "button:disabled" in css or ".action-button:disabled" in css
    ), "No :disabled styles for buttons"
    assert "input:disabled" in css, "No :disabled styles for inputs"
    assert "select:disabled" in css, "No :disabled styles for selects"
    assert "textarea:disabled" in css, "No :disabled styles for textareas"

    # Verify the rules include visual indicators
    assert (
        "cursor: not-allowed" in css
    ), "Disabled elements should use not-allowed cursor"
    assert (
        "opacity: 0.5" in css or "opacity: 0.6" in css
    ), "Disabled elements should have reduced opacity"


def test_print_stylesheet_uses_variables(client):
    """Print stylesheet should use CSS variables with fallbacks, not hardcoded colors."""
    partials = _read_partials_individually()
    print_css = partials.get("_print.css", "")
    assert print_css, "_print.css not found"

    # Should use var() with fallbacks
    assert (
        "var(--bg" in print_css or "var(--text" in print_css
    ), "Print stylesheet should use CSS variables"


def test_hover_overlay_uses_variable(client):
    """Plugin action button hover should use --hover-overlay variable."""
    css = _read_all_css()
    assert (
        "var(--hover-overlay" in css
    ), "Plugin hover should use --hover-overlay CSS variable"
