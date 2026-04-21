# pyright: reportMissingImports=false
"""Tests for plugin page layout fixes (JTN-89, JTN-152).

JTN-89:  Historical — a Configure/Preview mode toggle used to sit above the
         workflow grid; the design refresh removed it so both panels render
         together on every viewport.
JTN-152: API status chips removed from status row (header indicator is sole
         source).
"""

from pathlib import Path

_STYLES_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "styles"
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "src" / "templates"


def _read_partial(name: str) -> str:
    return (_STYLES_DIR / "partials" / name).read_text(encoding="utf-8")


# --- JTN-89: mode bar removed; both panels always render ---------------------


def test_workflow_mode_bar_removed_from_plugin_css():
    """The Configure/Preview mode bar was retired — no selectors should remain."""
    css = _read_partial("_plugins.css")
    assert ".workflow-mode-bar" not in css, (
        ".workflow-mode-bar rule should no longer exist in _plugins.css "
        "(both panels now render together)"
    )
    assert (
        ".workflow-mode-tab" not in css
    ), ".workflow-mode-tab rule should no longer exist in _plugins.css"


def test_plugin_template_has_no_workflow_mode_bar():
    """plugin.html must not render the workflow-mode-bar tablist."""
    template = (_TEMPLATES_DIR / "plugin.html").read_text(encoding="utf-8")
    assert "workflow-mode-bar" not in template
    assert "configureModeBtn" not in template
    assert "previewModeBtn" not in template


# --- JTN-152: duplicate API status chips removed -----------------------------


def test_status_row_has_no_api_chips(client):
    """The .status-row in plugin.html must not contain API ready / API key missing chips."""
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Find the status-row section
    start = html.find('class="status-row')
    assert start != -1, "status-row element not found in plugin page"
    # Extract a reasonable chunk after the status-row opening tag
    section = html[start : start + 500]
    assert "API ready" not in section, "status-row should not contain 'API ready' chip"
    assert (
        "API key missing" not in section
    ), "status-row should not contain 'API key missing' chip"


def test_header_api_indicator_still_present():
    """plugin.html must still contain the header .api-key-indicator."""
    template = (_TEMPLATES_DIR / "plugin.html").read_text(encoding="utf-8")
    assert (
        "api-key-indicator" in template
    ), "Header API key indicator must remain in plugin.html"


def test_plugin_template_uses_overview_and_preview_cards():
    """The plugin page should keep the handoff-style overview + preview framing."""
    template = (_TEMPLATES_DIR / "plugin.html").read_text(encoding="utf-8")
    assert "plugin-editor-overview" in template
    assert "workflow-preview-card" in template
