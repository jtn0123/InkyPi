"""HTTP helpers and canonical JSON response envelope (JTN-500).

Canonical JSON envelope
-----------------------
All JSON API routes should return responses built via :func:`json_success` or
:func:`json_error` so clients can rely on a single stable shape.

Success envelope::

    {
        "success": true,
        "message": "<optional human-readable summary>",
        "request_id": "<uuid, when inside a request context>",
        ...payload fields (e.g. "data", "items", "metrics")...
    }

Error envelope::

    {
        "success": false,
        "error": "<human-readable message>",
        "code": "<optional app error code>",
        "details": { ... optional structured detail ... },
        "request_id": "<uuid, when inside a request context>"
    }

Rules of thumb
~~~~~~~~~~~~~~
* Prefer ``json_success(message=..., data=..., meta=...)`` over
  ``jsonify({"success": True, ...})`` so ``request_id`` and future envelope
  fields are added automatically.
* For errors, raise :class:`APIError` or return ``json_error(...)``.  Do not
  return ``jsonify({"success": False, "error": "..."})`` directly — that shape
  skips ``request_id`` and bypasses the central error logging path.
* Pagination envelopes should place page data under ``items`` and cursor
  information under ``next_cursor``/``meta``.
* Pure data read endpoints (e.g. ``/api/version/info``) MAY return a raw JSON
  object without the ``success`` key for backwards compatibility, but any new
  endpoint should use the canonical envelope.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

from flask import Request, g, jsonify, request
from flask.wrappers import Response as FlaskResponse

# ``requests`` / ``urllib3`` are imported lazily (JTN-606) because they add
# ~8 MB of RSS at process startup.  The json_* helpers used by error
# handlers do not need them, so deferring the import to the first
# ``http_get`` / ``get_shared_session`` call keeps the critical path light.
if TYPE_CHECKING:  # pragma: no cover — type hints only
    import requests
    from urllib3.util.retry import Retry

from utils.form_utils import sanitize_response_value

logger = logging.getLogger(__name__)


def _sanitize_details(details: dict[str, Any]) -> dict[str, Any]:
    """Recursively HTML-escape all string leaf values in *details*.

    Non-string scalars (int, bool, float, None) pass through unchanged.
    Nested dicts are traversed recursively.  Lists are sanitized element-wise.
    This is defense-in-depth: any user-derived string reaching the JSON error
    envelope will have angle brackets and ampersands escaped before serialisation.
    """

    def _sanitize(value: Any) -> Any:
        if isinstance(value, str):
            return sanitize_response_value(value)
        if isinstance(value, dict):
            return {k: _sanitize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_sanitize(item) for item in value]
        return value

    return {k: _sanitize(v) for k, v in details.items()}


class APIError(Exception):
    """Typed API error that can be raised within routes to return JSON errors.

    Attributes
    ----------
    message: str
        Human-readable error message
    status: int
        HTTP status code (default 400)
    code: Optional[int | str]
        Optional application-specific error code
    details: Optional[dict[str, Any]]
        Optional structured details to aid clients
    """

    def __init__(
        self,
        message: str,
        status: int = 400,
        code: int | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details


def _get_or_set_request_id() -> str | None:
    """Return a stable per-request id if a request context exists.

    - Prefer an existing value in flask.g
    - Else prefer inbound header 'X-Request-Id'
    - Else generate a new uuid4 and store in flask.g
    - If no request context, return None
    """
    try:
        # Ensure we have a request context
        _ = request  # may raise if outside request context
    except RuntimeError:
        return None
    try:
        rid_existing: str | None = getattr(g, "request_id", None)
        if rid_existing is not None and rid_existing != "":
            return rid_existing
        # Prefer inbound X-Request-Id if provided by client/proxy
        rid_hdr: str | None = request.headers.get("X-Request-Id")
        if rid_hdr is not None and rid_hdr != "":
            g.request_id = rid_hdr
            return rid_hdr
        # Generate
        import uuid

        rid_gen: str = str(uuid.uuid4())
        g.request_id = rid_gen
        return rid_gen
    except RuntimeError:
        return None


def json_error(
    message: str,
    status: int = 400,
    code: int | str | None = None,
    details: dict[str, Any] | None = None,
) -> tuple[FlaskResponse | dict[str, Any], int]:
    payload: dict[str, Any] = {"success": False, "error": message}
    if code is not None:
        payload["code"] = code
    if details is not None:
        payload["details"] = _sanitize_details(details)
    rid = _get_or_set_request_id()
    if rid is not None:
        payload["request_id"] = rid
    try:
        return jsonify(payload), status
    except RuntimeError:
        # Allow utility-level calls outside Flask application/request contexts.
        return payload, status


def json_success(
    message: str | None = None, status: int = 200, **payload: Any
) -> tuple[FlaskResponse | dict[str, Any], int]:
    body: dict[str, Any] = {"success": True}
    if message is not None:
        body["message"] = message
    body.update(payload)
    rid = _get_or_set_request_id()
    if rid is not None:
        body["request_id"] = rid
    try:
        return jsonify(body), status
    except RuntimeError:
        return body, status


def reissue_json_error(
    error_response: tuple[FlaskResponse | dict[str, Any], int],
    fallback_message: str,
) -> tuple[FlaskResponse | dict[str, Any], int]:
    """Rebuild an error response using a server-controlled message.

    This preserves only the HTTP status and never reuses upstream payload
    fields. The returned message is always server-controlled.
    """
    _, status = error_response
    try:
        safe_status = int(status)
    except (TypeError, ValueError):
        safe_status = 400
    if safe_status < 400 or safe_status > 599:
        safe_status = 400
    return json_error(
        fallback_message,
        status=safe_status,
    )


def json_internal_error(
    context: str,
    *,
    status: int = 500,
    code: int | str | None = "internal_error",
    details: dict[str, Any] | None = None,
) -> tuple[FlaskResponse | dict[str, Any], int]:
    """Return a standardized internal error JSON while preserving existing error strings.

    - Keeps top-level error as a generic string for backward compatibility/tests
    - Adds structured details including a required context and optional hint
    """
    ctx: dict[str, Any] = {"context": context}
    if details:
        try:
            ctx.update(details)
        except Exception:
            pass
    return json_error(
        "An internal error occurred", status=status, code=code, details=ctx
    )


def wants_json(req: Request | None = None) -> bool:
    """Heuristic to decide if the current request expects JSON.

    We keep this conservative to avoid affecting HTML routes.
    """
    try:
        r = req or request
        accept_json = (
            r.accept_mimetypes.accept_json and not r.accept_mimetypes.accept_html
        )
        is_api_path = r.path.startswith("/api/")
        has_json = False
        try:
            has_json = bool(r.is_json or r.get_json(silent=True) is not None)
        except Exception:
            has_json = False
        return bool(accept_json or is_api_path or has_json)
    except Exception:
        return False


# ---- HTTP client helpers ----------------------------------------------------

# Use a thread-local container to avoid sharing sessions across threads.
_thread_local = threading.local()

# Conservative defaults that keep tests fast (no backoff sleeps) while providing resiliency


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.getenv(name)
        if raw is None or raw.strip() == "":
            return default
        return float(raw)
    except (ValueError, TypeError):
        logger.warning(
            "Failed to parse env var %s as float, using default %s", name, default
        )
        return default


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.getenv(name)
        if raw is None or raw.strip() == "":
            return default
        return int(raw)
    except (ValueError, TypeError):
        logger.warning(
            "Failed to parse env var %s as int, using default %s", name, default
        )
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    try:
        raw = os.getenv(name, "")
        return raw.strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        logger.warning(
            "Failed to parse env var %s as bool, using default %s", name, default
        )
        return default


DEFAULT_TIMEOUT_SECONDS: float = _env_float("INKYPI_HTTP_TIMEOUT_DEFAULT_S", 20.0)
CONNECT_TIMEOUT_SECONDS: float | None = None
READ_TIMEOUT_SECONDS: float | None = None
try:
    # Optional split timeouts; if either is set, we pass a (connect, read) tuple
    _c = os.getenv("INKYPI_HTTP_CONNECT_TIMEOUT_S")
    _r = os.getenv("INKYPI_HTTP_READ_TIMEOUT_S")
    CONNECT_TIMEOUT_SECONDS = float(_c) if _c and _c.strip() != "" else None
    READ_TIMEOUT_SECONDS = float(_r) if _r and _r.strip() != "" else None
except Exception:
    logger.warning("Failed to parse HTTP split timeout env vars, using defaults")
    CONNECT_TIMEOUT_SECONDS = None
    READ_TIMEOUT_SECONDS = None
HTTP_POOL_CONNECTIONS = 10
HTTP_POOL_MAXSIZE = 10
HTTP_POOL_BLOCK = False
HTTP_STATUS_FORCELIST = (429, 500, 502, 503, 504)
HTTP_ALLOWED_METHODS = ("HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE")
HTTP_DEFAULT_USER_AGENT = "InkyPi/1.0 (+https://github.com/fatihak/InkyPi)"
DEFAULT_HEADERS: dict[str, str] = {"User-Agent": HTTP_DEFAULT_USER_AGENT}


def _build_retry(
    *,
    total: int,
    connect: int | None,
    read: int | None,
    status: int | None,
    backoff_factor: float,
    allowed_methods: tuple[str, ...],
    raise_on_status: bool,
) -> Retry:
    """Build a retry policy without binding it to a specific caller profile."""
    # Retry idempotent methods on common transient failures.  ``urllib3`` is
    # imported lazily to keep it off the startup path (JTN-606).
    from urllib3.util.retry import Retry as _Retry  # noqa: F811

    return _Retry(
        total=total,
        connect=connect,
        read=read,
        status=status,
        backoff_factor=backoff_factor,
        status_forcelist=HTTP_STATUS_FORCELIST,
        allowed_methods=frozenset(allowed_methods),
        raise_on_status=raise_on_status,
    )


def _build_env_retry() -> Retry:
    """Build the default retry policy used by ``http_get``."""
    retries_total = _env_int("INKYPI_HTTP_RETRIES", 3)
    retries_connect = _env_int("INKYPI_HTTP_RETRIES_CONNECT", retries_total)
    retries_read = _env_int("INKYPI_HTTP_RETRIES_READ", retries_total)
    retries_status = _env_int("INKYPI_HTTP_RETRIES_STATUS", retries_total)
    backoff = _env_float("INKYPI_HTTP_BACKOFF", 0.0)  # keep tests snappy by default
    return _build_retry(
        total=retries_total,
        connect=retries_connect,
        read=retries_read,
        status=retries_status,
        backoff_factor=backoff,
        allowed_methods=HTTP_ALLOWED_METHODS,
        raise_on_status=False,
    )


def _build_session(*, headers: dict[str, str], retry: Retry) -> requests.Session:
    # ``requests`` / HTTPAdapter are imported lazily — see module docstring.
    import requests  # noqa: F811
    from requests.adapters import HTTPAdapter  # noqa: F811

    s = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=HTTP_POOL_CONNECTIONS,
        pool_maxsize=HTTP_POOL_MAXSIZE,
        max_retries=retry,
        pool_block=HTTP_POOL_BLOCK,
    )
    s.headers.update(headers)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def get_shared_session() -> requests.Session:
    """Return a requests.Session unique to the current thread."""
    session: requests.Session | None = getattr(_thread_local, "session", None)
    if session is None:
        session = _build_session(headers=DEFAULT_HEADERS, retry=_build_env_retry())
        _thread_local.session = session
    return session


def _resolve_timeout(
    timeout: float | tuple[float, float] | None,
    connect: float | None,
    read: float | None,
) -> float | tuple[float, float]:
    """Return the effective request timeout value.

    If *timeout* is explicitly provided it is used as-is.  Otherwise, if either
    *connect* or *read* split-timeout is configured, a ``(connect, read)`` tuple
    is built using ``DEFAULT_TIMEOUT_SECONDS`` as the fallback for whichever is
    absent.  When neither split timeout is set the module-level default is used.
    """
    if timeout is not None:
        return timeout
    if connect is not None or read is not None:
        ct = connect if connect is not None else DEFAULT_TIMEOUT_SECONDS
        rt = read if read is not None else DEFAULT_TIMEOUT_SECONDS
        return (float(ct), float(rt))
    return DEFAULT_TIMEOUT_SECONDS


def _try_cache_lookup(url: str, params: dict[str, Any] | None) -> Any:
    """Return a cached response for *url* + *params*, or ``None``."""
    try:
        from utils.http_cache import get_cache

        cache = get_cache()
        return cache.get(url, params)
    except Exception:
        return None


def _try_cache_store(
    url: str, resp: Any, params: dict[str, Any] | None, cache_ttl: float | None
) -> None:
    """Silently store *resp* in the HTTP cache."""
    try:
        from utils.http_cache import get_cache

        cache = get_cache()
        cache.put(url, resp, params, ttl=cache_ttl)
    except Exception:
        pass


def _log_latency_on_error(url: str, t0: float, ex: Exception) -> None:
    """Log a warning about a failed HTTP GET with elapsed time."""
    elapsed_ms = int((perf_counter() - t0) * 1000)
    try:
        logger.warning(
            "HTTP GET failed | url=%s elapsed_ms=%s error=%s",
            url,
            elapsed_ms,
            type(ex).__name__,
        )
    except Exception:
        pass


def _log_latency_on_success(url: str, resp: Any, t0: float, stream: bool) -> None:
    """Log an info message about a successful HTTP GET with elapsed time."""
    try:
        elapsed_ms = int((perf_counter() - t0) * 1000)
        logger.info(
            "HTTP GET | url=%s status=%s elapsed_ms=%s bytes=%s",
            url,
            getattr(resp, "status_code", "?"),
            elapsed_ms,
            len(getattr(resp, "content", b"")) if not stream else 0,
        )
    except Exception:
        pass


def http_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | tuple[float, float] | None = None,
    stream: bool = False,
    allow_redirects: bool = True,
    use_cache: bool = True,
    cache_ttl: float | None = None,
) -> requests.Response:
    """Perform a GET using a shared session with retries and sane defaults.

    - Adds a default User-Agent header
    - Applies a default timeout if none is provided
    - Uses a shared requests.Session configured with HTTPAdapter retries
    - SSL verification is enabled by default (do not disable)
    - Supports optional HTTP response caching with TTL

    Args:
        url: URL to request
        params: Query parameters
        headers: Additional headers
        timeout: Request timeout (seconds or tuple)
        stream: Whether to stream the response
        allow_redirects: Whether to follow redirects
        use_cache: Whether to use HTTP cache (default: True)
        cache_ttl: Override cache TTL in seconds (default: from config)

    Returns:
        Response object (may be from cache)
    """
    # Lazy import: see module docstring (JTN-606).  ``requests`` is only
    # loaded when an HTTP call is actually made.
    import requests  # noqa: F811

    # Check cache first (unless streaming or caching disabled)
    if use_cache and not stream:
        cached_response = cast(requests.Response, _try_cache_lookup(url, params))
        if cached_response is not None:
            return cached_response

    session = get_shared_session()
    final_headers = dict(DEFAULT_HEADERS)
    if headers:
        final_headers.update(headers)

    effective_timeout = _resolve_timeout(
        timeout, CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS
    )

    log_latency = _env_bool("INKYPI_HTTP_LOG_LATENCY", False)
    t0 = perf_counter() if log_latency else 0.0
    try:
        resp = session.get(
            url,
            params=params,
            headers=final_headers,
            timeout=effective_timeout,
            stream=stream,
            allow_redirects=allow_redirects,
        )
    except Exception as ex:
        if log_latency:
            _log_latency_on_error(url, t0, ex)
        raise

    if log_latency:
        _log_latency_on_success(url, resp, t0, stream)

    if use_cache and not stream:
        _try_cache_store(url, resp, params, cache_ttl)

    return resp


def _reset_shared_session_for_tests() -> None:
    """Reset the shared session (testing only)."""
    if hasattr(_thread_local, "session"):
        delattr(_thread_local, "session")


# ---- DNS pinning (SSRF mitigation, JTN-656) --------------------------------
#
# ``validate_url`` resolves DNS up-front to reject private targets, but the
# subsequent HTTP call resolves DNS *again* inside ``urllib3``.  A hostile
# authoritative server can flip the second answer to a private IP (DNS
# rebinding) — bypassing the guard entirely.
#
# The countermeasure here is to pin the resolver to the exact IPs observed at
# validation time for the duration of the fetch.  We do this by monkey-patching
# ``socket.getaddrinfo`` with a thin wrapper keyed on hostname.  The URL
# itself is unchanged, so TLS SNI and certificate verification still happen
# against the original hostname (we are *not* rewriting the URL host to an
# IP, which would break HTTPS vhost routing and cert matching).
#
# The swap is bounded by a context manager: on entry we stash the currently
# installed ``socket.getaddrinfo`` and replace it with our wrapper; on exit
# we restore exactly what we stashed.  This nests cleanly and plays well
# with test monkeypatches of ``socket.getaddrinfo`` that are set either
# before or after the pin is established.
#
# Concurrency note: ``socket.getaddrinfo`` is a module-level attribute, so
# replacing it affects every thread.  We serialise entry/exit through a
# lock and use a re-entrant pin store so only threads that have actually
# called ``pinned_dns`` see rewritten results.  Other threads' lookups pass
# through unchanged.

_dns_pin_global_lock = threading.Lock()
_dns_pin_depth: int = 0
_dns_pin_saved: Any = None
_dns_pin_local = threading.local()


def _pin_store() -> dict[str, tuple[str, ...]]:
    store: dict[str, tuple[str, ...]] | None = getattr(_dns_pin_local, "pins", None)
    if store is None:
        store = {}
        _dns_pin_local.pins = store
    return store


def _normalize_host(host: Any) -> str | None:
    """Return *host* as a lowercase string, or None if not a decodable host."""
    if isinstance(host, (bytes, bytearray)):
        try:
            host_str: Any = host.decode("idna")
        except Exception:
            host_str = host.decode("ascii", errors="replace")
    else:
        host_str = host
    return host_str.lower() if isinstance(host_str, str) else None


def _coerce_port(port: Any) -> int:
    """Best-effort conversion of *port* to an int; returns 0 on failure."""
    if port is None or port == "":
        return 0
    try:
        return int(port)
    except (TypeError, ValueError):
        return 0


def _addrinfo_for_pinned_ip(ip: str, port_int: int) -> tuple[Any, ...] | None:
    """Build an addrinfo tuple for *ip*, or None if *ip* is not parseable."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address):
        family = socket.AF_INET6
        sockaddr: tuple[Any, ...] = (ip, port_int, 0, 0)
    else:
        family = socket.AF_INET
        sockaddr = (ip, port_int)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


def _make_patched_getaddrinfo(original: Any) -> Any:
    """Return a getaddrinfo wrapper that consults the thread-local pin store.

    *original* is the resolver to delegate to for unpinned hostnames (or
    when the calling thread has no active pins).
    """

    def _patched_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        pins = _pin_store()
        key = _normalize_host(host) if pins else None
        ips = pins.get(key) if key else None
        if not ips:
            return original(host, port, *args, **kwargs)
        port_int = _coerce_port(port)
        results: list[Any] = [
            info
            for info in (_addrinfo_for_pinned_ip(ip, port_int) for ip in ips)
            if info is not None
        ]
        if not results:
            # Shouldn't happen (we vet IPs before pinning) — fall back.
            return original(host, port, *args, **kwargs)
        return results

    return _patched_getaddrinfo


@contextmanager
def pinned_dns(hostname: str, ips: tuple[str, ...] | list[str]) -> Iterator[None]:
    """Context manager that pins ``socket.getaddrinfo(hostname, ...)`` to *ips*.

    Only threads that entered ``pinned_dns`` see rewritten results; other
    threads fall through to the underlying resolver.  Intended to bracket
    an HTTP request whose hostname was already validated via
    :func:`utils.security_utils.validate_url_with_ips`.
    """
    global _dns_pin_depth, _dns_pin_saved

    if not hostname:
        yield
        return

    key = hostname.lower()
    store = _pin_store()
    previous_pin = store.get(key)
    store[key] = tuple(ips)

    # Install the wrapper on first entry across all threads; subsequent
    # nested ``pinned_dns`` calls just bump the depth.
    installed_here = False
    with _dns_pin_global_lock:
        if _dns_pin_depth == 0:
            _dns_pin_saved = socket.getaddrinfo
            socket.getaddrinfo = _make_patched_getaddrinfo(_dns_pin_saved)
            installed_here = True
        _dns_pin_depth += 1

    try:
        yield
    finally:
        with _dns_pin_global_lock:
            _dns_pin_depth -= 1
            if _dns_pin_depth == 0 and installed_here:
                socket.getaddrinfo = _dns_pin_saved
                _dns_pin_saved = None
        if previous_pin is None:
            store.pop(key, None)
        else:
            store[key] = previous_pin


def safe_http_get(url: str, **kwargs: Any) -> requests.Response:
    """Validate *url* for SSRF and perform an ``http_get`` with DNS pinned.

    The hostname is resolved once during validation; the resulting IPs are
    pinned for the subsequent fetch so a DNS-rebinding attack cannot flip
    the answer to a private address between the two resolutions (JTN-656).
    """
    # Local import to avoid a circular dependency during module initialisation.
    from utils.security_utils import validate_url_with_ips

    validated_url, ips = validate_url_with_ips(url)
    import urllib.parse as _urlparse

    hostname = _urlparse.urlparse(validated_url).hostname or ""
    with pinned_dns(hostname, ips):
        return http_get(validated_url, **kwargs)
