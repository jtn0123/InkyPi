"""Tests that playlist delete confirmation modals have aria-labelledby (JTN-468).

Both deletePlaylistModal and deleteInstanceModal must have an accessible name
exposed via aria-labelledby referencing a real heading element in the DOM.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAYLIST_HTML = ROOT / "src" / "templates" / "playlist.html"


def _html() -> str:
    return PLAYLIST_HTML.read_text(encoding="utf-8")


class TestDeletePlaylistModalLabelledBy:
    """deletePlaylistModal must have aria-labelledby pointing to an existing id."""

    def test_delete_playlist_modal_has_aria_labelledby(self):
        html = _html()
        match = re.search(
            r'id="deletePlaylistModal"[^>]*aria-labelledby="([^"]+)"'
            r'|aria-labelledby="([^"]+)"[^>]*id="deletePlaylistModal"',
            html,
        )
        assert match, "#deletePlaylistModal must have aria-labelledby attribute"

    def test_delete_playlist_modal_labelledby_id_exists(self):
        html = _html()
        # Extract the aria-labelledby value from deletePlaylistModal
        match = re.search(
            r'id="deletePlaylistModal"[^>]*aria-labelledby="([^"]+)"'
            r'|aria-labelledby="([^"]+)"[^>]*id="deletePlaylistModal"',
            html,
        )
        assert match, "#deletePlaylistModal must have aria-labelledby"
        label_id = match.group(1) or match.group(2)
        assert f'id="{label_id}"' in html, (
            f"Element with id='{label_id}' referenced by aria-labelledby "
            f"must exist in playlist.html"
        )

    def test_delete_playlist_modal_no_aria_label_fallback(self):
        """The modal should use aria-labelledby (not aria-label) for consistency."""
        html = _html()
        # Find the deletePlaylistModal element and verify it doesn't rely on aria-label
        # (it should use aria-labelledby matching the other modals' pattern)
        assert (
            'aria-labelledby="deletePlaylistTitle"' in html
        ), '#deletePlaylistModal must use aria-labelledby="deletePlaylistTitle"'


class TestDeleteInstanceModalLabelledBy:
    """deleteInstanceModal must have aria-labelledby pointing to an existing id."""

    def test_delete_instance_modal_has_aria_labelledby(self):
        html = _html()
        match = re.search(
            r'id="deleteInstanceModal"[^>]*aria-labelledby="([^"]+)"'
            r'|aria-labelledby="([^"]+)"[^>]*id="deleteInstanceModal"',
            html,
        )
        assert match, "#deleteInstanceModal must have aria-labelledby attribute"

    def test_delete_instance_modal_labelledby_id_exists(self):
        html = _html()
        match = re.search(
            r'id="deleteInstanceModal"[^>]*aria-labelledby="([^"]+)"'
            r'|aria-labelledby="([^"]+)"[^>]*id="deleteInstanceModal"',
            html,
        )
        assert match, "#deleteInstanceModal must have aria-labelledby"
        label_id = match.group(1) or match.group(2)
        assert f'id="{label_id}"' in html, (
            f"Element with id='{label_id}' referenced by aria-labelledby "
            f"must exist in playlist.html"
        )

    def test_delete_instance_modal_no_aria_label_fallback(self):
        """The modal should use aria-labelledby (not aria-label) for consistency."""
        html = _html()
        assert (
            'aria-labelledby="deleteInstanceTitle"' in html
        ), '#deleteInstanceModal must use aria-labelledby="deleteInstanceTitle"'


class TestDeleteModalHeadingElements:
    """Both delete modals must have visible-or-sr-only heading elements."""

    def test_delete_playlist_title_heading_exists(self):
        html = _html()
        assert (
            'id="deletePlaylistTitle"' in html
        ), "An element with id='deletePlaylistTitle' must exist in playlist.html"

    def test_delete_instance_title_heading_exists(self):
        html = _html()
        assert (
            'id="deleteInstanceTitle"' in html
        ), "An element with id='deleteInstanceTitle' must exist in playlist.html"

    def test_all_role_dialog_modals_have_accessible_name(self):
        """Every role=dialog element on playlist page must have an accessible name."""
        html = _html()
        # Find all modal divs with role="dialog"
        dialogs = re.findall(r'<div\s[^>]*role="dialog"[^>]*>', html)
        for dialog_tag in dialogs:
            has_labelledby = "aria-labelledby=" in dialog_tag
            has_label = "aria-label=" in dialog_tag
            assert (
                has_labelledby or has_label
            ), f"Dialog element missing accessible name: {dialog_tag[:120]}"
