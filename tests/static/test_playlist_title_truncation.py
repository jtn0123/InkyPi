"""Regression guard: playlist card heading must truncate long names.

Background: a 64-char playlist name (the maxlength of the input) rendered
without `text-overflow: ellipsis` on the playlist-page card heading,
overflowing the card on mobile. The Dashboard's Quick-switch panel already
truncated the same value, so behavior was inconsistent. The fix puts
ellipsis-truncation on `.playlist-title` itself, which is the only place
that uses the long playlist name as a heading.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAYLISTS_CSS = ROOT / "src" / "static" / "styles" / "partials" / "_playlists.css"
MAIN_CSS = ROOT / "src" / "static" / "styles" / "main.css"

CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def _block_for_selector(css: str, selector: str) -> str:
    """Return the body of the *first* CSS rule whose selector list contains
    `selector` exactly (no `:hover`, no descendant combinator)."""
    cleaned = CSS_COMMENT_RE.sub("", css)
    normalized = " ".join(selector.split())
    for match in re.finditer(
        r"(?P<sels>[^{}]+)\{(?P<body>[^}]*)\}",
        cleaned,
        re.S,
    ):
        sels = [
            " ".join(s.split())
            for s in match.group("sels").split(",")
            if s.strip()
        ]
        if normalized in sels:
            return match.group("body")
    raise AssertionError(f"selector {selector!r} not found in CSS")


def test_playlist_title_truncates_with_ellipsis_in_partial():
    """Source-of-truth: the partial that the build pulls in must declare
    truncation on `.playlist-title`."""
    block = _block_for_selector(PLAYLISTS_CSS.read_text(encoding="utf-8"), ".playlist-title")
    assert "overflow: hidden" in block
    assert "text-overflow: ellipsis" in block
    assert "white-space: nowrap" in block
    assert "min-width: 0" in block, (
        "min-width: 0 is required so the heading can shrink below its "
        "intrinsic content width inside flex/grid parents"
    )


def test_playlist_title_truncation_made_it_into_main_css_bundle():
    """Build sanity: scripts/build_css.py must have inlined the truncation
    rule into the bundled main.css. Catches a forgotten rebuild."""
    block = _block_for_selector(MAIN_CSS.read_text(encoding="utf-8"), ".playlist-title")
    assert "text-overflow: ellipsis" in block
    assert "white-space: nowrap" in block
