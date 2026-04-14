# pyright: reportMissingImports=false
"""Regression tests for DNS-rebinding SSRF mitigation (JTN-656).

``validate_url`` resolves DNS up-front to reject private targets, but the
subsequent HTTP fetch resolves DNS *again* inside ``urllib3``.  A hostile
authoritative server can flip the second answer to a private IP.  The
mitigation introduced in JTN-656 pins DNS (via
``utils.http_utils.pinned_dns``) to the IPs observed at validation time so
the fetch socket connects to exactly one of the vetted addresses.

These tests simulate the rebind by swapping ``socket.getaddrinfo`` between
the validation call and the fetch, and assert the pinned IP is what the
socket layer ends up using.
"""

from __future__ import annotations

import socket

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ainfo(ip: str, port: int = 0) -> list:
    """Build a minimal addrinfo tuple list for *ip* at *port*."""
    try:
        socket.inet_aton(ip)
        family = socket.AF_INET
        sockaddr: tuple = (ip, port)
    except OSError:
        family = socket.AF_INET6
        sockaddr = (ip, port, 0, 0)
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]


class _RebindingResolver:
    """Callable that returns a public IP on first call, private IP afterward."""

    def __init__(self, first: str, rebound: str) -> None:
        self.first = first
        self.rebound = rebound
        self.calls: list[str] = []

    def __call__(self, host, port=0, *args, **kwargs):
        self.calls.append(host)
        # First call (validation) → benign public IP
        if len(self.calls) == 1:
            return _ainfo(self.first, port or 0)
        # Every subsequent call → private/metadata IP (the rebind)
        return _ainfo(self.rebound, port or 0)


# ---------------------------------------------------------------------------
# validate_url_with_ips returns the exact IPs observed
# ---------------------------------------------------------------------------


def test_validate_url_with_ips_returns_resolved_addresses(monkeypatch):
    from utils.security_utils import validate_url_with_ips

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: _ainfo("93.184.216.34"),
    )
    url, ips = validate_url_with_ips("https://example.com/path")
    assert url == "https://example.com/path"
    assert ips == ("93.184.216.34",)


def test_validate_url_with_ips_literal_ip_shortcuts_dns(monkeypatch):
    """A literal public IP should validate without DNS."""
    from utils.security_utils import validate_url_with_ips

    def _should_not_be_called(*a, **kw):  # pragma: no cover - guard only
        raise AssertionError("getaddrinfo should not be invoked for literal IPs")

    monkeypatch.setattr(socket, "getaddrinfo", _should_not_be_called)
    url, ips = validate_url_with_ips("http://93.184.216.34/page")
    assert ips == ("93.184.216.34",)


# ---------------------------------------------------------------------------
# pinned_dns overrides getaddrinfo for the pinned hostname only
# ---------------------------------------------------------------------------


def test_pinned_dns_forces_getaddrinfo_to_return_pinned_ip(monkeypatch):
    from utils import http_utils

    # Baseline resolver always claims a private IP — rebind in effect.
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _ainfo("192.168.10.5"))

    with http_utils.pinned_dns("example.com", ("93.184.216.34",)):
        result = socket.getaddrinfo("example.com", 443)

    assert (
        result[0][4][0] == "93.184.216.34"
    ), "pinned_dns must short-circuit DNS for the pinned hostname"


def test_pinned_dns_does_not_affect_other_hostnames(monkeypatch):
    from utils import http_utils

    seen: dict[str, int] = {}

    def real_resolver(host, port=0, *a, **kw):
        seen[host] = seen.get(host, 0) + 1
        return _ainfo("8.8.8.8", port or 0)

    monkeypatch.setattr(socket, "getaddrinfo", real_resolver)

    with http_utils.pinned_dns("pinned.example.com", ("93.184.216.34",)):
        other = socket.getaddrinfo("other.example.net", 80)

    assert other[0][4][0] == "8.8.8.8"
    assert seen.get("other.example.net") == 1


def test_pinned_dns_restores_previous_resolver_on_exit(monkeypatch):
    from utils import http_utils

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _ainfo("192.168.10.5"))
    with http_utils.pinned_dns("example.com", ("93.184.216.34",)):
        pass
    # After exit the pin is removed — outer resolver takes over again
    result = socket.getaddrinfo("example.com", 80)
    assert result[0][4][0] == "192.168.10.5"


# ---------------------------------------------------------------------------
# End-to-end: a DNS rebind between validate and fetch cannot escape the pin
# ---------------------------------------------------------------------------


def test_safe_http_get_pins_ip_across_dns_rebind(monkeypatch):
    """Simulate an attacker flipping DNS between validate and fetch.

    ``safe_http_get`` must use the IP resolved at validation time, not the
    private IP the second resolution would return.
    """
    from utils import http_utils

    http_utils._reset_shared_session_for_tests()

    resolver = _RebindingResolver(first="93.184.216.34", rebound="169.254.169.254")
    monkeypatch.setattr(socket, "getaddrinfo", resolver)

    seen_sockaddrs: list[tuple] = []

    # Stand-in for urllib3's connect step: resolve the hostname through the
    # same socket.getaddrinfo hook that requests/urllib3 would use.  We skip
    # actually dialing a socket; the test asserts the resolver pick.
    def fake_session_get(self, url, **kwargs):
        import urllib.parse as _urlparse

        host = _urlparse.urlparse(url).hostname or ""
        addrs = socket.getaddrinfo(host, 443)
        seen_sockaddrs.append(addrs[0][4])

        class R:
            status_code = 200
            content = b""
            headers: dict[str, str] = {}

            def raise_for_status(self) -> None:
                return None

        return R()

    import requests

    monkeypatch.setattr(requests.Session, "get", fake_session_get, raising=True)

    http_utils.safe_http_get("https://example.com/data")

    assert seen_sockaddrs, "fetch step was not exercised"
    fetched_ip = seen_sockaddrs[0][0]
    assert (
        fetched_ip == "93.184.216.34"
    ), f"DNS-rebinding not prevented: fetch resolved to {fetched_ip}"
    # Sanity: the validation step did resolve the hostname at least once.
    # Subsequent resolutions are intercepted by ``pinned_dns`` and therefore
    # never reach the attacker-controlled resolver — that *is* the fix.
    assert resolver.calls[0] == "example.com"


def test_fetch_and_resize_remote_image_pins_across_rebind(monkeypatch):
    """fetch_and_resize_remote_image must not be tricked by a DNS flip."""
    import utils.http_utils as http_utils
    import utils.image_utils as image_utils

    http_utils._reset_shared_session_for_tests()

    resolver = _RebindingResolver(first="93.184.216.34", rebound="127.0.0.1")
    monkeypatch.setattr(socket, "getaddrinfo", resolver)

    observed_ips: list[str] = []

    def fake_http_get(url, **kwargs):
        import urllib.parse as _urlparse

        host = _urlparse.urlparse(url).hostname or ""
        observed_ips.append(socket.getaddrinfo(host, 443)[0][4][0])

        class R:
            status_code = 200
            # Invalid image bytes on purpose — we only care about the resolve.
            content = b""

            def raise_for_status(self) -> None:
                return None

        return R()

    monkeypatch.setattr(image_utils, "http_get", fake_http_get)

    image_utils.fetch_and_resize_remote_image(
        "https://example.com/pic.jpg", (10, 10), timeout_seconds=1.0
    )

    assert observed_ips == ["93.184.216.34"], observed_ips


def test_get_image_pins_across_rebind(monkeypatch):
    """get_image must resolve through the pinned IP even if DNS flips."""
    import utils.http_utils as http_utils
    import utils.image_utils as image_utils

    http_utils._reset_shared_session_for_tests()

    resolver = _RebindingResolver(first="93.184.216.34", rebound="10.0.0.5")
    monkeypatch.setattr(socket, "getaddrinfo", resolver)

    observed_ips: list[str] = []

    def fake_http_get(url, **kwargs):
        import urllib.parse as _urlparse

        host = _urlparse.urlparse(url).hostname or ""
        observed_ips.append(socket.getaddrinfo(host, 80)[0][4][0])

        class R:
            status_code = 500  # short-circuits decode path
            content = b""

        return R()

    monkeypatch.setattr(image_utils, "http_get", fake_http_get)

    image_utils.get_image("http://example.com/img.png")

    assert observed_ips == ["93.184.216.34"], observed_ips


def test_safe_http_get_rejects_private_ip_even_when_first_resolution_is_private(
    monkeypatch,
):
    """If the *first* DNS answer is already private, validation rejects it."""
    from utils import http_utils

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _ainfo("192.168.1.1"))

    try:
        http_utils.safe_http_get("http://evil.example.com/x")
    except ValueError as exc:
        assert "private" in str(exc).lower() or "loopback" in str(exc).lower()
    else:  # pragma: no cover - regression guard
        raise AssertionError("safe_http_get should refuse a private-resolving host")


# ---------------------------------------------------------------------------
# Plugin-level: image_album pins DNS for Immich API calls
# ---------------------------------------------------------------------------


def test_image_album_immich_uses_pinned_ip_across_rebind(monkeypatch):
    """ImageAlbum + Immich must pin DNS for the base URL across the fetch."""
    from unittest.mock import MagicMock

    import utils.http_utils as http_utils

    http_utils._reset_shared_session_for_tests()

    resolver = _RebindingResolver(first="93.184.216.34", rebound="127.0.0.1")
    monkeypatch.setattr(socket, "getaddrinfo", resolver)

    observed_hosts: list[str] = []

    def _resolve_during_call(url: str, **_kwargs) -> MagicMock:
        import urllib.parse as _urlparse

        host = _urlparse.urlparse(url).hostname or ""
        observed_hosts.append(socket.getaddrinfo(host, 443)[0][4][0])
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = []
        return resp

    session = MagicMock()
    session.get = MagicMock(side_effect=_resolve_during_call)
    session.post = MagicMock(side_effect=_resolve_during_call)

    monkeypatch.setattr(
        "plugins.image_album.image_album.get_http_session", lambda: session
    )

    from plugins.image_album.image_album import ImmichProvider
    from utils.security_utils import validate_url_with_ips

    url = "https://immich.example.com"
    _, pinned_ips = validate_url_with_ips(url)

    provider = ImmichProvider(
        url, key="k", image_loader=MagicMock(), pinned_ips=pinned_ips
    )

    # DNS has now flipped to private — the pin must hold.
    try:
        provider.get_album_id("no-such-album")
    except RuntimeError:
        # Expected: empty album list → not found.  We only care about the
        # host that was resolved during the call.
        pass

    assert observed_hosts == ["93.184.216.34"], observed_hosts
