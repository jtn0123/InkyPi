# pyright: reportMissingImports=false
"""RSS item images go through the SSRF guard, never the render Chromium (E2).

Feed-controlled ``media:content`` / ``media:thumbnail`` / enclosure URLs used
to be placed verbatim in ``<img src>`` and loaded by the local, file://-
privileged Chromium. They are now fetched in Python via
``safe_fetch_bytes`` (scheme + private-address checks, per-hop DNS pinning,
size cap), re-encoded, and embedded as ``data:`` URIs.
"""

from __future__ import annotations

import re
import socket
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    real_getaddrinfo = socket.getaddrinfo

    def _resolve(host: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(host, str) and host.endswith(".example"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 0))]
        if host == "rebind.example.net":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 0))]
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", _resolve)
    monkeypatch.delenv("INKYPI_ALLOW_PRIVATE_FEEDS", raising=False)


def _png_bytes(size: tuple[int, int] = (64, 48), mode: str = "RGB") -> bytes:
    buf = BytesIO()
    Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else "red").save(
        buf, format="PNG"
    )
    return buf.getvalue()


class _Resp:
    def __init__(
        self,
        body: bytes = b"",
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status_code = status
        self.headers = headers or {}

    def iter_content(self, chunk_size: int = 65536) -> Any:
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i : i + chunk_size]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self) -> None:
        pass


class _Session:
    """Records every URL the plugin asks the network for."""

    def __init__(self, routes: dict[str, _Resp]) -> None:
        self.routes = routes
        self.requested: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _Resp:
        self.requested.append(url)
        return self.routes.get(url, _Resp(status=404))


BLOCKED_URLS = [
    "http://127.0.0.1/admin.png",
    "http://localhost:8080/x.png",
    "file:///etc/passwd",
    "http://192.168.1.10/cam.jpg",
    "http://10.0.0.1/a.png",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/x.png",
    "http://rebind.example.net/x.png",
    "javascript:alert(1)",
]


def test_blocked_image_urls_are_never_requested_or_rendered() -> None:
    from plugins.rss.rss import Rss

    session = _Session({})
    items: list[dict[str, str | None]] = [
        {"title": f"t{i}", "image": url} for i, url in enumerate(BLOCKED_URLS)
    ]
    with patch("plugins.rss.rss.get_http_session", return_value=session):
        Rss._inline_item_images(items)

    assert session.requested == []
    assert all(item["image"] is None for item in items)


def test_public_image_is_fetched_via_guard_and_inlined() -> None:
    from plugins.rss import rss as rss_mod

    url = "https://cdn.news.example/pic.png"
    session = _Session({url: _Resp(_png_bytes((1200, 800)))})
    items: list[dict[str, str | None]] = [{"title": "ok", "image": url}]

    with (
        patch("plugins.rss.rss.get_http_session", return_value=session),
        patch(
            "plugins.rss.rss.safe_fetch_bytes", wraps=rss_mod.safe_fetch_bytes
        ) as guarded,
    ):
        rss_mod.Rss._inline_item_images(items)

    guarded.assert_called_once()
    assert guarded.call_args.args[0] == url
    assert guarded.call_args.kwargs["max_bytes"] == rss_mod.MAX_ITEM_IMAGE_BYTES
    assert guarded.call_args.kwargs["allow_lan"] is False
    assert session.requested == [url]

    data_uri = items[0]["image"]
    assert isinstance(data_uri, str)
    assert data_uri.startswith("data:image/jpeg;base64,")
    import base64

    decoded = Image.open(BytesIO(base64.b64decode(data_uri.split(",", 1)[1])))
    assert max(decoded.size) <= rss_mod.ITEM_IMAGE_MAX_SIDE


def test_transparent_image_is_flattened() -> None:
    from plugins.rss.rss import Rss

    data_uri = Rss._to_data_uri(_png_bytes(mode="RGBA"))
    assert data_uri is not None and data_uri.startswith("data:image/jpeg;base64,")


def test_redirect_to_loopback_is_dropped() -> None:
    from plugins.rss.rss import Rss

    url = "https://cdn.news.example/redirect.png"
    session = _Session(
        {url: _Resp(status=302, headers={"Location": "http://127.0.0.1/secret"})}
    )
    items: list[dict[str, str | None]] = [{"title": "r", "image": url}]
    with patch("plugins.rss.rss.get_http_session", return_value=session):
        Rss._inline_item_images(items)

    assert session.requested == [url]
    assert items[0]["image"] is None


def test_oversized_and_undecodable_images_are_dropped() -> None:
    from plugins.rss import rss as rss_mod

    big = "https://cdn.news.example/big.png"
    junk = "https://cdn.news.example/junk.png"
    session = _Session(
        {
            big: _Resp(
                b"x", headers={"Content-Length": str(rss_mod.MAX_ITEM_IMAGE_BYTES + 1)}
            ),
            junk: _Resp(b"<html>not an image</html>"),
        }
    )
    items: list[dict[str, str | None]] = [
        {"title": "big", "image": big},
        {"title": "junk", "image": junk},
    ]
    with patch("plugins.rss.rss.get_http_session", return_value=session):
        rss_mod.Rss._inline_item_images(items)

    assert [i["image"] for i in items] == [None, None]


def test_pixel_bomb_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.rss import rss as rss_mod

    monkeypatch.setattr(rss_mod, "MAX_ITEM_IMAGE_PIXELS", 100)
    assert rss_mod.Rss._to_data_uri(_png_bytes((20, 20))) is None


def test_time_budget_stops_further_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.rss import rss as rss_mod

    clock = iter([0.0, 0.0, 999.0, 999.0])
    monkeypatch.setattr(rss_mod, "monotonic", lambda: next(clock))
    first = "https://cdn.news.example/1.png"
    second = "https://cdn.news.example/2.png"
    session = _Session({first: _Resp(_png_bytes()), second: _Resp(_png_bytes())})
    items: list[dict[str, str | None]] = [
        {"title": "1", "image": first},
        {"title": "2", "image": second},
    ]
    with patch("plugins.rss.rss.get_http_session", return_value=session):
        rss_mod.Rss._inline_item_images(items)

    assert session.requested == [first]
    assert items[1]["image"] is None


def _feed_with_images(count: int) -> Any:
    entries = [
        {
            "title": f"Story {i}",
            "description": "d",
            "media_content": [{"url": f"https://cdn.news.example/{i}.png"}],
        }
        for i in range(count)
    ]
    feed = MagicMock()
    feed.bozo = False
    feed.entries = entries
    return feed


@pytest.mark.parametrize("include", ["true", "false"])
def test_only_rendered_items_fetch_images(device_config_dev: Any, include: str) -> None:
    from plugins.rss.rss import MAX_RENDERED_ITEMS, Rss

    routes = {
        f"https://cdn.news.example/{i}.png": _Resp(_png_bytes()) for i in range(15)
    }
    session = _Session(routes)
    captured: dict[str, Any] = {}

    def _render(self: Any, dims: Any, html: str, css: Any, params: Any) -> Any:
        captured.update(params)
        return Image.new("RGB", dims)

    with (
        patch("plugins.rss.rss.fetch_feed_bytes", return_value=b"<rss/>"),
        patch("plugins.rss.rss.feedparser.parse", return_value=_feed_with_images(15)),
        patch("plugins.rss.rss.get_http_session", return_value=session),
        patch.object(Rss, "render_image", _render),
    ):
        Rss({"id": "rss"}).generate_image(
            {"feedUrl": "https://news.example/rss", "includeImages": include},
            device_config_dev,
        )

    items = captured["items"]
    assert len(items) == MAX_RENDERED_ITEMS
    if include == "true":
        assert len(session.requested) == MAX_RENDERED_ITEMS
        assert all(str(i["image"]).startswith("data:image/jpeg") for i in items)
    else:
        assert session.requested == []
        assert all(i["image"] is None for i in items)


def test_template_renders_inlined_image_and_csp_blocks_remote() -> None:
    from plugins.base_plugin.base_plugin import BasePlugin

    html = BasePlugin({"id": "rss"})._render_template(
        "rss.html",
        {
            "title": "Feed",
            "include_images": True,
            "items": [
                {
                    "title": "a",
                    "description": "",
                    "image": "data:image/jpeg;base64,AA==",
                }
            ],
            "plugin_settings": {},
            "style_sheets": [],
            "font_faces": [],
        },
    )
    assert '<img src="data:image/jpeg;base64,AA=="' in html
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', html)
    assert csp is not None
    img_src = next(
        d.strip() for d in csp.group(1).split(";") if d.strip().startswith("img-src")
    )
    assert img_src == "img-src file: data: blob:"
