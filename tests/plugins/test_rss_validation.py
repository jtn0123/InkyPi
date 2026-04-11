# pyright: reportMissingImports=false
"""JTN-380: URL validation for the RSS plugin's feed URL field.

Prior behavior silently accepted any non-empty string (e.g.
``definitely-not-a-feed-url``), surfacing the failure later when
``generate_image`` tried to fetch the feed. We now reject non-http(s) URLs at
save time and render the input as ``type="url"`` for client-side feedback.
"""

import pytest


def _make_plugin():
    from plugins.rss.rss import Rss

    return Rss({"id": "rss"})


# ---------- validate_settings unit tests ----------


@pytest.mark.parametrize(
    "bad_url",
    [
        "definitely-not-a-feed-url",
        "not-a-url",
        "example.com/feed",  # missing scheme
        "ftp://example.com/feed",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "://example.com",  # empty scheme
    ],
)
def test_validate_settings_rejects_non_http_urls(bad_url):
    plugin = _make_plugin()
    err = plugin.validate_settings({"feedUrl": bad_url})
    assert err is not None
    assert "http" in err.lower() or "invalid" in err.lower() or "host" in err.lower()


@pytest.mark.parametrize(
    "good_url",
    [
        "https://example.com/feed.xml",
        "http://example.com/rss",
        "https://news.ycombinator.com/rss",
        "HTTP://Example.com/feed",  # uppercase scheme still ok
    ],
)
def test_validate_settings_accepts_http_https_urls(good_url):
    plugin = _make_plugin()
    assert plugin.validate_settings({"feedUrl": good_url}) is None


def test_validate_settings_empty_feed_url_returns_none():
    """Empty/missing feedUrl is handled by the required-field validator.

    ``validate_settings`` must not double-report the same error, so it returns
    ``None`` and defers to the upstream required-field check.
    """
    plugin = _make_plugin()
    assert plugin.validate_settings({}) is None
    assert plugin.validate_settings({"feedUrl": ""}) is None
    assert plugin.validate_settings({"feedUrl": "   "}) is None


def test_validate_settings_rejects_url_without_host():
    plugin = _make_plugin()
    err = plugin.validate_settings({"feedUrl": "https://"})
    assert err is not None


# ---------- schema / template tests ----------


def test_settings_schema_feed_url_is_url_type():
    plugin = _make_plugin()
    s = plugin.build_settings_schema()
    feed_url_field = None
    for section in s["sections"]:
        for item in section["items"]:
            if item.get("kind") == "field" and item.get("name") == "feedUrl":
                feed_url_field = item
                break
    assert feed_url_field is not None, "feedUrl field missing from schema"
    assert feed_url_field.get("type") == "url"
    assert feed_url_field.get("required") is True


def test_settings_template_renders_url_input(client):
    """The rendered RSS settings page must use ``<input type="url">`` (JTN-380)."""
    resp = client.get("/plugin/rss")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # The feedUrl input should advertise type="url" so HTML5 validation kicks in.
    assert 'name="feedUrl"' in body
    assert 'type="url"' in body


# ---------- save_plugin_settings integration tests ----------


def test_save_plugin_settings_rejects_non_url_feed(client):
    """JTN-380: POST with a bare-string feed URL returns 400."""
    data = {
        "plugin_id": "rss",
        "title": "Test Feed",
        "feedUrl": "definitely-not-a-feed-url",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 400
    body = resp.get_json() or {}
    assert body.get("success") is False
    msg = body.get("error") or body.get("message") or ""
    assert "http" in msg.lower() or "invalid" in msg.lower()


def test_save_plugin_settings_rejects_javascript_scheme(client):
    """JTN-380: javascript: URLs must be rejected server-side."""
    data = {
        "plugin_id": "rss",
        "title": "Test Feed",
        "feedUrl": "javascript:alert(1)",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 400
    body = resp.get_json() or {}
    assert body.get("success") is False


def test_save_plugin_settings_rejects_ftp_scheme(client):
    """JTN-380: ftp:// URLs must be rejected server-side."""
    data = {
        "plugin_id": "rss",
        "title": "Test Feed",
        "feedUrl": "ftp://example.com/feed",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 400


def test_save_plugin_settings_accepts_https_feed(client):
    """JTN-380: valid https feeds save successfully."""
    data = {
        "plugin_id": "rss",
        "title": "Test Feed",
        "feedUrl": "https://example.com/feed.xml",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 200
    body = resp.get_json() or {}
    assert body.get("success") is True
