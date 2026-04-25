"""Focused guards for the playlist frontend module split."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAYLIST_BOOTSTRAP_JS = ROOT / "src" / "static" / "scripts" / "playlist.js"
PLAYLIST_PAGE_JS = ROOT / "src" / "static" / "scripts" / "playlist" / "page.js"
PLAYLIST_HTML = ROOT / "src" / "templates" / "playlist.html"


def test_playlist_template_loads_split_scripts_in_order():
    html = PLAYLIST_HTML.read_text()
    scripts = [
        "scripts/playlist/shared.js",
        "scripts/playlist/cards.js",
        "scripts/playlist/modals.js",
        "scripts/playlist/progress.js",
        "scripts/playlist/actions.js",
        "scripts/playlist/form.js",
        "scripts/playlist/page.js",
        "scripts/playlist.js",
    ]
    positions = [html.find(script) for script in scripts]
    assert all(
        pos != -1 for pos in positions
    ), "playlist.html must load all split playlist scripts"
    assert positions == sorted(
        positions
    ), "playlist module scripts must load before the bootstrap"


def test_playlist_bootstrap_stays_thin_and_boot_oriented():
    js = PLAYLIST_BOOTSTRAP_JS.read_text()
    assert "InkyPiPlaylistPage" in js
    assert "createPlaylistPage" in js
    assert "bootstrap" in js

    for moved_symbol in (
        "function validatePlaylistName",
        "function displayPluginInstance",
        "function handleDrop",
        "function syncModalOpenState",
        "function openCreateModal",
    ):
        assert (
            moved_symbol not in js
        ), f"{moved_symbol} should live in a playlist module, not playlist.js"


def test_playlist_page_drops_dead_next_in_timer():
    js = PLAYLIST_PAGE_JS.read_text()
    assert "renderNextIn" not in js


def test_playlist_name_input_matches_client_validation_limits():
    html = PLAYLIST_HTML.read_text(encoding="utf-8")
    assert 'id="playlist_name"' in html
    assert 'maxlength="64"' in html
    assert 'pattern="[A-Za-z0-9 _-]+"' in html

    form_js = (ROOT / "src" / "static" / "scripts" / "playlist" / "form.js").read_text(
        encoding="utf-8"
    )
    assert 'event.inputType !== "insertFromPaste"' in form_js
    assert "Name must be 64 characters or fewer" in form_js
