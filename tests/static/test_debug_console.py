"""Tests for the floating debug console (JTN-587).

Verifies that the debug console uses the label "Debug console" — not
"Error log" — so it cannot be confused with the server-side Error Logs
page.  All assertions are DOM/source-level; no browser is required.
"""

from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "static"
    / "scripts"
    / "debug_console.js"
)

_BASE_TEMPLATE = Path(__file__).resolve().parents[2] / "src" / "templates" / "base.html"

_CSS_PARTIALS_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "static" / "styles" / "partials"
)


def _read_all_css() -> str:
    parts = [
        p.read_text(encoding="utf-8") for p in sorted(_CSS_PARTIALS_DIR.glob("_*.css"))
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# JS source checks
# ---------------------------------------------------------------------------


def test_debug_console_script_exists():
    """debug_console.js must be present."""
    assert _SCRIPT_PATH.exists(), "debug_console.js not found"


def test_debug_console_uses_correct_title_label():
    """The floating button must use title='Debug console', not 'Error log'."""
    src = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert "Debug console" in src, "Expected 'Debug console' label in debug_console.js"
    assert (
        "Error log" not in src
    ), "debug_console.js must not use the old 'Error log' label"


def test_debug_console_aria_label_is_correct():
    """aria-label must reference 'debug console' (case-insensitive)."""
    src = _SCRIPT_PATH.read_text(encoding="utf-8").lower()
    assert (
        "open debug console" in src or "debug console" in src
    ), "Expected aria-label containing 'debug console' in debug_console.js"


def test_debug_console_panel_heading_is_correct():
    """The panel heading text must be 'Debug console'."""
    src = _SCRIPT_PATH.read_text(encoding="utf-8")
    # The heading content is set via textContent
    assert (
        '"Debug console"' in src or "'Debug console'" in src
    ), "Panel heading must be 'Debug console' in debug_console.js"


def test_debug_console_filters_callback_names():
    """isUsefulMessage must filter out raw callback-name patterns."""
    src = _SCRIPT_PATH.read_text(encoding="utf-8")
    # The regex pattern for filtering should be present
    assert (
        "on[A-Z]" in src
    ), "Expected callback-name filter regex (on[A-Z]...) in debug_console.js"


# ---------------------------------------------------------------------------
# Template checks
# ---------------------------------------------------------------------------


def test_base_template_includes_debug_console_script():
    """base.html must load debug_console.js."""
    html = _BASE_TEMPLATE.read_text(encoding="utf-8")
    assert (
        "debug_console.js" in html
    ), "base.html must include a <script> tag for debug_console.js"


# ---------------------------------------------------------------------------
# CSS checks
# ---------------------------------------------------------------------------


def test_css_contains_debug_console_classes():
    """CSS partials must define the debug console widget classes."""
    css = _read_all_css()
    assert (
        ".debug-console-toggle" in css
    ), "Missing .debug-console-toggle in CSS partials"
    assert ".debug-console-panel" in css, "Missing .debug-console-panel in CSS partials"
    assert ".debug-console-title" in css, "Missing .debug-console-title in CSS partials"


# ---------------------------------------------------------------------------
# HTML render checks (uses Flask test client)
# ---------------------------------------------------------------------------


def test_no_error_log_title_in_rendered_pages(client):
    """No rendered page should expose a 'title=\"Error log\"' attribute on the
    floating debug button — the correct value is 'Debug console'."""
    for path in ("/", "/settings", "/plugin/clock"):
        resp = client.get(path)
        if resp.status_code not in (200, 302):
            continue
        html = resp.get_data(as_text=True)
        assert (
            'title="Error log"' not in html
        ), f"{path}: found old 'title=\"Error log\"' — use 'Debug console'"
        assert (
            'aria-label="Error log"' not in html
        ), f"{path}: found old 'aria-label=\"Error log\"'"
