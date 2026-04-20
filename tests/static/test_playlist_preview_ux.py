"""Tests for playlist modal defaults and preview helper text (JTN-188, JTN-189)."""

import re
from pathlib import Path


def test_playlist_modal_defaults_to_non_overlapping_range():
    """openCreateModal should default to 09:00-17:00, not 00:00-24:00."""
    js = Path("src/static/scripts/playlist/modals.js").read_text()
    # Find openCreateModal function body
    match = re.search(
        r"function\s+openCreateModal\s*\([^)]*\)\s*\{(.*?)\n\s*\}", js, re.DOTALL
    )
    assert match, "openCreateModal function not found"
    body = match.group(1)
    assert '"09:00"' in body, "start_time should default to 09:00"
    assert '"17:00"' in body, "end_time should default to 17:00"
    assert '"00:00"' not in body, "start_time should not default to 00:00"
    assert '"24:00"' not in body, "end_time should not default to 24:00"


def test_preview_helper_text_is_conditional():
    """The workflow-help region must be context-aware (draft vs instance)."""
    html = Path("src/templates/plugin.html").read_text()
    # Find the workflow-help section specifically
    match = re.search(
        r'class="form-help workflow-help">(.*?)</div>\s*</div>', html, re.DOTALL
    )
    assert match, "workflow-help section not found"
    help_section = match.group(1)
    assert (
        "{% if plugin_instance %}" in help_section
    ), "workflow-help must use conditional rendering for plugin_instance"
    assert "Update Instance" in help_section
    assert "Add to Playlist" in help_section
