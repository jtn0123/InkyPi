# pyright: reportMissingImports=false
import threading

import pytest
import requests

import utils.http_client as http_client_mod
from utils.http_client import close_http_session, get_http_session


@pytest.fixture(autouse=True)
def reset_http_session():
    """Ensure the module-level singleton is None before each test."""
    http_client_mod._HTTP_SESSION = None
    yield
    http_client_mod._HTTP_SESSION = None


def test_get_http_session_returns_session():
    session = get_http_session()
    assert isinstance(session, requests.Session)


def test_get_http_session_singleton():
    session1 = get_http_session()
    session2 = get_http_session()
    assert session1 is session2


def test_session_has_user_agent():
    session = get_http_session()
    assert "InkyPi/1.0" in session.headers.get("User-Agent", "")


def test_session_has_retry_strategy():
    session = get_http_session()
    # Both http:// and https:// should be mounted with our custom adapter
    http_adapter = session.get_adapter("http://example.com")
    https_adapter = session.get_adapter("https://example.com")
    assert isinstance(http_adapter, requests.adapters.HTTPAdapter)
    assert isinstance(https_adapter, requests.adapters.HTTPAdapter)
    # Verify the retry strategy is set on the adapter
    assert http_adapter.max_retries.total == 3
    assert https_adapter.max_retries.total == 3


def test_close_http_session():
    session1 = get_http_session()
    assert http_client_mod._HTTP_SESSION is not None

    close_http_session()
    assert http_client_mod._HTTP_SESSION is None

    # Next call should create a brand-new instance
    session2 = get_http_session()
    assert isinstance(session2, requests.Session)
    assert session2 is not session1


def test_thread_safety():
    results = []

    def fetch():
        results.append(get_http_session())

    t1 = threading.Thread(target=fetch)
    t2 = threading.Thread(target=fetch)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2
    assert results[0] is results[1]


# ---- Additional edge-case tests ----


def test_close_when_none():
    """Close with no session initialized → no crash."""
    assert http_client_mod._HTTP_SESSION is None
    close_http_session()  # should not raise
    assert http_client_mod._HTTP_SESSION is None


def test_close_idempotent():
    """Close twice → second is no-op, no crash."""
    get_http_session()
    close_http_session()
    assert http_client_mod._HTTP_SESSION is None
    close_http_session()  # second close
    assert http_client_mod._HTTP_SESSION is None


def test_concurrent_init_same_instance():
    """10 threads calling get_http_session all get the same object."""
    results = []

    def fetch():
        results.append(get_http_session())

    threads = [threading.Thread(target=fetch) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    assert all(r is results[0] for r in results)


def test_retry_adapter_pool_config():
    """Adapter has pool_connections=10 and pool_maxsize=10."""
    session = get_http_session()
    adapter = session.get_adapter("https://example.com")
    assert adapter._pool_connections == 10
    assert adapter._pool_maxsize == 10


def test_retry_allowed_methods():
    """Only GET, HEAD, OPTIONS are retried (not POST)."""
    session = get_http_session()
    adapter = session.get_adapter("https://example.com")
    allowed = adapter.max_retries.allowed_methods
    assert "GET" in allowed
    assert "HEAD" in allowed
    assert "OPTIONS" in allowed
    assert "POST" not in allowed


def test_atexit_registered():
    """atexit.register is called with close_http_session during init."""
    import atexit
    from unittest.mock import patch as _patch

    with _patch.object(atexit, "register") as mock_register:
        # Force re-initialization
        http_client_mod._HTTP_SESSION = None
        get_http_session()
        # atexit.register should have been called with close_http_session
        mock_register.assert_called_with(close_http_session)
