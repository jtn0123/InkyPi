"""Public import path for the HTTP helpers.

The implementation lives in focused modules; this module re-exports every
name it defined before the split, so ``from utils.http_utils import ...``
keeps working for plugins and blueprints:

* :mod:`utils.api_responses` — canonical JSON envelope (``json_success``,
  ``json_error``, ``APIError``, ``wants_json``, ``content_disposition``).
* :mod:`utils.http_transport` — ``http_get`` and the per-thread pooled
  session (retries, timeouts, cache, latency logging).
* :mod:`utils.dns_pinning` — ``pinned_dns`` (SSRF DNS-rebinding guard).
* :mod:`utils.safe_fetch` — SSRF-guarded fetches (``guarded_fetch``,
  ``safe_http_get``, ``safe_fetch_bytes``, ``fetch_feed_bytes``,
  ``read_capped``).

Patching note: monkeypatching a name here does not affect code in those
modules, which looks names up in its own globals. Patch the defining module.

``requests`` / ``urllib3`` stay off the import path (JTN-606): none of the
modules above import them at module level.
"""

from __future__ import annotations

import logging
from typing import Any

from utils import dns_pinning as _dns_pinning
from utils.api_responses import (
    _REQUEST_ID_RE,
    APIError,
    JsonResponse,
    _get_or_set_request_id,
    _sanitize_details,
    content_disposition,
    json_error,
    json_internal_error,
    json_success,
    reissue_json_error,
    wants_json,
)
from utils.dns_pinning import (
    _addrinfo_for_pinned_ip,
    _coerce_port,
    _dns_pin_global_lock,
    _dns_pin_local,
    _make_patched_getaddrinfo,
    _normalize_host,
    _pin_store,
    pinned_dns,
)
from utils.http_transport import (
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT_SECONDS,
    HTTP_ALLOWED_METHODS,
    HTTP_DEFAULT_USER_AGENT,
    HTTP_POOL_BLOCK,
    HTTP_POOL_CONNECTIONS,
    HTTP_POOL_MAXSIZE,
    HTTP_STATUS_FORCELIST,
    READ_TIMEOUT_SECONDS,
    _build_env_retry,
    _build_retry,
    _build_session,
    _c,
    _env_bool,
    _env_float,
    _env_int,
    _log_latency_on_error,
    _log_latency_on_success,
    _r,
    _reset_shared_session_for_tests,
    _resolve_timeout,
    _thread_local,
    _try_cache_lookup,
    _try_cache_store,
    get_shared_session,
    http_get,
)
from utils.safe_fetch import (
    _CROSS_ORIGIN_STRIP_HEADERS,
    _REDIRECT_STATUSES,
    MAX_GUARDED_REDIRECTS,
    ResponseTooLargeError,
    _close_quietly,
    _hop_headers,
    _origin,
    _redirect_target,
    _response_header,
    fetch_feed_bytes,
    guarded_fetch,
    private_feeds_allowed,
    read_capped,
    safe_fetch_bytes,
    safe_http_get,
)

logger = logging.getLogger(__name__)

#: Module globals that ``pinned_dns`` rebinds at runtime. A static re-export
#: would freeze their import-time values, so reads are forwarded live.
_LIVE_DNS_PIN_STATE = frozenset({"_dns_pin_depth", "_dns_pin_saved"})


def __getattr__(name: str) -> Any:
    if name in _LIVE_DNS_PIN_STATE:
        return getattr(_dns_pinning, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # utils.api_responses
    "APIError",
    "JsonResponse",
    "_REQUEST_ID_RE",
    "_get_or_set_request_id",
    "_sanitize_details",
    "content_disposition",
    "json_error",
    "json_internal_error",
    "json_success",
    "reissue_json_error",
    "wants_json",
    # utils.http_transport
    "CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_HEADERS",
    "DEFAULT_TIMEOUT_SECONDS",
    "HTTP_ALLOWED_METHODS",
    "HTTP_DEFAULT_USER_AGENT",
    "HTTP_POOL_BLOCK",
    "HTTP_POOL_CONNECTIONS",
    "HTTP_POOL_MAXSIZE",
    "HTTP_STATUS_FORCELIST",
    "READ_TIMEOUT_SECONDS",
    "_build_env_retry",
    "_build_retry",
    "_build_session",
    "_c",
    "_env_bool",
    "_env_float",
    "_env_int",
    "_log_latency_on_error",
    "_log_latency_on_success",
    "_r",
    "_reset_shared_session_for_tests",
    "_resolve_timeout",
    "_thread_local",
    "_try_cache_lookup",
    "_try_cache_store",
    "get_shared_session",
    "http_get",
    # utils.dns_pinning
    "_addrinfo_for_pinned_ip",
    "_coerce_port",
    "_dns_pin_global_lock",
    "_dns_pin_local",
    "_make_patched_getaddrinfo",
    "_normalize_host",
    "_pin_store",
    "pinned_dns",
    # utils.safe_fetch
    "MAX_GUARDED_REDIRECTS",
    "ResponseTooLargeError",
    "_CROSS_ORIGIN_STRIP_HEADERS",
    "_REDIRECT_STATUSES",
    "_close_quietly",
    "_hop_headers",
    "_origin",
    "_redirect_target",
    "_response_header",
    "fetch_feed_bytes",
    "guarded_fetch",
    "private_feeds_allowed",
    "read_capped",
    "safe_fetch_bytes",
    "safe_http_get",
    # this module
    "logger",
]
