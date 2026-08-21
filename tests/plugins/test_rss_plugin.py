from typing import Any

# pyright: reportMissingImports=false
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


@pytest.fixture()
def plugin_config() -> Any:
    return {"id": "rss", "class": "Rss", "name": "RSS"}


def _mock_feed_entries(entries: Any) -> Any:
    """Build a feedparser-like result with given entries."""
    feed = MagicMock()
    feed.bozo = False
    feed.entries = entries
    return feed


def _basic_entry(
    title: Any = "Article", description: Any = "Desc", image: Any = None
) -> Any:
    entry = MagicMock()
    entry.get = lambda k, d="": {
        "title": title,
        "description": description,
        "published": "Mon, 01 Jan 2025 00:00:00 GMT",
        "link": "http://example.com/article",
    }.get(k, d)
    # Remove optional media attributes by default
    entry_dict = {}
    if image:
        entry_dict = image
    # Use __contains__ and attribute access for the various image fields
    type(entry).__contains__ = lambda self, k: k in entry_dict
    for k, v in entry_dict.items():
        setattr(entry, k, v)
    return entry


def test_rss_generate_success(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> None:
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entries = [_basic_entry("Test Article")]
    feed = _mock_feed_entries(entries)

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.return_value = mock_resp
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            result = p.generate_image(
                {"title": "News", "feedUrl": "http://example.com/rss"},
                device_config_dev,
            )
    assert isinstance(result, Image.Image)


def test_rss_media_content_image(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> None:
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entry = _basic_entry(
        "With Image", image={"media_content": [{"url": "http://img.png"}]}
    )
    feed = _mock_feed_entries([entry])

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.return_value = mock_resp
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            result = p.generate_image(
                {
                    "title": "News",
                    "feedUrl": "http://example.com/rss",
                    "includeImages": "true",
                },
                device_config_dev,
            )
    assert isinstance(result, Image.Image)


def test_rss_media_thumbnail_image(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> None:
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entry = _basic_entry(
        "Thumb", image={"media_thumbnail": [{"url": "http://thumb.png"}]}
    )
    feed = _mock_feed_entries([entry])

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.return_value = mock_resp
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            result = p.generate_image(
                {"title": "News", "feedUrl": "http://example.com/rss"},
                device_config_dev,
            )
    assert isinstance(result, Image.Image)


def test_rss_enclosure_image(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> None:
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entry = _basic_entry("Enclosure", image={"enclosures": [{"url": "http://enc.png"}]})
    feed = _mock_feed_entries([entry])

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.return_value = mock_resp
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            result = p.generate_image(
                {"title": "News", "feedUrl": "http://example.com/rss"},
                device_config_dev,
            )
    assert isinstance(result, Image.Image)


def test_rss_html_entities_unescaped(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> None:
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entry = _basic_entry("Tom &amp; Jerry", "Fun &amp; Games")
    feed = _mock_feed_entries([entry])

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.return_value = mock_resp
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            items = p.parse_rss_feed("http://example.com/rss")
    # html.unescape should convert &amp; to &
    assert "&amp;" not in items[0]["title"]


def test_rss_html_tags_stripped(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> None:
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entry = _basic_entry(
        '<b>Bold</b> <script>alert("xss")</script>',
        "<p>Paragraph</p><img src=x onerror=alert(1)>",
    )
    feed = _mock_feed_entries([entry])

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.return_value = mock_resp
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            items = p.parse_rss_feed("http://example.com/rss")
    assert "<" not in items[0]["title"]
    assert "<" not in items[0]["description"]
    assert "Bold" in items[0]["title"]
    assert "alert" in items[0]["title"]  # text content kept, tags stripped
    assert "Paragraph" in items[0]["description"]


def test_rss_sanitize_text_static() -> None:
    from plugins.rss.rss import Rss

    assert Rss._sanitize_text("") == ""
    assert Rss._sanitize_text("plain text") == "plain text"
    assert Rss._sanitize_text("&amp; &lt;") == "& <"
    assert Rss._sanitize_text("<b>bold</b>") == "bold"
    assert Rss._sanitize_text('<a href="x">link</a> text') == "link text"


def test_rss_max_ten_items(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> None:
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entries = [_basic_entry(f"Article {i}") for i in range(15)]
    feed = _mock_feed_entries(entries)

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.return_value = mock_resp
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            result = p.generate_image(
                {"title": "Many", "feedUrl": "http://example.com/rss"},
                device_config_dev,
            )
    assert isinstance(result, Image.Image)


def test_rss_sanitize_nested_tags() -> None:
    """Nested HTML tags should be fully stripped."""
    from plugins.rss.rss import Rss

    assert Rss._sanitize_text("<p><b>bold</b></p>") == "bold"
    assert Rss._sanitize_text("<div><span>inner</span></div>") == "inner"


def test_rss_sanitize_entities() -> None:
    """HTML entities should be unescaped."""
    from plugins.rss.rss import Rss

    assert Rss._sanitize_text("&amp;") == "&"
    assert Rss._sanitize_text("&lt;tag&gt;") == "<tag>"
    assert Rss._sanitize_text("&#39;quoted&#39;") == "'quoted'"


def test_rss_generate_with_realistic_feed(
    monkeypatch: pytest.MonkeyPatch,
    plugin_config: Any,
    device_config_dev: Any,
    realistic_rss_feed: Any,
) -> None:
    """Test RSS plugin with a realistic feed fixture."""
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.return_value = mock_resp
        with patch("plugins.rss.rss.feedparser.parse", return_value=realistic_rss_feed):
            p = Rss(plugin_config)
            result = p.generate_image(
                {"title": "Realistic News", "feedUrl": "http://example.com/rss"},
                device_config_dev,
            )
    assert isinstance(result, Image.Image)
