"""Input validation utilities for URL and file-path security."""

import ipaddress
import os
import socket
import urllib.parse


def validate_url(url: str) -> str:
    """Validate that a URL uses an allowed scheme and does not resolve to a private IP.

    Parameters
    ----------
    url:
        The URL string to validate.

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
    if not url:
        raise ValueError("URL must not be empty")

    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL scheme must be http or https")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a hostname")

    if hostname.lower() == "localhost":
        raise ValueError("URL must not target localhost")

    # Reject bare IP addresses that are private/loopback/etc. before DNS
    try:
        addr = ipaddress.ip_address(hostname)
        _reject_private_ip(addr, hostname)
    except ValueError:
        # hostname is not a literal IP — fall through to DNS resolution
        pass

    # Resolve hostname and check all resulting IPs
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError("Cannot resolve hostname") from exc

    for info in addr_infos:
        ip_str = info[4][0]
        addr = ipaddress.ip_address(ip_str)
        _reject_private_ip(addr, hostname)

    return url


def _reject_private_ip(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address, hostname: str
) -> None:
    """Raise ValueError if *addr* is private, loopback, link-local, reserved, or multicast."""
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    ):
        raise ValueError(
            "URL must not resolve to a private, loopback, link-local, reserved, or multicast address"
        )


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
