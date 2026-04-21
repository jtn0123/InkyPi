# pyright: reportMissingImports=false
"""Error scenario tests for the RSS plugin."""

from unittest.mock import MagicMock, patch

import pytest
import requests


def _make_rss_plugin():
    from plugins.rss.rss import Rss

    return Rss({"id": "rss"})


def _make_device_config():
    cfg = MagicMock()
    cfg.get_resolution.return_value = (800, 480)
    cfg.get_config.side_effect = lambda key, default=None: {
        "orientation": "horizontal",
        "timezone": "UTC",
    }.get(key, default)
    return cfg


def _base_settings(feed_url="http://example.com/feed.xml"):
    return {
        "title": "Test Feed",
        "feedUrl": feed_url,
        "includeImages": "false",
        "fontSize": "normal",
    }


def test_rss_malformed_xml():
    """feedparser gets garbage XML -> RuntimeError."""
    p = _make_rss_plugin()

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"<not valid xml at all><><><"
        resp.raise_for_status = MagicMock()
        mock_session_fn.return_value.get.return_value = resp

        # feedparser with bozo and no entries should raise
        with patch("plugins.rss.rss.feedparser.parse") as mock_parse:
            mock_result = MagicMock()
            mock_result.bozo = True
            mock_result.entries = []
            mock_result.bozo_exception = Exception("not well-formed")
            mock_parse.return_value = mock_result

            with pytest.raises(RuntimeError, match="Failed to parse RSS feed"):
                p.parse_rss_feed("http://example.com/feed.xml")


def test_rss_empty_feed():
    """Valid XML with zero entries returns empty list gracefully."""
    p = _make_rss_plugin()

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"<rss><channel></channel></rss>"
        resp.raise_for_status = MagicMock()
        mock_session_fn.return_value.get.return_value = resp

        with patch("plugins.rss.rss.feedparser.parse") as mock_parse:
            mock_result = MagicMock()
            mock_result.bozo = False
            mock_result.entries = []
            mock_parse.return_value = mock_result

            items = p.parse_rss_feed("http://example.com/feed.xml")
            assert items == []


def test_rss_network_timeout():
    """requests.get raises Timeout."""
    p = _make_rss_plugin()

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.side_effect = requests.exceptions.Timeout(
            "timed out"
        )
        with pytest.raises(requests.exceptions.Timeout):
            p.parse_rss_feed("http://example.com/feed.xml")


def test_rss_http_500():
    """Server returns 500 -> raise_for_status raises."""
    p = _make_rss_plugin()

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        resp = MagicMock()
        resp.status_code = 500
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "500 Server Error"
        )
        mock_session_fn.return_value.get.return_value = resp

        with pytest.raises(requests.exceptions.HTTPError):
            p.parse_rss_feed("http://example.com/feed.xml")


def test_rss_missing_feed_url_falls_back_to_default():
    """JTN-784: missing feedUrl at render time falls back to the BBC World News
    default so a bare /update_now renders. validate_settings still rejects an
    empty feedUrl on save — see tests/plugins/test_rss.py for that contract."""
    p = _make_rss_plugin()
    cfg = _make_device_config()

    with patch.object(p, "parse_rss_feed", return_value=[]) as m_parse:
        p.generate_image({"title": "Test"}, cfg)
    args, _kwargs = m_parse.call_args
    assert args[0] == "https://feeds.bbci.co.uk/news/rss.xml"


def test_rss_connection_error():
    """requests.get raises ConnectionError."""
    p = _make_rss_plugin()

    with patch("plugins.rss.rss.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.side_effect = (
            requests.exceptions.ConnectionError("refused")
        )
        with pytest.raises(requests.exceptions.ConnectionError):
            p.parse_rss_feed("http://example.com/feed.xml")
