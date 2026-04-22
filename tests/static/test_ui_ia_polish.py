# pyright: reportMissingImports=false
"""Targeted tests for final UI IA and polish additions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_STYLES_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "styles"
SETTINGS_HTML = ROOT / "src" / "templates" / "settings.html"


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
    assert 'id="settingsLogsToggle"' in html
    assert 'id="settingsLogsPanel"' in html
    assert 'id="benchSummary"' in html and "loading-panel" in html
    assert 'id="healthSummary"' in html and "loading-panel" in html
    assert 'id="isolationSummary"' in html and "loading-panel" in html


def test_plugin_page_contains_status_chips_and_unique_schedule_ids(client):
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "plugin-mode-row" in html
    assert "status-chip" in html
    assert 'data-plugin-subtab-target="schedule"' in html
    assert 'id="scheduleForm"' in html
    assert 'id="scheduleInterval"' in html
    assert 'id="scheduleUnit"' in html
    assert 'id="scheduleTime"' in html


def test_main_css_contains_new_ia_polish_classes(client):
    css = _read_all_css()

    assert ".section-nav" in css
    assert ".status-chip" in css
    assert ".loading-panel" in css
    assert ".section-focus" in css


def test_settings_logs_toggle_shares_action_bar_and_mobile_stays_in_flow(client):
    """The live-logs action should share the settings footer and avoid
    reintroducing the old fixed mobile FAB contract."""
    css = _read_all_css()
    html = SETTINGS_HTML.read_text(encoding="utf-8")

    assert ".settings-logs-toggle" in css
    assert ".page-shell-settings .settings-logs-toggle" not in css
    assert "@media (max-height: 860px) and (min-width: 769px)" in css
    assert 'id="settings-form-status"' in html
    assert 'id="settingsLogsToggle"' in html
    assert 'id="saveSettingsBtn"' in html
    assert html.index('id="settings-form-status"') < html.index(
        'id="settingsLogsToggle"'
    ) < html.index('id="saveSettingsBtn"')
