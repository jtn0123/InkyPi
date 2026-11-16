# pyright: reportMissingImports=false
"""Image Album (Immich): redirects never carry the API key, and the LAN opt-in.

``requests`` keeps custom headers such as ``x-api-key`` when it follows a
redirect to another host, so the Immich API calls must not follow redirects
and the asset download (a guarded stream) must drop the key on a
cross-origin hop.  HTTP goes through a real ``requests.Session`` with a
recording transport adapter, so header handling is what ``requests`` really
does; DNS comes from a table.  No real network.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from collections.abc import Callable
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from PIL import Image
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

IMMICH = "https://immich.example.com"
HOSTS = {
    "immich.example.com": "93.184.216.34",
    "evil.example.net": "93.184.216.35",
    "cdn.example.net": "93.184.216.36",
    "tailnet.example.com": "100.101.102.103",
}

Route = tuple[int, dict[str, str], bytes]


def _png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (40, 30), "blue").save(buf, format="PNG")
    return buf.getvalue()


def _json(data: object) -> Route:
    return 200, {"Content-Type": "application/json"}, json.dumps(data).encode()


def _redirect(location: str, status: int = 302) -> Route:
    return status, {"Location": location}, b""


class RecordingAdapter(BaseAdapter):
    """Answer requests from a table keyed by ``(method, url)``.

    A list value is served in order, one entry per request.
    """

    def __init__(self, routes: dict[tuple[str, str], Route | list[Route]]) -> None:
        super().__init__()
        self.routes = routes
        self.sent: list[requests.PreparedRequest] = []
        self.session = requests.Session()
        self.session.mount("http://", self)
        self.session.mount("https://", self)

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        self.sent.append(request)
        key = (request.method or "", request.url or "")
        if key not in self.routes:
            raise AssertionError(f"unexpected request {key}")
        route = self.routes[key]
        status, headers, body = route.pop(0) if isinstance(route, list) else route
        resp = requests.Response()
        resp.status_code = status
        resp.headers = CaseInsensitiveDict(headers)
        resp.raw = BytesIO(body)
        resp.url = request.url or ""
        resp.request = request
        resp.encoding = "utf-8"
        return resp

    def close(self) -> None:
        return None

    def hosts(self) -> list[str]:
        import urllib.parse as _urlparse

        return [_urlparse.urlsplit(r.url or "").hostname or "" for r in self.sent]


@pytest.fixture(autouse=True)
def _table_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def _resolve(host: Any, port: Any = 0, *a: Any, **kw: Any) -> Any:
        host_s = host.decode() if isinstance(host, bytes) else str(host)
        ip = HOSTS.get(host_s, host_s)
        ipaddress.ip_address(ip)  # unknown names fail loudly
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, int(port or 0)))]

    monkeypatch.setattr(socket, "getaddrinfo", _resolve)
    monkeypatch.delenv("INKYPI_ALLOW_PRIVATE_FEEDS", raising=False)


@pytest.fixture
def immich_session(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[dict[tuple[str, str], Route | list[Route]]], RecordingAdapter]:
    """Serve the plugin's and the image loader's HTTP from one adapter."""

    def _install(
        routes: dict[tuple[str, str], Route | list[Route]],
    ) -> RecordingAdapter:
        adapter = RecordingAdapter(routes)
        monkeypatch.setattr(
            "plugins.image_album.image_album.get_http_session", lambda: adapter.session
        )
        monkeypatch.setattr(
            "utils.image_loader.get_http_session", lambda: adapter.session
        )
        return adapter

    return _install


def _provider(**kwargs: Any) -> Any:
    from plugins.image_album.image_album import ImmichProvider
    from utils.image_loader import AdaptiveImageLoader

    return ImmichProvider(
        IMMICH,
        "immich-secret",
        kwargs.pop("image_loader", None) or AdaptiveImageLoader(),
        pinned_ips=(HOSTS["immich.example.com"],),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# API calls never follow redirects
# ---------------------------------------------------------------------------


def test_requests_alone_would_send_the_key_to_the_redirect_host(
    immich_session: Any,
) -> None:
    """Why the fix is needed: requests keeps x-api-key across hosts."""
    adapter = immich_session(
        {
            ("GET", f"{IMMICH}/api/albums"): _redirect(
                "https://evil.example.net/api/albums"
            ),
            ("GET", "https://evil.example.net/api/albums"): _json([]),
        }
    )
    adapter.session.get(f"{IMMICH}/api/albums", headers={"x-api-key": "immich-secret"})
    assert adapter.sent[1].headers["x-api-key"] == "immich-secret"


def test_album_lookup_refuses_a_redirect_to_another_host(immich_session: Any) -> None:
    adapter = immich_session(
        {
            ("GET", f"{IMMICH}/api/albums"): _redirect(
                "https://evil.example.net/api/albums"
            ),
        }
    )
    with pytest.raises(RuntimeError, match="redirect"):
        _provider().get_album_id("Trips")

    assert adapter.hosts() == ["immich.example.com"]
    assert adapter.sent[0].headers["x-api-key"] == "immich-secret"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_asset_search_refuses_a_redirect(immich_session: Any, status: int) -> None:
    adapter = immich_session(
        {
            ("POST", f"{IMMICH}/api/search/metadata"): _redirect(
                "https://evil.example.net/api/search/metadata", status
            ),
        }
    )
    with pytest.raises(RuntimeError, match=str(status)):
        _provider().get_assets("album-1")
    assert adapter.hosts() == ["immich.example.com"]


def test_a_redirect_fails_the_refresh_without_reaching_the_other_host(
    immich_session: Any,
) -> None:
    adapter = immich_session(
        {
            ("GET", f"{IMMICH}/api/albums"): _redirect(
                "https://evil.example.net/api/albums"
            ),
        }
    )
    assert _provider().get_image("Trips", (40, 30)) is None
    assert "evil.example.net" not in adapter.hosts()


# ---------------------------------------------------------------------------
# Asset download: the guarded stream drops the key on a cross-origin hop
# ---------------------------------------------------------------------------


def _album_routes(asset_route: Route) -> dict[tuple[str, str], Route | list[Route]]:
    return {
        ("GET", f"{IMMICH}/api/albums"): _json([{"albumName": "Trips", "id": "a1"}]),
        ("POST", f"{IMMICH}/api/search/metadata"): [
            _json({"assets": {"items": [{"id": "asset-1"}]}}),
            _json({"assets": {"items": []}}),
        ],
        ("GET", f"{IMMICH}/api/assets/asset-1/original"): asset_route,
    }


def test_asset_redirect_to_another_host_drops_the_api_key(
    immich_session: Any,
) -> None:
    routes = _album_routes(_redirect("https://cdn.example.net/asset-1.png"))
    routes[("GET", "https://cdn.example.net/asset-1.png")] = (
        200,
        {"Content-Type": "image/png"},
        _png(),
    )
    adapter = immich_session(routes)

    img = _provider().get_image("Trips", (40, 30))

    assert img is not None
    by_host = list(zip(adapter.hosts(), adapter.sent, strict=True))
    assert [host for host, _ in by_host][-1] == "cdn.example.net"
    for host, request in by_host:
        has_key = "x-api-key" in request.headers
        assert has_key is (host == "immich.example.com"), host
    cdn_request = by_host[-1][1]
    assert cdn_request.headers["User-Agent"].startswith("InkyPi/")


def test_asset_redirect_to_a_private_address_is_refused(immich_session: Any) -> None:
    adapter = immich_session(_album_routes(_redirect("http://192.168.1.5/x.png")))
    assert _provider().get_image("Trips", (40, 30)) is None
    assert "192.168.1.5" not in adapter.hosts()


# ---------------------------------------------------------------------------
# LAN / Tailscale opt-in
# ---------------------------------------------------------------------------


def _album_settings(url: str) -> dict[str, object]:
    return {"albumProvider": "Immich", "url": url, "album": "Trips"}


def test_tailscale_immich_needs_the_opt_in(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    from plugins.image_album.image_album import ImageAlbum
    from utils.plugin_errors import URL_ERR_PRIVATE_FEED, URLValidationError

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda _k: "immich-secret")
    plugin = ImageAlbum({"id": "image_album"})

    with pytest.raises(URLValidationError) as excinfo:
        plugin.generate_image(
            _album_settings("https://tailnet.example.com"), device_config_dev
        )
    assert excinfo.value.reason == URL_ERR_PRIVATE_FEED


def test_tailscale_immich_works_with_the_opt_in(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    import plugins.image_album.image_album as image_album

    monkeypatch.setenv("INKYPI_ALLOW_PRIVATE_FEEDS", "1")
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda _k: "immich-secret")
    created: dict[str, Any] = {}

    class FakeProvider:
        def __init__(self, url: str, key: str, loader: Any, **kwargs: Any) -> None:
            created.update(url=url, **kwargs)

        def get_image(self, album: str, dimensions: Any, resize: bool = True) -> Any:
            return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(image_album, "ImmichProvider", FakeProvider)

    img = image_album.ImageAlbum({"id": "image_album"}).generate_image(
        _album_settings("https://tailnet.example.com"), device_config_dev
    )

    assert img is not None
    assert created["allow_lan"] is True
    assert created["pinned_ips"] == (HOSTS["tailnet.example.com"],)


@pytest.mark.parametrize("allow_lan", [False, True])
def test_provider_passes_the_opt_in_to_the_asset_download(
    immich_session: Any, allow_lan: bool
) -> None:
    immich_session(_album_routes(_json({})))
    loader = MagicMock()
    loader.from_url.return_value = Image.new("RGB", (4, 3))

    _provider(image_loader=loader, allow_lan=allow_lan).get_image("Trips", (4, 3))

    assert loader.from_url.call_args.kwargs["allow_lan"] is allow_lan
    assert loader.from_url.call_args.kwargs["headers"] == {"x-api-key": "immich-secret"}
