"""Input validation utilities for URL and file-path security."""

import ipaddress
import os
import socket
import urllib.parse

from utils.dns_pinning import idna_hostname

# URLValidationError — and the whitelist of hardcoded validator messages —
# live in ``utils.plugin_errors`` so the subprocess worker and cross-process
# tests can reference the exception type without importing ``security_utils``
# (SonarCloud architecture rule S7788; JTN-776 PR #563). The class is
# re-exported here for backward compatibility with the blueprint and plugin
# call sites that also use the validator functions.
from utils.plugin_errors import (
    URL_ERR_EMPTY as _URL_ERR_EMPTY,
    URL_ERR_LOCALHOST as _URL_ERR_LOCALHOST,
    URL_ERR_NO_HOST as _URL_ERR_NO_HOST,
    URL_ERR_PRIVATE as _URL_ERR_PRIVATE,
    URL_ERR_SCHEME as _URL_ERR_SCHEME,
    URL_ERR_UNRESOLVABLE as _URL_ERR_UNRESOLVABLE,
    URLValidationError,
)

__all__ = [
    "LanAddressError",
    "URLValidationError",
    "is_public_address",
    "validate_url",
    "validate_url_with_ips",
    "validate_file_path",
]


def validate_url(url: str, *, allow_lan: bool = False) -> str:
    """Validate that a URL uses an allowed scheme and does not resolve to a private IP.

    Parameters
    ----------
    url:
        The URL string to validate.
    allow_lan:
        Also accept local-network and Tailscale addresses; see
        :func:`validate_url_with_ips`.

    Returns
    -------
    str
        The original *url* if validation passes.

    Raises
    ------
    ValueError
        If the URL is empty, uses a disallowed scheme, targets localhost,
        or resolves to a private/reserved IP address.
    """
    url_out, _ips = validate_url_with_ips(url, allow_lan=allow_lan)
    return url_out


#: Ranges that :func:`validate_url_with_ips` admits when the caller passes
#: ``allow_lan=True``: RFC 1918 IPv4, RFC 6598 shared address space (carrier
#: NAT, and the addresses Tailscale hands out) and RFC 4193 IPv6
#: unique-local (Tailscale's IPv6 range sits inside it).  Loopback,
#: link-local (cloud metadata), unspecified, reserved and multicast
#: addresses stay blocked even then.
_LAN_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fc00::/7"),
)

#: Ranges Python's ``is_global`` still counts as public that no fetch should
#: reach: the 6to4 relay anycast prefix, deprecated by RFC 7526, forwards to
#: whichever relay is nearest rather than to one known host.
_NOT_PUBLIC_NETWORKS: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("192.88.99.0/24"),
)

#: Global unicast IPv6.  Addresses outside it that ``is_global`` accepts
#: (NAT64 ``64:ff9b::/96``, IPv4-mapped ``::ffff:0:0/96``) can carry a
#: private IPv4 destination.
_IPV6_GLOBAL_UNICAST = ipaddress.IPv6Network("2000::/3")


def is_public_address(
    address: str | ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Return True if *address* is a public unicast address a fetch may reach.

    Shared by the user-URL guard (:func:`validate_url_with_ips`) and the
    remote-rendering proxy (:mod:`utils.remote_rendering`), so both refuse
    the same ranges.  Anything ``ipaddress`` doesn't call global is refused:
    private, shared (``100.64.0.0/10``), loopback, link-local, documentation,
    benchmarking and reserved ranges.  Multicast, the 6to4 relay anycast
    prefix and IPv6 outside ``2000::/3`` or inside the 6to4 and Teredo
    tunnelling prefixes are refused too, because those can stand for a
    private IPv4 destination.
    """
    addr = ipaddress.ip_address(address)
    if not addr.is_global or addr.is_multicast:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        return addr in _IPV6_GLOBAL_UNICAST and not (addr.sixtofour or addr.teredo)
    return not any(addr in network for network in _NOT_PUBLIC_NETWORKS)


def validate_url_with_ips(
    url: str, *, allow_lan: bool = False
) -> tuple[str, tuple[str, ...]]:
    """Validate *url* and return ``(url, resolved_ips)``.

    The returned IP tuple is the exact set of addresses the URL's hostname
    resolved to at validation time.  Callers should pin DNS to these IPs for
    the subsequent HTTP fetch (see :func:`utils.dns_pinning.pinned_dns`) to
    mitigate DNS-rebinding SSRF where an attacker-controlled DNS server flips
    the answer to a private IP between validation and the actual request
    (JTN-656).

    Every resolved address must pass :func:`is_public_address`.  When
    *allow_lan* is true, addresses inside :data:`_LAN_NETWORKS` are accepted
    as well (an explicit per-deployment opt-in for servers on the local
    network or a Tailscale tailnet); every other non-public range is still
    rejected.

    A non-ASCII host name is resolved in the ASCII (IDNA) form that
    ``requests`` connects to, so the returned IPs belong to the same name
    that :func:`utils.dns_pinning.pinned_dns` pins.

    Raises
    ------
    ValueError
        If the URL is empty, uses a disallowed scheme, targets localhost,
        or resolves to a private/reserved IP address.
    """
    if not url:
        raise ValueError(_URL_ERR_EMPTY)

    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(_URL_ERR_SCHEME)

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(_URL_ERR_NO_HOST)

    if hostname.lower() == "localhost":
        raise ValueError(_URL_ERR_LOCALHOST)

    # DNS libraries can raise low-level IDNA/Unicode errors for malformed
    # hostnames (for example a single label over 63 octets). Treat those as
    # ordinary unresolvable hosts so users see one consistent validation error.
    labels = hostname.rstrip(".").split(".")
    if len(hostname) > 253 or any(not label or len(label) > 63 for label in labels):
        raise ValueError(_URL_ERR_UNRESOLVABLE)

    # Reject bare IP addresses that are private/loopback/etc. before DNS
    # The rejection must sit outside the ``try`` — otherwise its ValueError is
    # swallowed and the literal is silently re-checked via getaddrinfo, which
    # a patched or unusual resolver may answer differently.
    try:
        literal: ipaddress.IPv4Address | ipaddress.IPv6Address | None = (
            ipaddress.ip_address(hostname)
        )
    except ValueError:
        # hostname is not a literal IP — fall through to DNS resolution
        literal = None
    if literal is not None:
        _reject_private_ip(literal, allow_lan=allow_lan)
        # Literal IP — no DNS required; the "resolved" set is the literal.
        return url, (hostname,)

    # Resolve hostname and check all resulting IPs
    try:
        addr_infos = socket.getaddrinfo(idna_hostname(hostname), None)
    except (UnicodeError, OSError) as exc:
        raise ValueError(_URL_ERR_UNRESOLVABLE) from exc

    resolved: list[str] = []
    for info in addr_infos:
        ip_str = str(info[4][0])
        addr = ipaddress.ip_address(ip_str)
        _reject_private_ip(addr, allow_lan=allow_lan)
        if ip_str not in resolved:
            resolved.append(ip_str)

    if not resolved:
        raise ValueError(_URL_ERR_UNRESOLVABLE)

    return url, tuple(resolved)


class LanAddressError(ValueError):
    """A URL was rejected only because it resolves to an opt-in LAN range.

    Carries the same message as any other private-address rejection, so
    existing callers and their whitelisted error text are unchanged.
    """


def _is_lan_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if *addr* sits in one of the opt-in :data:`_LAN_NETWORKS`."""
    return any(addr in network for network in _LAN_NETWORKS)


def _reject_private_ip(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    allow_lan: bool = False,
) -> None:
    """Raise ValueError unless *addr* is public (see :func:`is_public_address`).

    With *allow_lan*, :data:`_LAN_NETWORKS` addresses are permitted too.  When
    they are not, the rejection is a :class:`LanAddressError` so callers that
    offer an opt-in can tell "LAN host" apart from loopback/metadata targets.
    """
    if is_public_address(addr):
        return
    if _is_lan_address(addr):
        if allow_lan:
            return
        raise LanAddressError(_URL_ERR_PRIVATE)
    raise ValueError(_URL_ERR_PRIVATE)


def validate_file_path(file_path: str, allowed_directory: str) -> str:
    """Ensure *file_path* resolves to a location inside *allowed_directory*.

    Parameters
    ----------
    file_path:
        The file path to validate.
    allowed_directory:
        The directory the path must reside within.

    Returns
    -------
    str
        The resolved (real) path if it is inside the allowed directory.

    Raises
    ------
    ValueError
        If the resolved path escapes the allowed directory.
    """
    real_path = os.path.realpath(file_path)
    real_allowed = os.path.realpath(allowed_directory)
    try:
        common = os.path.commonpath([real_allowed, real_path])
    except ValueError as exc:
        # On Windows, paths on different drives raise ValueError
        raise ValueError("Path is outside the allowed directory") from exc
    if common != real_allowed:
        raise ValueError("Path is outside the allowed directory")
    return real_path
