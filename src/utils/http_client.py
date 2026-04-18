"""
HTTP Client with Connection Pooling for InkyPi

Provides a shared requests.Session() instance for all plugins to use.
The session wiring is shared with ``utils.http_utils`` so pooling, retries,
and default headers stay aligned across the two public HTTP entry points.

Usage:
    from utils.http_client import get_http_session

    session = get_http_session()
    response = session.get(url)
"""

import atexit
import logging
import threading

import requests

from utils.http_utils import DEFAULT_HEADERS, _build_retry, _build_session

logger = logging.getLogger(__name__)

_PLUGIN_RETRY_TOTAL = 3
_PLUGIN_RETRY_BACKOFF = 0.5
_PLUGIN_RETRY_ALLOWED_METHODS = ("GET", "HEAD", "OPTIONS")

# Global session instance (singleton)
_HTTP_SESSION: requests.Session | None = None
_HTTP_SESSION_LOCK = threading.Lock()


def get_http_session() -> requests.Session:
    """
    Get the shared HTTP session instance.
    Creates it on first call (lazy initialization).

    Returns:
        requests.Session: Shared session with connection pooling
    """
    global _HTTP_SESSION

    with _HTTP_SESSION_LOCK:
        if _HTTP_SESSION is None:
            logger.debug("Initializing shared HTTP session with connection pooling")
            _HTTP_SESSION = _build_session(
                headers=DEFAULT_HEADERS,
                retry=_build_retry(
                    total=_PLUGIN_RETRY_TOTAL,
                    connect=None,
                    read=None,
                    status=None,
                    backoff_factor=_PLUGIN_RETRY_BACKOFF,
                    allowed_methods=_PLUGIN_RETRY_ALLOWED_METHODS,
                    raise_on_status=True,
                ),
            )

            atexit.register(close_http_session)
            logger.debug("HTTP session initialized successfully")

    return _HTTP_SESSION


def close_http_session() -> None:
    """
    Close the shared HTTP session.
    Should be called on application shutdown.
    """
    global _HTTP_SESSION

    with _HTTP_SESSION_LOCK:
        if _HTTP_SESSION is not None:
            logger.debug("Closing shared HTTP session")
            _HTTP_SESSION.close()
            _HTTP_SESSION = None


def reset_for_tests() -> None:
    """Reset the shared HTTP session (testing only).

    Closes any open session and clears the singleton so the next call to
    ``get_http_session()`` creates a fresh instance.  Call this from a
    pytest fixture to prevent session state from leaking between tests.
    """
    global _HTTP_SESSION

    with _HTTP_SESSION_LOCK:
        if _HTTP_SESSION is not None:
            try:
                _HTTP_SESSION.close()
            except Exception:
                pass
            _HTTP_SESSION = None
