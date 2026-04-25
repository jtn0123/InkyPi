# pyright: reportMissingImports=false
"""Targeted tests for final UI IA and polish additions."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_STYLES_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "styles"
SETTINGS_HTML = ROOT / "src" / "templates" / "settings.html"
SIDEBAR_HTML = ROOT / "src" / "templates" / "macros" / "sidebar.html"


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
    assert "data-schedule-submit" in html
    schedule_time = re.search(r"<input[^>]*id=\"scheduleTime\"[^>]*>", html)
    assert schedule_time is not None
    schedule_time_tag = schedule_time.group(0)
    assert 'class="time-input"' in schedule_time_tag
    assert 'type="time"' in schedule_time_tag
    assert re.search(r"\bdisabled\b", schedule_time_tag)


def test_mobile_shell_has_primary_navigation_replacement():
    html = SIDEBAR_HTML.read_text(encoding="utf-8")
    css = _read_all_css()

    assert 'class="mobile-site-nav"' in html
    assert 'aria-label="Mobile site navigation"' in html
    for label in (
        "Dashboard",
        "Playlists",
        "Plugins",
        "History",
        "Settings",
        "API Keys",
    ):
        assert label in html
    assert ".mobile-site-nav" in css
    assert ".mobile-site-nav-panel" in css


def test_main_css_contains_new_ia_polish_classes(client):
    css = _read_all_css()

    assert ".section-nav" in css
    assert ".status-chip" in css
    assert ".loading-panel" in css
    assert ".section-focus" in css


def test_settings_time_format_defaults_to_24h_when_config_is_missing():
    html = SETTINGS_HTML.read_text(encoding="utf-8")

    assert (
        'selected_time_format = device_settings.time_format if device_settings.time_format in ("12h", "24h") else "24h"'
        in html
    )
    assert (
        'value="24h" {% if selected_time_format == "24h" %}checked{% endif %}' in html
    )


def test_plugin_page_updates_generated_preview_after_success(client):
    resp = client.get("/static/scripts/plugin_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    assert "function refreshPreviewsAfterSuccess()" in js
    assert "await refreshInstancePreview({ force: true })" in js
    assert "setLatestRefresh(resolvedRefresh)" in js
    assert "setCurrentDisplayRefresh(resolvedRefresh)" in js
    assert "button.disabled = !hasSnapshot" in js


def test_settings_logs_toggle_shares_action_bar_and_mobile_stays_in_flow(client):
    """The live-logs action should share the settings footer and avoid
    reintroducing the old fixed mobile FAB contract."""
    css = _read_all_css()
    html = SETTINGS_HTML.read_text(encoding="utf-8")

    assert ".settings-logs-toggle" in css
    assert ".page-shell-settings .settings-logs-toggle" not in css
    assert re.search(
        r"@media \(max-height: 860px\) and \(min-width: 769px\)\s*\{"
        r"[^}]*\.settings-panel \.buttons-container\s*\{[^}]*"
        r"position:\s*sticky;[^}]*bottom:\s*8px;",
        css,
        re.S,
    )
    assert 'id="settings-form-status"' in html
    assert 'id="settingsLogsToggle"' in html
    assert 'id="saveSettingsBtn"' in html
    assert (
        html.index('id="settings-form-status"')
        < html.index('id="settingsLogsToggle"')
        < html.index('id="saveSettingsBtn"')
    )


def test_second_validation_mobile_and_feedback_polish_contracts():
    css = _read_all_css()
    api_js = (ROOT / "src" / "static" / "scripts" / "api_keys_page.js").read_text(
        encoding="utf-8"
    )

    assert "grid-template-columns: auto minmax(84px, 1fr) auto" in css
    assert "@media (max-width: 360px)" in css
    assert ".brand-host" in css and "display: none" in css
    assert "bottom: 20px" in css and ".toast-container" in css
    assert "--modal-overlay-destructive" in css
    assert "body.success-failure-modal-open .toast-container" in css
    assert "overflow-x: clip" in css
    assert "env(safe-area-inset-bottom, 0px) + 16px" in css
    assert (
        '.pageheader-plugin .pageheader-actions [data-plugin-action="update_now"]'
        in css
    )
    assert "grid-column: 1 / -1" in css
    assert (
        ".schedule-inline-group" in css
        and "grid-template-columns: minmax(0, 1fr)" in css
    )
    assert '#playlistModal input[type="time"]' in css
    assert 'setToggleLabel(button, "Editing")' in api_js


def test_image_url_schema_has_inline_url_validation(client):
    resp = client.get("/plugin/image_url")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    plugin_form_js = (ROOT / "src" / "static" / "scripts" / "plugin_form.js").read_text(
        encoding="utf-8"
    )

    assert 'type="url"' in html
    assert 'pattern="https?://.+"' in html
    assert 'aria-describedby="url-error"' in html
    assert 'id="url-error"' in html
    assert "function surfaceFieldError(result)" in plugin_form_js
    assert "#settingsForm [name='url']" in plugin_form_js
