# pyright: reportMissingImports=false
import pytest
from unittest.mock import MagicMock, patch

from plugins.comic.comic_parser import (
    COMICS,
    _img_alt,
    _img_src,
    _split_safe,
    get_panel,
)


def test_img_src_basic():
    html = '<img src="https://example.com/comic.png" alt="test">'
    assert _img_src(html) == "https://example.com/comic.png"


def test_img_src_no_match():
    assert _img_src("<div>no image here</div>") == ""


def test_img_alt_basic():
    html = '<img src="https://example.com/comic.png" alt="A witty caption">'
    assert _img_alt(html) == "A witty caption"


def test_split_safe_normal():
    assert _split_safe("Part A - Part B", " - ", 1) == "Part B"


def test_split_safe_out_of_bounds():
    # Index 5 is way out of range — should return the full stripped text
    result = _split_safe("only one part", " - ", 5)
    assert result == "only one part"


def _make_mock_feed(description, title):
    """Build a minimal feedparser-like feed object."""
    entry = MagicMock()
    entry.description = description
    entry.title = title
    feed = MagicMock()
    feed.entries = [entry]
    return feed


def test_get_panel_xkcd():
    description = '<img src="https://imgs.xkcd.com/comics/test.png" alt="Alt text here" />'
    mock_feed = _make_mock_feed(description, "XKCD Title")

    with patch("plugins.comic.comic_parser.feedparser") as mock_feedparser:
        mock_feedparser.parse.return_value = mock_feed
        result = get_panel("XKCD")

    assert "image_url" in result
    assert "title" in result
    assert "caption" in result
    assert result["image_url"] == "https://imgs.xkcd.com/comics/test.png"
    assert result["title"] == "XKCD Title"
    assert result["caption"] == "Alt text here"


def test_get_panel_empty_feed():
    empty_feed = MagicMock()
    empty_feed.entries = []

    with patch("plugins.comic.comic_parser.feedparser") as mock_feedparser:
        mock_feedparser.parse.return_value = empty_feed
        with pytest.raises(RuntimeError, match="Failed to retrieve latest comic"):
            get_panel("XKCD")


def test_comics_dict_all_have_required_keys():
    required_keys = {"feed", "element", "url", "title", "caption"}
    for name, config in COMICS.items():
        missing = required_keys - set(config.keys())
        assert not missing, f"Comic '{name}' is missing keys: {missing}"
