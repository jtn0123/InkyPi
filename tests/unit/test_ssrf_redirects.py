# pyright: reportMissingImports=false
"""SSRF guard regression tests: redirects, LAN opt-in, body caps, DNS pin cleanup.

Only the first URL used to be validated and DNS-pinned, so a public host
answering ``302 Location: http://192.168.1.1/`` was followed unchecked.  The
guarded fetch paths now follow redirects manually and re-validate every hop.
RSS and Calendar fetches go through the same guard with a byte cap and an
explicit ``INKYPI_ALLOW_PRIVATE_FEEDS`` opt-in for LAN servers.

No real network: ``socket.getaddrinfo`` is replaced by a table-driven
resolver and HTTP is served by fake sessions / ``http_get`` doubles.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from typing import Any

import pytest
import requests
from requests.structures import CaseInsensitiveDict

PUBLIC_A = "93.184.216.34"
PUBLIC_B = "93.184.216.35"

HOSTS = {
    "public.example.com": PUBLIC_A,
    "cdn.example.net": PUBLIC_B,
    "lan.example.com": "192.168.1.20",
    "loop.example.com": "127.0.0.1",
}


def _ainfo(ip: str, port: int = 0) -> list[Any]:
    if ipaddress.ip_address(ip).version == 6:
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0))]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


@pytest.fixture(autouse=True)
def _table_dns(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Resolve names from HOSTS; literals resolve to themselves."""
    lookups: list[str] = []

    def _resolve(host: Any, port: Any = 0, *a: Any, **kw: Any) -> Any:
        host_s = host.decode() if isinstance(host, bytes) else str(host)
        lookups.append(host_s)
        try:
            ipaddress.ip_address(host_s)
            return _ainfo(host_s, int(port or 0))
        except ValueError:
            pass
        if host_s not in HOSTS:
            raise socket.gaierror(f"unknown host {host_s}")
        return _ainfo(HOSTS[host_s], int(port or 0))

    monkeypatch.setattr(socket, "getaddrinfo", _resolve)
    monkeypatch.delenv("INKYPI_ALLOW_PRIVATE_FEEDS", raising=False)
    return lookups


class FakeResp:
    def __init__(
        self,
        status: int = 200,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        chunk: int = 4096,
    ) -> None:
        self.status_code = status
        self.body = body
        self.content = body
        self.headers = CaseInsensitiveDict(headers or {})
        self.closed = False
        self._chunk = chunk

    def iter_content(self, chunk_size: int = 1) -> Any:
        step = self._chunk
        for i in range(0, len(self.body), step):
            yield self.body[i : i + step]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def close(self) -> None:
        self.closed = True


def _redirect(location: str, status: int = 302) -> FakeResp:
    return FakeResp(status, headers={"Location": location})


class Router:
    """Serve canned responses by URL and record what was fetched and resolved."""

    def __init__(self, routes: dict[str, FakeResp]) -> None:
        self.routes = routes
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> FakeResp:
        import urllib.parse as _urlparse

        host = _urlparse.urlparse(url).hostname or ""
        resolved = socket.getaddrinfo(host, 443)[0][4][0]
        self.calls.append({"url": url, "ip": resolved, **kwargs})
        if url not in self.routes:
            raise AssertionError(f"unexpected fetch of {url}")
        return self.routes[url]


@pytest.fixture
def http_get_router(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Route ``utils.http_utils.http_get``'s session through a Router."""
    from utils import http_utils

    http_utils._reset_shared_session_for_tests()

    def _install(routes: dict[str, FakeResp]) -> Router:
        router = Router(routes)

        def fake_session_get(self: Any, url: str, **kwargs: Any) -> FakeResp:
            return router(url, **kwargs)

        monkeypatch.setattr(requests.Session, "get", fake_session_get)
        return router

    return _install


# ---------------------------------------------------------------------------
# safe_http_get / guarded_fetch
# ---------------------------------------------------------------------------


def test_redirect_to_private_ip_is_blocked(http_get_router: Any) -> None:
    from utils.http_utils import safe_http_get

    router = http_get_router(
        {"https://public.example.com/a": _redirect("http://192.168.1.1/admin")}
    )
    with pytest.raises(ValueError, match="private"):
        safe_http_get("https://public.example.com/a")
    assert [c["url"] for c in router.calls] == ["https://public.example.com/a"]
    assert all(c["allow_redirects"] is False for c in router.calls)


def test_redirect_to_hostname_resolving_private_is_blocked(
    http_get_router: Any,
) -> None:
    from utils.http_utils import safe_http_get

    http_get_router(
        {"https://public.example.com/a": _redirect("http://loop.example.com/")}
    )
    with pytest.raises(ValueError, match="private"):
        safe_http_get("https://public.example.com/a")


def test_redirect_to_public_host_is_followed_and_pinned(
    http_get_router: Any, _table_dns: list[str]
) -> None:
    from utils.http_utils import safe_http_get

    final = FakeResp(200, b"ok")
    router = http_get_router(
        {
            "https://public.example.com/a": _redirect(
                "https://cdn.example.net/b", status=301
            ),
            "https://cdn.example.net/b": final,
        }
    )
    resp: object = safe_http_get("https://public.example.com/a", use_cache=False)
    assert resp is final
    assert [(c["url"], c["ip"]) for c in router.calls] == [
        ("https://public.example.com/a", PUBLIC_A),
        ("https://cdn.example.net/b", PUBLIC_B),
    ]
    # The intermediate redirect response is released.
    assert router.routes["https://public.example.com/a"].closed


def test_relative_redirect_resolves_against_current_url(http_get_router: Any) -> None:
    from utils.http_utils import safe_http_get

    final = FakeResp(200, b"ok")
    router = http_get_router(
        {
            "https://public.example.com/dir/a": _redirect("../other?x=1", 307),
            "https://public.example.com/other?x=1": final,
        }
    )
    resp: object = safe_http_get("https://public.example.com/dir/a", use_cache=False)
    assert resp is final
    assert router.calls[-1]["url"] == "https://public.example.com/other?x=1"


def test_too_many_redirects_fails(http_get_router: Any) -> None:
    from utils.http_utils import MAX_GUARDED_REDIRECTS, safe_http_get

    routes = {
        f"https://public.example.com/{i}": _redirect(f"/{i + 1}")
        for i in range(MAX_GUARDED_REDIRECTS + 2)
    }
    router = http_get_router(routes)
    with pytest.raises(requests.TooManyRedirects):
        safe_http_get("https://public.example.com/0", use_cache=False)
    assert len(router.calls) == MAX_GUARDED_REDIRECTS + 1


def test_allow_redirects_false_returns_redirect_response(http_get_router: Any) -> None:
    from utils.http_utils import safe_http_get

    redirect = _redirect("http://192.168.1.1/")
    http_get_router({"https://public.example.com/a": redirect})
    resp: object = safe_http_get(
        "https://public.example.com/a", allow_redirects=False, use_cache=False
    )
    assert resp is redirect


def test_cross_origin_redirect_drops_credentials(http_get_router: Any) -> None:
    from utils.http_utils import safe_http_get

    router = http_get_router(
        {
            "https://public.example.com/a": _redirect("https://cdn.example.net/b"),
            "https://cdn.example.net/b": FakeResp(200),
        }
    )
    safe_http_get(
        "https://public.example.com/a",
        headers={"Authorization": "Bearer s3cret", "X-Keep": "1"},
        use_cache=False,
    )
    first, second = router.calls
    assert first["headers"]["Authorization"] == "Bearer s3cret"
    assert "Authorization" not in second["headers"]
    assert second["headers"]["X-Keep"] == "1"


# ---------------------------------------------------------------------------
# image_utils callers
# ---------------------------------------------------------------------------


def _image_router(
    monkeypatch: pytest.MonkeyPatch, routes: dict[str, FakeResp]
) -> Router:
    import utils.image_utils as image_utils

    router = Router(routes)
    monkeypatch.setattr(image_utils, "http_get", router)
    return router


def test_get_image_refuses_redirect_to_private(monkeypatch: pytest.MonkeyPatch) -> None:
    import utils.image_utils as image_utils

    router = _image_router(
        monkeypatch,
        {"http://public.example.com/i.png": _redirect("http://10.0.0.5/i.png")},
    )
    assert image_utils.get_image("http://public.example.com/i.png") is None
    assert len(router.calls) == 1


def test_get_image_follows_public_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    from io import BytesIO

    from PIL import Image

    import utils.image_utils as image_utils

    buf = BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="PNG")
    router = _image_router(
        monkeypatch,
        {
            "http://public.example.com/i.png": _redirect("http://cdn.example.net/i"),
            "http://cdn.example.net/i": FakeResp(200, buf.getvalue()),
        },
    )
    img = image_utils.get_image("http://public.example.com/i.png")
    assert img is not None
    assert img.size == (4, 4)
    assert router.calls[1]["ip"] == PUBLIC_B


def test_fetch_and_resize_refuses_redirect_to_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import utils.image_utils as image_utils

    _image_router(
        monkeypatch,
        {"http://public.example.com/p.jpg": _redirect("http://169.254.169.254/")},
    )
    assert (
        image_utils.fetch_and_resize_remote_image(
            "http://public.example.com/p.jpg", (10, 10)
        )
        is None
    )


def test_stream_to_disk_refuses_redirect_to_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import utils.image_utils as image_utils

    router = _image_router(
        monkeypatch,
        {"http://public.example.com/p.jpg": _redirect("http://192.168.0.1/p")},
    )
    with pytest.raises(ValueError, match="private"):
        image_utils._stream_to_disk("http://public.example.com/p.jpg", 5.0, (PUBLIC_A,))
    assert router.calls[0]["stream"] is True
    assert router.calls[0]["allow_redirects"] is False


# ---------------------------------------------------------------------------
# validate_url_with_ips: literal IPs and the LAN opt-in
# ---------------------------------------------------------------------------


def test_private_literal_rejected_even_if_resolver_lies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A literal private IP must not fall through to a (patched) DNS lookup."""
    from utils.security_utils import validate_url_with_ips

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _ainfo(PUBLIC_A))
    with pytest.raises(ValueError, match="private"):
        validate_url_with_ips("http://192.168.1.1/")


@pytest.mark.parametrize(
    "url",
    ["http://192.168.1.20/cal.ics", "http://lan.example.com/x", "http://[fd00::5]/x"],
)
def test_allow_lan_admits_site_local_addresses(url: str) -> None:
    from utils.security_utils import LanAddressError, validate_url_with_ips

    with pytest.raises(LanAddressError):
        validate_url_with_ips(url)
    _, ips = validate_url_with_ips(url, allow_lan=True)
    assert ips


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://loop.example.com/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://0.0.0.0/",
    ],
)
def test_allow_lan_still_blocks_loopback_and_link_local(url: str) -> None:
    from utils.security_utils import LanAddressError, validate_url_with_ips

    with pytest.raises(ValueError) as excinfo:
        validate_url_with_ips(url, allow_lan=True)
    assert not isinstance(excinfo.value, LanAddressError)


# ---------------------------------------------------------------------------
# Byte caps
# ---------------------------------------------------------------------------


def test_read_capped_rejects_declared_oversize_without_reading() -> None:
    from utils.http_utils import ResponseTooLargeError, read_capped

    resp = FakeResp(200, b"x" * 10, headers={"Content-Length": "1000"})
    resp.iter_content = None  # type: ignore[assignment,method-assign]
    with pytest.raises(ResponseTooLargeError):
        read_capped(resp, 100)


def test_read_capped_rejects_streamed_oversize() -> None:
    from utils.http_utils import ResponseTooLargeError, read_capped

    oversized = FakeResp(200, b"x" * 300, chunk=64)
    with pytest.raises(ResponseTooLargeError):
        read_capped(oversized, 200)
    assert read_capped(FakeResp(200, b"x" * 200, chunk=64), 200) == b"x" * 200


def test_safe_fetch_bytes_rejects_oversized_body(http_get_router: Any) -> None:
    from utils.http_utils import ResponseTooLargeError, safe_fetch_bytes

    resp = FakeResp(200, b"y" * 5000, chunk=1000)
    http_get_router({"https://public.example.com/big": resp})
    with pytest.raises(ResponseTooLargeError):
        safe_fetch_bytes("https://public.example.com/big", max_bytes=1024)
    assert resp.closed


# ---------------------------------------------------------------------------
# pinned_dns: out-of-order thread exit must not leak / stack the wrapper
# ---------------------------------------------------------------------------


def _wait(event: threading.Event, what: str) -> None:
    if not event.wait(5):
        raise TimeoutError(f"timed out waiting for {what}")


def _saved_resolver() -> object:
    from utils import http_utils

    return http_utils._dns_pin_saved


def test_pinned_dns_restores_resolver_when_threads_exit_out_of_order() -> None:
    from utils import http_utils

    original = socket.getaddrinfo
    a_entered, b_entered, a_exited = (threading.Event() for _ in range(3))
    errors: list[BaseException] = []

    def thread_a() -> None:
        try:
            with http_utils.pinned_dns("a.example.com", (PUBLIC_A,)):
                a_entered.set()
                _wait(b_entered, "thread b to enter")
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            a_exited.set()

    def thread_b() -> None:
        try:
            _wait(a_entered, "thread a to enter")
            with http_utils.pinned_dns("b.example.com", (PUBLIC_B,)):
                b_entered.set()
                _wait(a_exited, "thread a to exit")
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=thread_a), threading.Thread(target=thread_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert not errors
    assert socket.getaddrinfo is original, "pin wrapper leaked after last exit"
    assert http_utils._dns_pin_depth == 0
    assert _saved_resolver() is None

    # A later pin must wrap the original resolver, not a leaked wrapper.
    with http_utils.pinned_dns("c.example.com", (PUBLIC_A,)):
        assert _saved_resolver() is original
    assert socket.getaddrinfo is original


# ---------------------------------------------------------------------------
# RSS and Calendar plugins
# ---------------------------------------------------------------------------


class FakeSession:
    def __init__(self, routes: dict[str, FakeResp]) -> None:
        self.router = Router(routes)

    def get(self, url: str, **kwargs: Any) -> FakeResp:
        return self.router(url, **kwargs)


RSS_XML = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
    b"<item><title>Hello</title><description>d</description></item>"
    b"</channel></rss>"
)
ICS = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//EN\r\n"
    b"BEGIN:VEVENT\r\nUID:1\r\nDTSTART:20260101T100000Z\r\n"
    b"DTEND:20260101T110000Z\r\nSUMMARY:Standup\r\nEND:VEVENT\r\n"
    b"END:VCALENDAR\r\n"
)


def _rss(monkeypatch: pytest.MonkeyPatch, routes: dict[str, FakeResp]) -> Any:
    from plugins.rss.rss import Rss

    session = FakeSession(routes)
    monkeypatch.setattr("plugins.rss.rss.get_http_session", lambda: session)
    return Rss({"id": "rss"}), session


def _calendar(monkeypatch: pytest.MonkeyPatch, routes: dict[str, FakeResp]) -> Any:
    from plugins.calendar.calendar import Calendar

    session = FakeSession(routes)
    monkeypatch.setattr("plugins.calendar.calendar.get_http_session", lambda: session)
    return Calendar({"id": "calendar"}), session


def test_rss_fetch_is_streamed_without_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rss, session = _rss(
        monkeypatch, {"https://public.example.com/feed": FakeResp(200, RSS_XML)}
    )
    items = rss.parse_rss_feed("https://public.example.com/feed")
    assert [i["title"] for i in items] == ["Hello"]
    call = session.router.calls[0]
    assert call["stream"] is True
    assert call["allow_redirects"] is False
    assert call["headers"]["User-Agent"] == "Mozilla/5.0"


def test_rss_private_url_blocked_with_opt_in_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from utils.plugin_errors import URL_ERR_PRIVATE_FEED, URLValidationError

    rss, session = _rss(monkeypatch, {})
    with pytest.raises(URLValidationError) as excinfo:
        rss.parse_rss_feed("http://192.168.1.20/feed.xml")
    assert excinfo.value.safe_message() == f"Invalid URL: {URL_ERR_PRIVATE_FEED}"
    assert "INKYPI_ALLOW_PRIVATE_FEEDS=1" in excinfo.value.safe_message()
    assert session.router.calls == []


def test_rss_private_url_allowed_with_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INKYPI_ALLOW_PRIVATE_FEEDS", "1")
    rss, _ = _rss(
        monkeypatch, {"http://lan.example.com/feed.xml": FakeResp(200, RSS_XML)}
    )
    assert rss.parse_rss_feed("http://lan.example.com/feed.xml")[0]["title"] == "Hello"


def test_rss_opt_in_does_not_admit_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    from utils.plugin_errors import URL_ERR_PRIVATE, URLValidationError

    monkeypatch.setenv("INKYPI_ALLOW_PRIVATE_FEEDS", "1")
    rss, _ = _rss(monkeypatch, {})
    with pytest.raises(URLValidationError) as excinfo:
        rss.parse_rss_feed("http://127.0.0.1:8080/feed")
    assert excinfo.value.reason == URL_ERR_PRIVATE


def test_rss_redirect_to_private_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    from utils.plugin_errors import URLValidationError

    rss, session = _rss(
        monkeypatch,
        {"https://public.example.com/feed": _redirect("http://10.1.2.3/feed")},
    )
    with pytest.raises(URLValidationError):
        rss.parse_rss_feed("https://public.example.com/feed")
    assert len(session.router.calls) == 1


def test_rss_oversized_feed_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.rss import rss as rss_mod
    from utils.http_utils import ResponseTooLargeError

    monkeypatch.setattr(rss_mod, "MAX_FEED_BYTES", 64)
    rss, _ = _rss(
        monkeypatch, {"https://public.example.com/feed": FakeResp(200, RSS_XML)}
    )
    with pytest.raises(ResponseTooLargeError):
        rss.parse_rss_feed("https://public.example.com/feed")


def test_calendar_public_redirect_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    cal, session = _calendar(
        monkeypatch,
        {
            "https://public.example.com/c.ics": _redirect("/real.ics", 302),
            "https://public.example.com/real.ics": FakeResp(200, ICS),
        },
    )
    parsed = cal.fetch_calendar("webcal://public.example.com/c.ics")
    assert [str(e.get("summary")) for e in parsed.walk("VEVENT")] == ["Standup"]
    assert [c["url"] for c in session.router.calls] == [
        "https://public.example.com/c.ics",
        "https://public.example.com/real.ics",
    ]


def test_calendar_private_url_blocked_with_opt_in_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from utils.plugin_errors import URL_ERR_PRIVATE_FEED, URLValidationError

    cal, session = _calendar(monkeypatch, {})
    with pytest.raises(URLValidationError) as excinfo:
        cal.fetch_calendar("http://lan.example.com/remote.php/dav/cal.ics")
    assert excinfo.value.reason == URL_ERR_PRIVATE_FEED
    assert session.router.calls == []


def test_calendar_private_url_allowed_with_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INKYPI_ALLOW_PRIVATE_FEEDS", "true")
    cal, _ = _calendar(
        monkeypatch, {"http://192.168.1.20:5232/user/cal/": FakeResp(200, ICS)}
    )
    parsed = cal.fetch_calendar("http://192.168.1.20:5232/user/cal/")
    assert len(list(parsed.walk("VEVENT"))) == 1


def test_calendar_redirect_to_metadata_blocked_even_with_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from utils.plugin_errors import URLValidationError

    monkeypatch.setenv("INKYPI_ALLOW_PRIVATE_FEEDS", "1")
    cal, _ = _calendar(
        monkeypatch,
        {"https://public.example.com/c.ics": _redirect("http://169.254.169.254/")},
    )
    with pytest.raises(URLValidationError):
        cal.fetch_calendar("https://public.example.com/c.ics")


def test_calendar_oversized_ics_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.calendar import calendar as cal_mod

    monkeypatch.setattr(cal_mod, "MAX_ICS_BYTES", 32)
    cal, _ = _calendar(
        monkeypatch, {"https://public.example.com/c.ics": FakeResp(200, ICS)}
    )
    with pytest.raises(RuntimeError, match="Response too large"):
        cal.fetch_calendar("https://public.example.com/c.ics")
