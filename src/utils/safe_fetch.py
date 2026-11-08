"""SSRF-guarded fetches: per-hop redirect validation, DNS pinning, size caps.

Every hop of a guarded fetch is validated with
:func:`utils.security_utils.validate_url_with_ips` and fetched while DNS is
pinned (:mod:`utils.dns_pinning`) to the vetted IPs; bodies can be streamed
under a byte cap.

Re-exported from :mod:`utils.http_utils`, which remains the public import path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from utils.dns_pinning import pinned_dns
from utils.http_transport import (
    CONNECT_TIMEOUT_SECONDS,
    READ_TIMEOUT_SECONDS,
    _env_bool,
    _resolve_timeout,
    http_get,
)

# ``requests`` is imported lazily (JTN-606); see utils.http_transport.
if TYPE_CHECKING:  # pragma: no cover — type hints only
    import requests

# Keeps the pre-split logger name so log filters and output are unchanged.
logger = logging.getLogger("utils.http_utils")


# ---- Redirect-safe guarded fetch (SSRF mitigation) -------------------------
#
# Validating and pinning only the *first* URL is not enough: a public host
# answering ``302 Location: http://192.168.1.1/`` would otherwise be followed
# by ``requests`` with no further check.  Guarded fetches therefore disable
# automatic redirects and follow them here, re-validating and re-pinning DNS
# for every hop.

#: Maximum number of redirects a guarded fetch will follow.
MAX_GUARDED_REDIRECTS = 5

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

#: Request headers dropped when a redirect leaves the original origin, matching
#: what ``requests`` itself strips: credentials must not follow a redirect to a
#: different host.
_CROSS_ORIGIN_STRIP_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization"}
)


class ResponseTooLargeError(RuntimeError):
    """Raised when a guarded fetch body exceeds its byte cap."""


def _response_header(resp: Any, name: str) -> object:
    """Return header *name* from *resp*, tolerating responses without headers."""
    getter = getattr(getattr(resp, "headers", None), "get", None)
    return getter(name) if callable(getter) else None


def _redirect_target(current_url: str, resp: Any) -> str | None:
    """Return the absolute redirect target for *resp*, or None if not a redirect."""
    status = getattr(resp, "status_code", None)
    if not isinstance(status, int) or status not in _REDIRECT_STATUSES:
        return None
    location = _response_header(resp, "Location")
    if not isinstance(location, str) or not location.strip():
        return None
    import urllib.parse as _urlparse

    # Relative Location headers resolve against the URL that produced them.
    return _urlparse.urljoin(current_url, location.strip())


def _origin(url: str) -> tuple[str, str, int | None]:
    import urllib.parse as _urlparse

    parsed = _urlparse.urlsplit(url)
    return (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)


def _hop_headers(
    headers: dict[str, str], original_url: str, hop_url: str
) -> dict[str, str]:
    """Return *headers* for *hop_url*, minus credentials on a cross-origin hop."""
    if _origin(hop_url) == _origin(original_url):
        return headers
    return {
        k: v for k, v in headers.items() if k.lower() not in _CROSS_ORIGIN_STRIP_HEADERS
    }


def _close_quietly(resp: Any) -> None:
    close = getattr(resp, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def guarded_fetch(
    url: str,
    fetch: Callable[[str], Any],
    *,
    max_redirects: int = MAX_GUARDED_REDIRECTS,
    allow_lan: bool = False,
    first_hop_ips: tuple[str, ...] | None = None,
    follow_redirects: bool = True,
) -> Any:
    """Run *fetch* against *url*, following redirects with per-hop SSRF checks.

    *fetch* receives one validated absolute URL and is called while DNS is
    pinned to the IPs vetted for that URL's hostname.  It must perform a
    single request **without** following redirects (``allow_redirects=False``)
    and return the response.  Every ``Location`` target (relative targets are
    resolved against the current URL) is validated with
    :func:`utils.security_utils.validate_url_with_ips` and pinned before it is
    fetched, so a public host cannot bounce the request to a private address.

    *first_hop_ips* lets callers that already validated *url* reuse the IPs
    they observed instead of resolving the first hop again.  With
    *follow_redirects* false the first response is returned as-is, 3xx
    included.

    Raises ``ValueError`` when any hop fails validation and
    ``requests.TooManyRedirects`` once more than *max_redirects* redirects
    are seen.
    """
    import urllib.parse as _urlparse

    # Local import to avoid a circular dependency during module initialisation.
    from utils.security_utils import validate_url_with_ips

    current = url
    ips = first_hop_ips
    for _hop in range(max_redirects + 1):
        if ips is None:
            current, ips = validate_url_with_ips(current, allow_lan=allow_lan)
        hostname = _urlparse.urlparse(current).hostname or ""
        with pinned_dns(hostname, ips):
            resp = fetch(current)
        target = _redirect_target(current, resp) if follow_redirects else None
        if target is None:
            return resp
        _close_quietly(resp)
        logger.debug("Guarded fetch redirect | from=%s to=%s", current, target)
        current = target
        ips = None

    import requests  # noqa: F811

    raise requests.TooManyRedirects(f"Exceeded {max_redirects} redirects")


def safe_http_get(
    url: str,
    *,
    max_redirects: int = MAX_GUARDED_REDIRECTS,
    allow_lan: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """Validate *url* for SSRF and perform an ``http_get`` with DNS pinned.

    The hostname is resolved once during validation; the resulting IPs are
    pinned for the subsequent fetch so a DNS-rebinding attack cannot flip
    the answer to a private address between the two resolutions (JTN-656).
    Redirects are followed by :func:`guarded_fetch`, so every hop is
    validated and pinned too.  ``allow_redirects=False`` returns the first
    response (a 3xx included) without following it.
    """
    follow = bool(kwargs.pop("allow_redirects", True))
    headers: dict[str, str] = dict(kwargs.pop("headers", None) or {})

    def _fetch(hop_url: str) -> requests.Response:
        return http_get(
            hop_url,
            headers=_hop_headers(headers, url, hop_url) or None,
            allow_redirects=False,
            **kwargs,
        )

    return cast(
        "requests.Response",
        guarded_fetch(
            url,
            _fetch,
            max_redirects=max_redirects,
            allow_lan=allow_lan,
            follow_redirects=follow,
        ),
    )


def read_capped(resp: Any, max_bytes: int, *, chunk_size: int = 65536) -> bytes:
    """Read a streamed response body, raising if it exceeds *max_bytes*.

    A declared ``Content-Length`` above the cap is rejected before any body
    is read; otherwise the body is accumulated chunk by chunk and the read
    stops as soon as the running total passes the cap, so an endless or
    lying server cannot exhaust memory.
    """
    declared = _response_header(resp, "Content-Length")
    if isinstance(declared, (str, int)):
        try:
            declared_len = int(declared)
        except ValueError:
            declared_len = -1
        if declared_len > max_bytes:
            raise ResponseTooLargeError(
                f"Response too large: {declared_len} bytes exceeds {max_bytes}"
            )
    buf = bytearray()
    for chunk in resp.iter_content(chunk_size=chunk_size):
        if not chunk:
            continue
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise ResponseTooLargeError(
                f"Response too large: exceeds {max_bytes} bytes"
            )
    return bytes(buf)


def safe_fetch_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: float | tuple[float, float] | None = None,
    headers: dict[str, str] | None = None,
    allow_lan: bool = False,
    session: Any = None,
    max_redirects: int = MAX_GUARDED_REDIRECTS,
) -> bytes:
    """SSRF-guarded streaming GET of *url* returning at most *max_bytes*.

    Every hop is validated and DNS-pinned (see :func:`guarded_fetch`), the
    body is streamed and capped via :func:`read_capped`, and a non-2xx final
    response raises ``requests.HTTPError`` through ``raise_for_status``.
    Responses are never cached.

    *session* lets plugins keep using the shared plugin session from
    :func:`utils.http_client.get_http_session`; without it :func:`http_get`
    and its session are used.
    """
    from contextlib import closing

    base_headers: dict[str, str] = dict(headers or {})
    effective_timeout = _resolve_timeout(
        timeout, CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS
    )

    def _fetch(hop_url: str) -> Any:
        hop_headers = _hop_headers(base_headers, url, hop_url) or None
        if session is None:
            return http_get(
                hop_url,
                headers=hop_headers,
                timeout=effective_timeout,
                stream=True,
                allow_redirects=False,
                use_cache=False,
            )
        return session.get(
            hop_url,
            headers=hop_headers,
            timeout=effective_timeout,
            stream=True,
            allow_redirects=False,
        )

    resp = guarded_fetch(url, _fetch, max_redirects=max_redirects, allow_lan=allow_lan)
    with closing(resp):
        resp.raise_for_status()
        return read_capped(resp, max_bytes)


def private_feeds_allowed() -> bool:
    """Return True when the deployment opted feeds into LAN targets.

    Controlled by ``INKYPI_ALLOW_PRIVATE_FEEDS`` (see docs/security.md).  Read
    on every call so a restart with an updated environment takes effect
    without code changes.
    """
    from utils.plugin_errors import ALLOW_PRIVATE_FEEDS_ENV

    return _env_bool(ALLOW_PRIVATE_FEEDS_ENV, False)


def fetch_feed_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: float | tuple[float, float] | None = None,
    headers: dict[str, str] | None = None,
    session: Any = None,
) -> bytes:
    """Fetch a user-configured feed (RSS, iCal) through the SSRF guard.

    Wraps :func:`safe_fetch_bytes`; private-network targets are refused
    unless :func:`private_feeds_allowed`.  Validation failures on any hop
    are raised as :class:`utils.plugin_errors.URLValidationError` so the UI
    shows a specific, response-safe reason (including how to opt in when a
    LAN address was the cause) and the refresh loop does not retry.
    """
    from utils.plugin_errors import URL_ERR_PRIVATE_FEED, URLValidationError
    from utils.security_utils import LanAddressError

    allow_lan = private_feeds_allowed()
    try:
        return safe_fetch_bytes(
            url,
            max_bytes=max_bytes,
            timeout=timeout,
            headers=headers,
            allow_lan=allow_lan,
            session=session,
        )
    except URLValidationError:
        raise
    except ValueError as exc:
        import requests  # noqa: F811

        if isinstance(exc, requests.RequestException):
            # ``requests.InvalidURL`` & co. subclass ValueError but are
            # transport errors, not SSRF validation results.
            raise
        # Only a pure LAN-range rejection is fixable by the opt-in; loopback,
        # link-local and similar targets keep the generic message.
        reason = URL_ERR_PRIVATE_FEED if isinstance(exc, LanAddressError) else str(exc)
        raise URLValidationError(f"Invalid URL: {reason}", reason=reason) from exc
