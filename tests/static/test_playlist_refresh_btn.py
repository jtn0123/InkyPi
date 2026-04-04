"""Tests that the Edit Refresh Settings button is properly wired up."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLAYLIST_JS = ROOT / "src" / "static" / "scripts" / "playlist.js"
PLAYLIST_HTML = ROOT / "src" / "templates" / "playlist.html"


class TestRefreshSettingsBtnListener:
    """Verify playlist.js registers a click listener for .refresh-settings-btn."""

    def test_js_has_refresh_settings_btn_listener(self):
        js_text = PLAYLIST_JS.read_text()
        assert (
            ".refresh-settings-btn" in js_text
        ), "playlist.js must bind a click listener on .refresh-settings-btn"

    def test_js_calls_open_refresh_modal(self):
        js_text = PLAYLIST_JS.read_text()
        # The listener block should call openRefreshModal
        assert (
            "openRefreshModal" in js_text
        ), "playlist.js must call openRefreshModal from the refresh-settings-btn listener"

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
