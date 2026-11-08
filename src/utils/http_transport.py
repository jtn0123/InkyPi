"""Outbound HTTP GET helper with a per-thread pooled session.

:func:`http_get` wraps a thread-local ``requests.Session`` configured with
retries, default headers, split timeouts from the environment, optional
latency logging and the response cache in :mod:`utils.http_cache`.

Re-exported from :mod:`utils.http_utils`, which remains the public import path.
"""

from __future__ import annotations

import logging
import os
import threading
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

# ``requests`` / ``urllib3`` are imported lazily (JTN-606) because they add
# ~8 MB of RSS at process startup.  The json_* helpers used by error
# handlers do not need them, so deferring the import to the first
# ``http_get`` / ``get_shared_session`` call keeps the critical path light.
if TYPE_CHECKING:  # pragma: no cover — type hints only
    import requests
    from urllib3.util.retry import Retry

# Keeps the pre-split logger name so log filters and output are unchanged.
logger = logging.getLogger("utils.http_utils")


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
    # Pooling/retry adapter for plain-HTTP URLs (user-configured feeds, LAN
    # devices). This does not downgrade anything: callers choose the scheme and
    # remote fetches go through the SSRF guard in utils.safe_fetch.
    s.mount("http://", adapter)  # NOSONAR python:S5332
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
