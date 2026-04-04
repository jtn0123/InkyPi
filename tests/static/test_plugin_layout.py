# pyright: reportMissingImports=false
"""Tests for plugin page layout fixes (JTN-89, JTN-152).

JTN-89:  Tab bar hidden on desktop, visible only on mobile.
JTN-152: API status chips removed from status row (header indicator is sole source).
"""

import re
from pathlib import Path

_STYLES_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "styles"
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "src" / "templates"


def _read_partial(name: str) -> str:
    return (_STYLES_DIR / "partials" / name).read_text(encoding="utf-8")


# --- JTN-89: desktop tab bar hidden, mobile visible --------------------------


def test_workflow_mode_bar_hidden_on_desktop():
    """The .workflow-mode-bar rule in _plugins.css must include display: none."""
    css = _read_partial("_plugins.css")
    # Find the .workflow-mode-bar block and verify display: none
    block = re.search(r"\.workflow-mode-bar\s*\{([^}]+)\}", css, re.DOTALL)
    assert block, ".workflow-mode-bar rule not found in _plugins.css"
    assert "display: none" in block.group(
        1
    ), ".workflow-mode-bar should have display: none on desktop"


def test_workflow_mode_bar_visible_on_mobile():
    """Inside a @media query in _responsive.css, .workflow-mode-bar must be display: flex."""
    css = _read_partial("_responsive.css")
    # Find .workflow-mode-bar rule and check it has display: flex
    assert (
        ".workflow-mode-bar" in css
    ), ".workflow-mode-bar must exist in _responsive.css"
    # Find the specific rule block
    pattern = r"\.workflow-mode-bar\s*\{[^}]*display:\s*flex"
    assert re.search(
        pattern, css
    ), ".workflow-mode-bar should have display: flex in responsive CSS"


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
