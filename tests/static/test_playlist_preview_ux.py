"""Tests for playlist modal defaults and preview helper text (JTN-188, JTN-189)."""

from pathlib import Path


def test_playlist_modal_no_all_day_default():
    """openCreateModal should not default to 00:00-24:00 (overlaps Default)."""
    js = Path("src/static/scripts/playlist.js").read_text()
    # Find the openCreateModal function and verify it doesn't use 00:00/24:00
    # The defaults should be something like 09:00-17:00
    assert (
        '"00:00"' not in js or "openCreateModal" not in js.split('"00:00"')[0][-200:]
    ), "openCreateModal should not default start_time to 00:00"


def test_preview_helper_text_is_conditional():
    """plugin.html helper text must be context-aware (draft vs instance)."""
    html = Path("src/templates/plugin.html").read_text()
    # The helper text should be wrapped in {% if plugin_instance %}
    assert "{% if plugin_instance %}" in html
    assert "Update Instance" in html
    assert "Add to Playlist" in html
