"""Regression tests for button hierarchy and control consistency."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_HTML = ROOT / "src" / "templates" / "settings.html"
PLAYLIST_HTML = ROOT / "src" / "templates" / "playlist.html"
BUTTON_CSS = ROOT / "src" / "static" / "styles" / "partials" / "_button.css"
NAVIGATION_CSS = ROOT / "src" / "static" / "styles" / "partials" / "_navigation.css"
PLAYLISTS_CSS = ROOT / "src" / "static" / "styles" / "partials" / "_playlists.css"


def test_settings_demotes_non_primary_actions_to_secondary_styles():
    html = SETTINGS_HTML.read_text(encoding="utf-8")

    assert 'class="header-button is-secondary" href="{{ url_for(\'settings.api_keys_page\') }}"' in html
    assert 'class="settings-mobile-toggle header-button is-secondary"' in html
    assert 'id="exportConfigBtn" class="action-button compact is-secondary"' in html
    assert 'id="refreshBenchmarksBtn" class="action-button compact is-secondary"' in html
    assert 'id="unIsolatePluginBtn" class="action-button compact is-secondary"' in html
    assert 'id="refreshIsolationBtn" class="action-button compact is-secondary"' in html
    assert 'class="action-button is-secondary settings-logs-toggle"' in html


def test_playlist_card_actions_use_visible_labels_for_edit_and_delete():
    html = PLAYLIST_HTML.read_text(encoding="utf-8")

    assert '<span class="action-button-label">Edit</span>' in html
    assert '<span class="action-button-label">Delete</span>' in html
    assert "delete-playlist-btn playlist-secondary-button is-icon-only" not in html
    assert 'class="pl-add-row"' in html


def test_secondary_button_styles_share_surface_treatment_and_compact_scale():
    button_css = BUTTON_CSS.read_text(encoding="utf-8")
    nav_css = NAVIGATION_CSS.read_text(encoding="utf-8")

    assert ".action-button.compact" in button_css
    assert "min-height: 44px" in button_css
    assert "padding: 10px 16px" in button_css
    assert ".action-button.is-secondary" in button_css
    assert "background-color: var(--surface)" in button_css
    assert "border: 1px solid var(--surface-border)" in button_css
    assert ".header-button.is-secondary" in nav_css
    assert "background-color: var(--surface)" in nav_css
    assert "border: 1px solid var(--surface-border)" in nav_css


def test_playlist_add_row_reads_as_clickable_recovery_action():
    css = PLAYLISTS_CSS.read_text(encoding="utf-8")

    assert ".pl-add-row" in css
    assert "min-height: 44px" in css
    assert "font-weight: 600" in css
    assert "box-shadow: var(--shadow-xs)" in css
    assert "background: var(--surface-2)" in css
