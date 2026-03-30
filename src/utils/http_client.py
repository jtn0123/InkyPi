"""
HTTP Client with Connection Pooling for InkyPi

Provides a shared requests.Session() instance for all plugins to use.
Benefits:
- Connection reuse (20-30% faster requests)
- Reduced TCP handshake overhead
- Automatic keep-alive handling
- Consistent headers across all requests

Usage:
    from utils.http_client import get_http_session

    session = get_http_session()
    response = session.get(url)
"""

import atexit
import logging
import threading

import requests
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

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
            _HTTP_SESSION = requests.Session()

            # Set common headers for all InkyPi requests
            _HTTP_SESSION.headers.update(
                {"User-Agent": "InkyPi/1.0 (https://github.com/fatihak/InkyPi/)"}
            )

            # Configure connection pool with retries for transient network and 5xx/429 responses.
            retry_strategy = Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
            )
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=10,
                pool_maxsize=10,
                max_retries=retry_strategy,
                pool_block=False,
            )
            _HTTP_SESSION.mount("http://", adapter)
            _HTTP_SESSION.mount("https://", adapter)

            atexit.register(close_http_session)
            logger.debug("HTTP session initialized successfully")

    return _HTTP_SESSION


def close_http_session():
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
