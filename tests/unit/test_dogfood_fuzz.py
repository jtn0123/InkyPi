"""Dogfood fuzz checks for playlist-name contract alignment (JTN-747)."""

from __future__ import annotations

from pathlib import Path

PLAYLIST_JS = Path(__file__).resolve().parents[2] / "src/static/scripts/playlist.js"
EXPECTED_COPY = (
    "Playlist name can only contain ASCII letters, "
    "numbers, spaces, underscores, and hyphens"
)


def test_non_ascii_playlist_names_match_ui_copy(client):
    """Non-ASCII playlist names should be rejected by both UI copy and server."""
    js = PLAYLIST_JS.read_text()
    assert "^[A-Za-z0-9 _-]+$" in js
    assert EXPECTED_COPY in js

    for name in ("Météo", "東京", "Cafe\u0301"):
        resp = client.post(
            "/create_playlist",
            json={"playlist_name": name, "start_time": "08:00", "end_time": "12:00"},
        )
        assert resp.status_code == 400, name
        data = resp.get_json()
        assert data["success"] is False
        assert data["details"]["field"] == "playlist_name"
        assert EXPECTED_COPY in data["error"]
