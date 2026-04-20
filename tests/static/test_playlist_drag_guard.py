"""Tests that the drag-and-drop handler prevents cross-playlist drops (JTN-235)."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLAYLIST_CARDS_JS = ROOT / "src" / "static" / "scripts" / "playlist" / "cards.js"


def _handle_drop_block() -> str:
    """Extract the handleDrop function body from playlist/cards.js.

    Finds the text between ``function handleDrop(event) {`` and the next function
    declaration (``function handleDragEnd()``) so that assertions are scoped
    to just that function and cannot produce false positives from elsewhere in
    the file.
    """
    js_text = PLAYLIST_CARDS_JS.read_text()
    start = js_text.find("function handleDrop(event) {")
    assert start != -1, "function handleDrop(event) { not found in playlist/cards.js"
    end = js_text.find("function handleDragEnd()", start)
    assert (
        end != -1
    ), "function handleDragEnd() not found after handleDrop in playlist/cards.js"
    return js_text[start:end]


class TestCrossPlaylistDragGuard:
    """Verify playlist/cards.js rejects drops whose source is in a different playlist."""

    def test_handle_drop_reads_src_playlist(self):
        block = _handle_drop_block()
        assert (
            "srcPlaylist" in block
        ), "handleDrop must derive srcPlaylist from the dragged element"

    def test_handle_drop_reads_dst_playlist(self):
        block = _handle_drop_block()
        assert (
            "dstPlaylist" in block
        ), "handleDrop must derive dstPlaylist from the drop target"

    def test_handle_drop_guards_cross_playlist(self):
        block = _handle_drop_block()
        # Guard: if srcPlaylist !== dstPlaylist, bail out
        assert re.search(
            r"srcPlaylist\s*!==\s*dstPlaylist", block
        ), "handleDrop must return early when srcPlaylist !== dstPlaylist"

    def test_guard_returns_before_dom_mutation(self):
        """The guard must appear before insertBefore so the DOM is never mutated."""
        block = _handle_drop_block()
        guard_pos = block.find("srcPlaylist !== dstPlaylist")
        insert_pos = block.find("insertBefore")
        assert guard_pos != -1, "srcPlaylist !== dstPlaylist guard not found"
        assert insert_pos != -1, "insertBefore call not found"
        assert (
            guard_pos < insert_pos
        ), "Cross-playlist guard must appear before the insertBefore DOM mutation"

    def test_guard_uses_closest_playlist_item(self):
        block = _handle_drop_block()
        assert (
            "closest('.playlist-item')" in block
            or 'closest(".playlist-item")' in block
        ), "Guard must use .closest('.playlist-item') to identify playlist boundaries"
