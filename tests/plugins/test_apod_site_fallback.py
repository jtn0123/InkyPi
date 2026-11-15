"""APOD falls back to the APOD website when the API has no usable picture.

Since the APOD site moved to science.nasa.gov the API answers every date with
a NASA-logo placeholder (and today's date with HTTP 500), so the plugin reads
the picture from the dated page, or from the feed for today.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from PIL import Image

PLACEHOLDER = {
    "date": "2026-04-24",
    "media_type": "image",
    "title": "NASA Science",
    "url": "https://science.nasa.gov/wp-content/themes/nasa-child/assets/images/nasa-logo@2x.png",
    "hdurl": "https://science.nasa.gov/wp-content/themes/nasa-child/assets/images/nasa-logo@2x.png",
}

PICTURE = "https://assets.science.nasa.gov/content/dam/apod/2026/april/moon.jpg/renditions/web.1280.jpeg"
ARTICLE = "https://science.nasa.gov/image-article/apod-2026-april-24-young-moon-and-sister-stars/"


def _page(
    image: str | None = PICTURE,
    title: str = "APOD: 2026 April 24 - Young Moon and Sister Stars - NASA Science",
    url: str = ARTICLE,
) -> bytes:
    # A second og:image checks that the first one wins.
    image_tags = (
        f'<meta property="og:image" content="{image}" />'
        '<meta property="og:image" content="https://example.com/second.jpg" />'
        if image
        else ""
    )
    return (
        "<html><head>"
        f'<meta property="og:url" content="{url}" />'
        f'<meta property="og:title" content="{title}" />'
        f"{image_tags}"
        "</head><body></body></html>"
    ).encode()


FEED = b"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0"><channel><title>APOD Basic</title>
<item>
  <title>Apollo 12 and Surveyor 3</title>
  <link>https://science.nasa.gov/image-article/apod-2026-november-14-apollo-12-and-surveyor-3/</link>
  <pubDate>Sat, 14 Nov 2026 05:05:00 +0000</pubDate>
</item>
<item>
  <title>Older entry</title>
  <link>https://science.nasa.gov/image-article/apod-2026-november-13-older/</link>
</item>
</channel></rss>"""


def _api(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: int = 200,
    body: Any = None,
    exc: Exception | None = None,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.text = "Internal Server Error"
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    session = MagicMock()
    if exc is not None:
        session.get.side_effect = exc
    else:
        session.get.return_value = response
    monkeypatch.setattr("plugins.apod.apod.get_http_session", lambda: session)
    return session


def _site(monkeypatch: pytest.MonkeyPatch, pages: dict[str, bytes]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(url: str, **kwargs: Any) -> bytes:
        fetched.append(url)
        assert kwargs["max_bytes"] > 0
        if url not in pages:
            raise requests.HTTPError(f"404 for {url}")
        return pages[url]

    monkeypatch.setattr("plugins.apod.apod.safe_fetch_bytes", fake_fetch)
    return fetched


def _plugin(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> tuple[Any, MagicMock]:
    from plugins.apod.apod import Apod

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "test_key")
    plugin = Apod({"id": "apod"})
    loader = MagicMock(return_value=Image.new("RGB", (800, 480), "black"))
    monkeypatch.setattr(plugin.image_loader, "from_url", loader)
    return plugin, loader


def test_placeholder_answer_uses_the_dated_page(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    _api(monkeypatch, body=PLACEHOLDER)
    fetched = _site(monkeypatch, {"https://apod.nasa.gov/apod/ap260424.html": _page()})
    plugin, loader = _plugin(monkeypatch, device_config_dev)

    image = plugin.generate_image(
        {"randomizeApod": "false", "customDate": "2026-04-24"}, device_config_dev
    )

    assert image.size == (800, 480)
    assert fetched == ["https://apod.nasa.gov/apod/ap260424.html"]
    assert loader.call_args.args[0] == PICTURE
    meta = plugin.get_latest_metadata()
    assert meta["title"] == "Young Moon and Sister Stars"
    assert meta["date"] == "2026-04-24"
    assert meta["page_url"] == ARTICLE


def test_api_error_for_today_uses_the_newest_feed_entry(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    newest = "https://science.nasa.gov/image-article/apod-2026-november-14-apollo-12-and-surveyor-3/"
    _api(monkeypatch, status=500)
    fetched = _site(
        monkeypatch,
        {
            "https://science.nasa.gov/feed/apod-basic/": FEED,
            newest: _page(
                title="APOD: 2026 November 14 – Apollo 12 and Surveyor 3 - NASA Science",
                url=newest,
            ),
        },
    )
    plugin, loader = _plugin(monkeypatch, device_config_dev)

    plugin.generate_image({}, device_config_dev)

    assert fetched == ["https://science.nasa.gov/feed/apod-basic/", newest]
    assert loader.call_args.args[0] == PICTURE
    meta = plugin.get_latest_metadata()
    assert meta["title"] == "Apollo 12 and Surveyor 3"
    assert meta["date"] == "2026-11-14"


@pytest.mark.parametrize(
    "api",
    [
        {"exc": requests.ConnectionError("down")},
        {"body": ValueError("not json")},
    ],
    ids=["request-error", "not-json"],
)
def test_unreachable_or_garbled_api_uses_the_website(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any, api: dict[str, Any]
) -> None:
    _api(monkeypatch, **api)
    _site(monkeypatch, {"https://apod.nasa.gov/apod/ap260424.html": _page()})
    plugin, loader = _plugin(monkeypatch, device_config_dev)

    plugin.generate_image({"customDate": "2026-04-24"}, device_config_dev)

    assert loader.call_args.args[0] == PICTURE


@pytest.mark.parametrize(
    "page",
    [
        _page(image=None),
        _page(image=PLACEHOLDER["url"]),
        _page(url="https://science.nasa.gov/apod/"),
    ],
    ids=["no-image", "placeholder-image", "landing-page"],
)
def test_website_without_a_picture_fails_clearly(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any, page: bytes
) -> None:
    _api(monkeypatch, body=PLACEHOLDER)
    _site(monkeypatch, {"https://apod.nasa.gov/apod/ap260424.html": page})
    plugin, loader = _plugin(monkeypatch, device_config_dev)

    with pytest.raises(RuntimeError, match="Failed to retrieve NASA APOD"):
        plugin.generate_image({"customDate": "2026-04-24"}, device_config_dev)
    loader.assert_not_called()


@pytest.mark.parametrize(
    "feed",
    [
        b"<rss><channel><title>empty</title></channel></rss>",
        b"<rss><channel><item><title>x</title><link>http://insecure.example/</link></item></channel></rss>",
    ],
    ids=["no-entries", "not-https"],
)
def test_unusable_feed_fails_clearly(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any, feed: bytes
) -> None:
    _api(monkeypatch, status=500)
    _site(monkeypatch, {"https://science.nasa.gov/feed/apod-basic/": feed})
    plugin, _ = _plugin(monkeypatch, device_config_dev)

    with pytest.raises(RuntimeError, match="Failed to retrieve NASA APOD"):
        plugin.generate_image({}, device_config_dev)


def test_website_request_error_fails_clearly(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    _api(monkeypatch, body=PLACEHOLDER)
    _site(monkeypatch, {})
    plugin, _ = _plugin(monkeypatch, device_config_dev)

    with pytest.raises(RuntimeError, match="Failed to retrieve NASA APOD"):
        plugin.generate_image({"customDate": "2026-04-24"}, device_config_dev)


def test_real_api_answer_does_not_touch_the_website(
    monkeypatch: pytest.MonkeyPatch,
    device_config_dev: Any,
    realistic_nasa_apod_response: Any,
) -> None:
    _api(monkeypatch, body=realistic_nasa_apod_response)
    fetched = _site(monkeypatch, {})
    plugin, _ = _plugin(monkeypatch, device_config_dev)

    plugin.generate_image({}, device_config_dev)

    assert fetched == []
    assert plugin.get_latest_metadata()["title"] == "The Center of the Milky Way"


def test_blank_custom_date_asks_for_today(
    monkeypatch: pytest.MonkeyPatch,
    device_config_dev: Any,
    realistic_nasa_apod_response: Any,
) -> None:
    session = _api(monkeypatch, body=realistic_nasa_apod_response)
    plugin, _ = _plugin(monkeypatch, device_config_dev)

    plugin.generate_image(
        {"randomizeApod": "false", "customDate": "  "}, device_config_dev
    )

    assert "date" not in session.get.call_args.kwargs["params"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "APOD: 2026 April 24 - Young Moon and Sister Stars - NASA Science",
            "Young Moon and Sister Stars",
        ),
        ("APOD: 2026 November 14 – Apollo 12 - NASA Science", "Apollo 12"),
        ("Plain title", "Plain title"),
        ("APOD: 2026 April 24 - No Suffix", "No Suffix"),
        ("", None),
        (None, None),
    ],
)
def test_clean_title(raw: str | None, expected: str | None) -> None:
    from plugins.apod.apod import _clean_title

    assert _clean_title(raw) == expected
