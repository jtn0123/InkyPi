"""Tests that the playlist page blocks background interaction while a modal is open.

JTN-228: The Refresh Settings dialog (and other playlist modals) must make the
underlying page inert — preventing mouse clicks, keyboard focus, and touch events
on background controls.

These static checks cover the template layout and the wiring;
tests/integration/test_modal_keyboard_e2e.py checks the behaviour in a browser.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLAYLIST_MODALS_JS = ROOT / "src" / "static" / "scripts" / "playlist" / "modals.js"
PLAYLIST_ACTIONS_JS = ROOT / "src" / "static" / "scripts" / "playlist" / "actions.js"
PLAYLIST_HTML = ROOT / "src" / "templates" / "playlist.html"


class TestInertAttributeManagement:
    """The shared InkyPiModalFocus helper owns the inert state.

    It marks every sibling of the open dialog (including
    #playlist-page-content) inert and restores the previous values on close.
    playlist/modals.js must not toggle inert itself: the helper records the
    value it found and puts it back, so a second owner would leave the page
    inert after the dialog closed. tests/integration/test_modal_keyboard_e2e.py
    checks the real behaviour in a browser.
    """

    def test_js_delegates_inert_to_the_shared_helper(self) -> None:
        js = PLAYLIST_MODALS_JS.read_text()
        assert "InkyPiModalFocus?.activate" in js
        assert "InkyPiModalFocus?.deactivate" in js

    def test_js_does_not_toggle_inert_itself(self) -> None:
        js = PLAYLIST_MODALS_JS.read_text()
        assert not re.search(r"(set|remove)Attribute\(\s*['\"]inert", js)
        assert ".inert =" not in js


class TestPageContentWrapperInTemplate:
    """Verify playlist.html has the #playlist-page-content wrapper."""

    def test_html_has_page_content_wrapper(self) -> None:
        """The template must wrap the interactive page content in a dedicated div."""
        html = PLAYLIST_HTML.read_text()
        assert (
            'id="playlist-page-content"' in html
        ), "playlist.html must contain <div id='playlist-page-content'>"

    def test_modals_are_outside_page_content_wrapper(self) -> None:
        """Modal elements must come after (outside) #playlist-page-content so that
        the inert attribute does not block them."""
        html = PLAYLIST_HTML.read_text()

        # The closing tag of #playlist-page-content must appear before the modals
        content_close_idx = html.find("</div><!-- /#playlist-page-content -->")
        assert (
            content_close_idx != -1
        ), "playlist.html must have a closing </div><!-- /#playlist-page-content --> comment"

        # All modal divs must start after the wrapper closes
        modal_ids = [
            "playlistModal",
            "refreshSettingsModal",
            "deletePlaylistModal",
            "deleteInstanceModal",
        ]
        for modal_id in modal_ids:
            modal_idx = html.find(f'id="{modal_id}"')
            assert modal_idx != -1, f"Modal #{modal_id} not found in playlist.html"
            assert modal_idx > content_close_idx, (
                f"Modal #{modal_id} must be outside (after) #playlist-page-content "
                f"so it is not blocked by the inert attribute"
            )


class TestFocusManagement:
    """Focus moves in on open and returns to the opener on close (via the helper)."""

    def test_refresh_btn_listener_passes_trigger(self) -> None:
        """The delegated refresh action must pass the button element as the
        trigger so focus can be restored after close."""
        js = PLAYLIST_ACTIONS_JS.read_text()
        match = re.search(
            r'action === [\'"]edit-refresh[\'"].*?openRefreshModal\((.*?)\);',
            js,
            re.DOTALL,
        )
        assert match, "delegated edit-refresh action calling openRefreshModal not found"
        call_args = match.group(1)
        assert re.search(
            r",\s*actionButton\s*$", call_args.strip()
        ), "openRefreshModal must receive the delegated trigger element as last argument"
