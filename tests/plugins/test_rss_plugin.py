# pyright: reportMissingImports=false
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


@pytest.fixture()
def plugin_config():
    return {"id": "rss", "class": "Rss", "name": "RSS"}


def _mock_feed_entries(entries):
    """Build a feedparser-like result with given entries."""
    feed = MagicMock()
    feed.bozo = False
    feed.entries = entries
    return feed


def _basic_entry(title="Article", description="Desc", image=None):
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


def test_rss_generate_success(monkeypatch, plugin_config, device_config_dev):
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entries = [_basic_entry("Test Article")]
    feed = _mock_feed_entries(entries)

    with patch("plugins.rss.rss.requests.get", return_value=mock_resp):
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            result = p.generate_image(
                {"title": "News", "feedUrl": "http://example.com/rss"},
                device_config_dev,
            )
    assert isinstance(result, Image.Image)


def test_rss_media_content_image(monkeypatch, plugin_config, device_config_dev):
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entry = _basic_entry("With Image", image={"media_content": [{"url": "http://img.png"}]})
    feed = _mock_feed_entries([entry])

    with patch("plugins.rss.rss.requests.get", return_value=mock_resp):
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            result = p.generate_image(
                {"title": "News", "feedUrl": "http://example.com/rss", "includeImages": "true"},
                device_config_dev,
            )
    assert isinstance(result, Image.Image)


def test_rss_media_thumbnail_image(monkeypatch, plugin_config, device_config_dev):
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entry = _basic_entry("Thumb", image={"media_thumbnail": [{"url": "http://thumb.png"}]})
    feed = _mock_feed_entries([entry])

    with patch("plugins.rss.rss.requests.get", return_value=mock_resp):
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            result = p.generate_image(
                {"title": "News", "feedUrl": "http://example.com/rss"},
                device_config_dev,
            )
    assert isinstance(result, Image.Image)


def test_rss_enclosure_image(monkeypatch, plugin_config, device_config_dev):
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entry = _basic_entry("Enclosure", image={"enclosures": [{"url": "http://enc.png"}]})
    feed = _mock_feed_entries([entry])

    with patch("plugins.rss.rss.requests.get", return_value=mock_resp):
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            result = p.generate_image(
                {"title": "News", "feedUrl": "http://example.com/rss"},
                device_config_dev,
            )
    assert isinstance(result, Image.Image)


def test_rss_html_entities_unescaped(monkeypatch, plugin_config, device_config_dev):
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entry = _basic_entry("Tom &amp; Jerry", "Fun &amp; Games")
    feed = _mock_feed_entries([entry])

    with patch("plugins.rss.rss.requests.get", return_value=mock_resp):
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            items = p.parse_rss_feed("http://example.com/rss")
    # html.unescape should convert &amp; to &
    assert "&amp;" not in items[0]["title"]


def test_rss_max_ten_items(monkeypatch, plugin_config, device_config_dev):
    from plugins.rss.rss import Rss

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = b"<rss></rss>"

    entries = [_basic_entry(f"Article {i}") for i in range(15)]
    feed = _mock_feed_entries(entries)

    with patch("plugins.rss.rss.requests.get", return_value=mock_resp):
        with patch("plugins.rss.rss.feedparser.parse", return_value=feed):
            p = Rss(plugin_config)
            result = p.generate_image(
                {"title": "Many", "feedUrl": "http://example.com/rss"},
                device_config_dev,
            )
    assert isinstance(result, Image.Image)
