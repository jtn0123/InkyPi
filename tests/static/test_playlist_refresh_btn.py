"""Tests that the Edit Refresh Settings button is properly wired up."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLAYLIST_JS = ROOT / "src" / "static" / "scripts" / "playlist.js"
PLAYLIST_HTML = ROOT / "src" / "templates" / "playlist.html"


class TestRefreshSettingsBtnListener:
    """Verify playlist.js delegates refresh-settings actions from playlist cards."""

    def test_js_delegates_playlist_actions(self):
        js_text = PLAYLIST_JS.read_text()
        assert (
            "[data-playlist-action]" in js_text
        ), "playlist.js must delegate playlist card clicks via data-playlist-action"
        assert (
            "dataset.playlistAction" in js_text
        ), "playlist.js must read dataset.playlistAction from the delegated target"

    def test_js_handles_refresh_action(self):
        js_text = PLAYLIST_JS.read_text()
        assert (
            "action === 'edit-refresh'" in js_text
            or 'action === "edit-refresh"' in js_text
        ), "delegated handler must branch on the edit-refresh action"
        assert (
            "openRefreshModal" in js_text
        ), "playlist.js must call openRefreshModal from the delegated refresh action"

    def test_js_parses_data_refresh_attribute(self):
        js_text = PLAYLIST_JS.read_text()
        assert (
            "data-refresh" in js_text
        ), "playlist.js must read the data-refresh attribute"


class TestRefreshSettingsBtnTemplate:
    """Verify playlist.html has the button with required data attributes."""

    def test_html_has_refresh_settings_btn(self):
        html_text = PLAYLIST_HTML.read_text()
        assert (
            "refresh-settings-btn" in html_text
        ), "playlist.html must contain a .refresh-settings-btn element"

    def test_html_btn_has_required_data_attributes(self):
        html_text = PLAYLIST_HTML.read_text()
        btn_pattern = re.search(
            r'<button[^>]*class="[^"]*refresh-settings-btn[^"]*"[^>]*>',
            html_text,
            re.DOTALL,
        )
        assert (
            btn_pattern
        ), "playlist.html must contain a button with refresh-settings-btn class"
        btn_match = btn_pattern.group(0)
        for attr in (
            'data-playlist-action="edit-refresh"',
            "data-playlist",
            "data-plugin-id",
            "data-instance",
            "data-refresh",
        ):
            assert attr in btn_match, f"refresh-settings-btn must have {attr} attribute"

    def test_html_has_refresh_modal(self):
        html_text = PLAYLIST_HTML.read_text()
        assert (
            "refreshSettingsModal" in html_text
        ), "playlist.html must contain the refreshSettingsModal markup"
