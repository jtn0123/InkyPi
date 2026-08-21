# pyright: reportMissingImports=false
"""JTN-380: RSS plugin feed URL validation.

The feed URL field must reject non-URL values at save time (backend
``validate_settings``) and the rendered settings template must use a
``type="url"`` input so the browser enforces basic URL constraints client-side.
"""

import re
from typing import Any

from flask.testing import FlaskClient


def _plugin() -> Any:
    from plugins.rss.rss import Rss

    return Rss({"id": "rss"})


def test_validate_settings_accepts_http_feed_url() -> None:
    assert (
        _plugin().validate_settings({"feedUrl": "http://example.com/feed.xml"}) is None
    )


def test_validate_settings_accepts_https_feed_url() -> None:
    assert (
        _plugin().validate_settings({"feedUrl": "https://news.ycombinator.com/rss"})
        is None
    )


def test_validate_settings_accepts_url_without_extension() -> None:
    # Many feeds are exposed at a bare path without a file extension.
    assert _plugin().validate_settings({"feedUrl": "https://example.com/feed"}) is None


def test_validate_settings_accepts_url_with_query_string() -> None:
    assert (
        _plugin().validate_settings(
            {"feedUrl": "https://example.com/rss?category=news"}
        )
        is None
    )


def test_validate_settings_rejects_non_url_string() -> None:
    error = _plugin().validate_settings({"feedUrl": "definitely-not-a-feed-url"})
    assert error is not None
    assert "not valid" in error.lower()
    assert "definitely-not-a-feed-url" in error


def test_validate_settings_rejects_bare_word() -> None:
    error = _plugin().validate_settings({"feedUrl": "news"})
    assert error is not None
    assert "not valid" in error.lower()


def test_validate_settings_rejects_javascript_scheme() -> None:
    error = _plugin().validate_settings({"feedUrl": "javascript:alert(1)"})
    assert error is not None
    assert "not valid" in error.lower()


def test_validate_settings_rejects_file_scheme() -> None:
    error = _plugin().validate_settings({"feedUrl": "file:///etc/passwd"})
    assert error is not None
    assert "not valid" in error.lower()


def test_validate_settings_rejects_ftp_scheme() -> None:
    error = _plugin().validate_settings({"feedUrl": "ftp://example.com/feed.xml"})
    assert error is not None
    assert "not valid" in error.lower()


def test_validate_settings_rejects_webcal_scheme() -> None:
    # RSS does not use webcal:// like the Calendar plugin does.
    error = _plugin().validate_settings({"feedUrl": "webcal://example.com/feed.xml"})
    assert error is not None
    assert "not valid" in error.lower()


def test_validate_settings_rejects_empty_url() -> None:
    error = _plugin().validate_settings({"feedUrl": ""})
    assert error is not None
    assert "required" in error.lower()


def test_validate_settings_rejects_whitespace_url() -> None:
    error = _plugin().validate_settings({"feedUrl": "   "})
    assert error is not None
    assert "required" in error.lower()


def test_validate_settings_rejects_missing_feed_url_key() -> None:
    error = _plugin().validate_settings({})
    assert error is not None
    assert "required" in error.lower()


def test_validate_settings_rejects_none_feed_url() -> None:
    error = _plugin().validate_settings({"feedUrl": None})
    assert error is not None
    assert "required" in error.lower()


def test_validate_settings_rejects_url_missing_netloc() -> None:
    # ``http://`` parses with empty netloc; must be rejected.
    error = _plugin().validate_settings({"feedUrl": "http://"})
    assert error is not None
    assert "not valid" in error.lower()


def test_rss_feed_url_input_is_type_url_and_required(client: FlaskClient) -> None:
    """The RSS settings form renders a type=url input with required/pattern (JTN-380)."""
    resp = client.get("/plugin/rss")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="feedUrl"' in html
    input_tag = re.search(r'<input[^>]*name="feedUrl"[^>]*>', html)
    assert input_tag is not None, "feedUrl input not found in rendered page"
    tag = input_tag.group(0)
    assert 'type="url"' in tag
    assert "required" in tag
    assert 'pattern="https?://.+"' in tag
