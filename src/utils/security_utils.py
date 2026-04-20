"""Input validation utilities for URL and file-path security."""

import ipaddress
import os
import socket
import urllib.parse

from utils.plugin_errors import PermanentPluginError

# Canonical validator messages. Keeping these as module constants gives us an
# explicit whitelist that :meth:`URLValidationError.safe_message` can check
# against before any validator text reaches an HTTP response body — this is
# what lets the blueprint return a specific error reason without tripping
# CodeQL's ``py/stack-trace-exposure`` rule (JTN-776).
_URL_ERR_EMPTY = "URL must not be empty"
_URL_ERR_SCHEME = "URL scheme must be http or https"
_URL_ERR_NO_HOST = "URL must include a hostname"
_URL_ERR_LOCALHOST = "URL must not target localhost"
_URL_ERR_UNRESOLVABLE = "Cannot resolve hostname"
_URL_ERR_PRIVATE = (
    "URL must not resolve to a private, loopback, link-local, "
    "reserved, or multicast address"
)
_URL_VALIDATOR_MESSAGES: frozenset[str] = frozenset(
    {
        _URL_ERR_EMPTY,
        _URL_ERR_SCHEME,
        _URL_ERR_NO_HOST,
        _URL_ERR_LOCALHOST,
        _URL_ERR_UNRESOLVABLE,
        _URL_ERR_PRIVATE,
    }
)
_URL_ERR_GENERIC = "URL failed validation"


class URLValidationError(PermanentPluginError):
    """Raised by plugins when a user-supplied URL fails SSRF/scheme validation.

    Subclasses :class:`PermanentPluginError` (itself a :class:`RuntimeError`)
    so the refresh-task retry loop skips extra attempts (JTN-778) and
    existing ``except RuntimeError`` blocks in plugin code keep working.
    The plugin blueprint catches this subclass specifically to return HTTP
    4xx with the validator message instead of a generic 500 (JTN-776).

    Callers returning this error to an HTTP client MUST use
    :meth:`safe_message` rather than ``str(self)`` — the former looks the
    reason up in a whitelist of known hardcoded validator strings, breaking
    any accidental information-exposure taint flow.
    """

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        # ``reason`` is the raw validator string from :func:`validate_url`.
        # When the plugin wraps ``ValueError`` the message is "Invalid URL: X"
        # where X is from :data:`_URL_VALIDATOR_MESSAGES`; callers can pass
        # the validator text directly via ``reason`` to avoid string parsing.
        self.reason = reason if reason is not None else _extract_reason(message)

    def safe_message(self) -> str:
        """Return a response-safe description of the validation failure.

        The returned string is always one of two things:

        * ``"Invalid URL: <validator text>"`` where ``<validator text>`` is a
          member of :data:`_URL_VALIDATOR_MESSAGES` (an immutable set of
          hardcoded strings in this module), or
        * ``"Invalid URL: URL failed validation"`` as a fallback.

        Because the output is selected from a constant set rather than derived
        from the exception instance, this satisfies CodeQL's
        ``py/stack-trace-exposure`` rule.
        """
        if self.reason in _URL_VALIDATOR_MESSAGES:
            return f"Invalid URL: {self.reason}"
        return f"Invalid URL: {_URL_ERR_GENERIC}"


def _extract_reason(message: str) -> str:
    """Extract the validator text from a wrapped "Invalid URL: X" message."""
    prefix = "Invalid URL: "
    if message.startswith(prefix):
        return message[len(prefix) :]
    return message


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
    url_out, _ips = validate_url_with_ips(url)
    return url_out


def validate_url_with_ips(url: str) -> tuple[str, tuple[str, ...]]:
    """Validate *url* and return ``(url, resolved_ips)``.

    The returned IP tuple is the exact set of addresses the URL's hostname
    resolved to at validation time.  Callers should pin DNS to these IPs for
    the subsequent HTTP fetch (see :func:`utils.http_utils.pinned_dns`) to
    mitigate DNS-rebinding SSRF where an attacker-controlled DNS server flips
    the answer to a private IP between validation and the actual request
    (JTN-656).

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

    # Reject bare IP addresses that are private/loopback/etc. before DNS
    try:
        addr = ipaddress.ip_address(hostname)
        _reject_private_ip(addr, hostname)
        # Literal IP — no DNS required; the "resolved" set is the literal.
        return url, (hostname,)
    except ValueError:
        # hostname is not a literal IP — fall through to DNS resolution
        pass

    # Resolve hostname and check all resulting IPs
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(_URL_ERR_UNRESOLVABLE) from exc

    resolved: list[str] = []
    for info in addr_infos:
        ip_str = str(info[4][0])
        addr = ipaddress.ip_address(ip_str)
        _reject_private_ip(addr, hostname)
        if ip_str not in resolved:
            resolved.append(ip_str)

    if not resolved:
        raise ValueError(_URL_ERR_UNRESOLVABLE)

    return url, tuple(resolved)


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
