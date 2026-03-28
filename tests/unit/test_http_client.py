# pyright: reportMissingImports=false
import threading
from unittest.mock import patch

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
