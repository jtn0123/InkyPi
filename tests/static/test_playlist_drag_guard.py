"""Tests that the drag-and-drop handler prevents cross-playlist drops (JTN-235)."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLAYLIST_JS = ROOT / "src" / "static" / "scripts" / "playlist.js"


class TestCrossPlaylistDragGuard:
    """Verify playlist.js rejects drops whose source is in a different playlist."""

    def test_handle_drop_reads_src_playlist(self):
        js_text = PLAYLIST_JS.read_text()
        assert (
            "srcPlaylist" in js_text
        ), "handleDrop must derive srcPlaylist from the dragged element"

    def test_handle_drop_reads_dst_playlist(self):
        js_text = PLAYLIST_JS.read_text()
        assert (
            "dstPlaylist" in js_text
        ), "handleDrop must derive dstPlaylist from the drop target"

    def test_handle_drop_guards_cross_playlist(self):
        js_text = PLAYLIST_JS.read_text()
        # Guard: if srcPlaylist !== dstPlaylist, bail out
        assert re.search(
            r"srcPlaylist\s*!==\s*dstPlaylist", js_text
        ), "handleDrop must return early when srcPlaylist !== dstPlaylist"

    def test_guard_returns_before_dom_mutation(self):
        """The guard must appear before insertBefore so the DOM is never mutated."""
        js_text = PLAYLIST_JS.read_text()
        guard_pos = js_text.find("srcPlaylist !== dstPlaylist")
        insert_pos = js_text.find("insertBefore")
        assert guard_pos != -1, "srcPlaylist !== dstPlaylist guard not found"
        assert insert_pos != -1, "insertBefore call not found"
        assert (
            guard_pos < insert_pos
        ), "Cross-playlist guard must appear before the insertBefore DOM mutation"

    def test_guard_uses_closest_playlist_item(self):
        js_text = PLAYLIST_JS.read_text()
        assert (
            "closest('.playlist-item')" in js_text
        ), "Guard must use .closest('.playlist-item') to identify playlist boundaries"
