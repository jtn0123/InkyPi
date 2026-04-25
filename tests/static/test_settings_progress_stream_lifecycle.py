"""Regression guards for Settings progress SSE lifecycle."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PAGE_JS = ROOT / "src" / "static" / "scripts" / "settings_page.js"
DIAGNOSTICS_JS = ROOT / "src" / "static" / "scripts" / "settings" / "diagnostics.js"
NAVIGATION_JS = ROOT / "src" / "static" / "scripts" / "settings" / "navigation.js"


def test_progress_sse_is_lazy_and_closed_off_maintenance_tab():
    """Settings should not keep a progress stream open for unrelated tabs."""
    settings_js = SETTINGS_PAGE_JS.read_text(encoding="utf-8")
    diagnostics_js = DIAGNOSTICS_JS.read_text(encoding="utf-8")
    navigation_js = NAVIGATION_JS.read_text(encoding="utf-8")

    assert 'tab === "maintenance"' in settings_js
    assert "diagnosticsModule.initProgressSSE()" in settings_js
    assert "diagnosticsModule.stopProgressSSE()" in settings_js
    assert 'document.addEventListener("settingsTabChanged"' in settings_js
    assert 'globalThis.addEventListener("pagehide", teardown)' in settings_js
    assert 'globalThis.addEventListener("pageshow"' in settings_js
    assert "syncProgressStreamForTab(state.activeTab)" in settings_js
    assert 'new CustomEvent("settingsTabChanged"' in navigation_js
    assert "if (!globalThis.EventSource || progressES) return;" in diagnostics_js
    assert "progressES?.readyState === globalThis.EventSource.CLOSED" in diagnostics_js
    assert "function stopProgressSSE()" in diagnostics_js
