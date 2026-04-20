"""Tests that the playlist page blocks background interaction while a modal is open.

JTN-228: The Refresh Settings dialog (and other playlist modals) must make the
underlying page inert — preventing mouse clicks, keyboard focus, and touch events
on background controls.

These are static-analysis tests that verify the HTML and JS implement the correct
inert-attribute pattern without requiring a running browser.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLAYLIST_MODALS_JS = ROOT / "src" / "static" / "scripts" / "playlist" / "modals.js"
PLAYLIST_ACTIONS_JS = ROOT / "src" / "static" / "scripts" / "playlist" / "actions.js"
PLAYLIST_HTML = ROOT / "src" / "templates" / "playlist.html"


class TestInertAttributeManagement:
    """Verify that playlist/modals.js sets/removes inert on the page content wrapper."""

    def test_js_sets_inert_on_page_content(self):
        """syncModalOpenState must set the inert attribute when a modal opens."""
        js = PLAYLIST_MODALS_JS.read_text()
        assert (
            "setAttribute('inert'" in js or 'setAttribute("inert"' in js
        ), "playlist/modals.js must call setAttribute('inert', '') to block background"

    def test_js_removes_inert_on_modal_close(self):
        """syncModalOpenState must remove the inert attribute when all modals close."""
        js = PLAYLIST_MODALS_JS.read_text()
        assert (
            "removeAttribute('inert'" in js or 'removeAttribute("inert"' in js
        ), "playlist/modals.js must call removeAttribute('inert') when modals close"

    def test_js_targets_playlist_page_content(self):
        """The inert toggle must target the #playlist-page-content wrapper."""
        js = PLAYLIST_MODALS_JS.read_text()
        assert (
            "playlist-page-content" in js
        ), "playlist/modals.js must reference #playlist-page-content as the inert target"

    def test_inert_toggled_in_sync_function(self):
        """The inert toggle must live inside the syncModalOpenState function so it
        fires on every open/close path."""
        js = PLAYLIST_MODALS_JS.read_text()
        # Extract the syncModalOpenState function body
        match = re.search(
            r"function\s+syncModalOpenState\s*\(\s*\)\s*\{(.*?)\n\s*\}",
            js,
            re.DOTALL,
        )
        assert match, "syncModalOpenState function not found"
        body = match.group(1)
        assert (
            "playlist-page-content" in body
        ), "inert toggling must be inside syncModalOpenState"
        assert "inert" in body, "syncModalOpenState must handle the inert attribute"


class TestPageContentWrapperInTemplate:
    """Verify playlist.html has the #playlist-page-content wrapper."""

    def test_html_has_page_content_wrapper(self):
        """The template must wrap the interactive page content in a dedicated div."""
        html = PLAYLIST_HTML.read_text()
        assert (
            'id="playlist-page-content"' in html
        ), "playlist.html must contain <div id='playlist-page-content'>"

    def test_modals_are_outside_page_content_wrapper(self):
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
    """Verify that focus is moved into the modal when it opens and restored on close."""

    def test_js_moves_focus_into_modal_on_open(self):
        """setModalOpen / openRefreshModal must focus a child element when opening."""
        js = PLAYLIST_MODALS_JS.read_text()
        # Look for a focus() call inside an open path
        assert (
            "focusable.focus()" in js
        ), "playlist/modals.js must call focusable.focus() when opening a modal"

    def test_js_restores_focus_on_close(self):
        """On close, focus must return to _lastModalTrigger."""
        js = PLAYLIST_MODALS_JS.read_text()
        assert (
            "lastModalTrigger" in js
        ), "playlist/modals.js must track lastModalTrigger for focus restoration"
        assert (
            "lastModalTrigger.focus()" in js
        ), "playlist/modals.js must call lastModalTrigger.focus() when closing a modal"

    def test_refresh_btn_listener_passes_trigger(self):
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
