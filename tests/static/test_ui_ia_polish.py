# pyright: reportMissingImports=false
"""Targeted tests for final UI IA and polish additions."""

from pathlib import Path

_STYLES_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "styles"


def _read_all_css() -> str:
    """Concatenate all CSS partials referenced by main.css."""
    parts = [
        p.read_text(encoding="utf-8")
        for p in sorted(_STYLES_DIR.glob("partials/_*.css"))
    ]
    return "\n".join(parts)


def test_settings_page_contains_section_nav_and_loading_panels(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "section-basics" in html
    assert "section-observability" in html
    assert 'id="benchSummary"' in html and "loading-panel" in html
    assert 'id="healthSummary"' in html and "loading-panel" in html
    assert 'id="isolationSummary"' in html and "loading-panel" in html


def test_plugin_page_contains_status_chips_and_unique_schedule_ids(client):
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "plugin-mode-row" in html
    assert "status-chip" in html
    assert 'id="scheduleInterval"' in html
    assert 'id="scheduleUnit"' in html
    assert 'id="scheduleTime"' in html


def test_main_css_contains_new_ia_polish_classes(client):
    css = _read_all_css()

    assert ".section-nav" in css
    assert ".status-chip" in css
    assert ".loading-panel" in css
    assert ".section-focus" in css


def test_settings_logs_toggle_respects_safe_area(client):
    """JTN-339: Show Logs floating action must clear the iOS safe area
    and the settings page must reserve bottom padding so the toggle
    never covers the last in-flow action on narrow mobile viewports."""
    css = _read_all_css()

    assert ".settings-logs-toggle" in css
    # Floating button accounts for the iOS home indicator / chrome.
    assert "env(safe-area-inset-bottom" in css
    # Settings shell reserves bottom padding for the floating action.
    assert ".page-shell-management" in css
