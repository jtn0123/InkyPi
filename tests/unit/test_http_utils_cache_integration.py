"""Tests for HTTP cache integration with http_utils."""

import time

import pytest
import requests_mock

from utils.http_utils import http_get, _reset_shared_session_for_tests
from utils.http_cache import get_cache, _reset_cache_for_tests


@pytest.fixture(autouse=True)
def reset_cache_and_session():
    """Reset cache and session before each test."""
    _reset_cache_for_tests()
    _reset_shared_session_for_tests()
    yield
    _reset_cache_for_tests()
    _reset_shared_session_for_tests()


def test_http_get_uses_cache():
    """Test that http_get uses cache for repeated requests."""
    with requests_mock.Mocker() as m:
        url = "https://api.example.com/data"
        m.get(url, text="response data", status_code=200)

        # First request - cache miss
        resp1 = http_get(url)
        assert resp1.text == "response data"

        # Check that request was made
        assert m.call_count == 1

        # Second request - should hit cache
        resp2 = http_get(url)
        assert resp2.text == "response data"

        # Should not have made another HTTP request
        assert m.call_count == 1

        # Verify cache stats
        cache = get_cache()
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1


def test_http_get_cache_respects_params():
    """Test that cache keys include query parameters."""
    with requests_mock.Mocker() as m:
        url = "https://api.example.com/search"

        m.get(url, text="result1")

        # Request with params1
        resp1 = http_get(url, params={"q": "python"})
        assert m.call_count == 1

        # Request with same params - should hit cache
        resp2 = http_get(url, params={"q": "python"})
        assert m.call_count == 1

        # Request with different params - should miss cache
        resp3 = http_get(url, params={"q": "rust"})
        assert m.call_count == 2


def test_http_get_cache_bypass():
    """Test that cache can be bypassed with use_cache=False."""
    with requests_mock.Mocker() as m:
        url = "https://api.example.com/fresh"
        m.get(url, text="data")

        # First request with cache
        resp1 = http_get(url, use_cache=True)
        assert m.call_count == 1

        # Second request bypassing cache
        resp2 = http_get(url, use_cache=False)
        assert m.call_count == 2  # Should make a new request

        # Third request with cache - should still hit cache from first request
        resp3 = http_get(url, use_cache=True)
        assert m.call_count == 2  # No new request


def test_http_get_custom_cache_ttl():
    """Test that custom cache TTL is respected."""
    with requests_mock.Mocker() as m:
        url = "https://api.example.com/ttl"
        m.get(url, text="data")

        # Request with short TTL
        resp1 = http_get(url, cache_ttl=0.1)
        assert m.call_count == 1

        # Immediate second request - should hit cache
        resp2 = http_get(url)
        assert m.call_count == 1

        # Wait for TTL expiration
        time.sleep(0.15)

        # Third request - cache expired, should make new request
        resp3 = http_get(url)
        assert m.call_count == 2


def test_http_get_streaming_bypasses_cache():
    """Test that streaming requests bypass cache."""
    with requests_mock.Mocker() as m:
        url = "https://api.example.com/stream"
        m.get(url, text="streaming data")

        # Streaming request
        resp1 = http_get(url, stream=True)
        assert m.call_count == 1

        # Second streaming request - should not use cache
        resp2 = http_get(url, stream=True)
        assert m.call_count == 2

        # Verify cache is empty
        cache = get_cache()
        stats = cache.get_stats()
        assert stats["size"] == 0


def test_http_get_caches_successful_responses_only():
    """Test that only successful responses are cached."""
    with requests_mock.Mocker() as m:
        url = "https://api.example.com/maybe"

        # First call returns 404
        m.get(url, status_code=404, text="not found")
        resp1 = http_get(url)
        assert resp1.status_code == 404

        # Second call (mock changes response)
        m.get(url, status_code=200, text="found")
        resp2 = http_get(url)
        assert resp2.status_code == 200

        # Should have made 2 requests (404 not cached)
        assert m.call_count == 2


def test_http_get_cache_control_headers():
    """Test that Cache-Control headers affect caching."""
    with requests_mock.Mocker() as m:
        # Response with max-age
        url1 = "https://api.example.com/maxage"
        m.get(
            url1,
            text="cacheable",
            headers={"Cache-Control": "max-age=3600"},
        )

        resp1 = http_get(url1)
        cache = get_cache()
        cache_key = cache._make_cache_key(url1)
        entry = cache._cache[cache_key]
        assert entry.ttl_seconds == 3600.0

        # Response with no-cache
        url2 = "https://api.example.com/nocache"
        m.get(
            url2,
            text="dont cache",
            headers={"Cache-Control": "no-cache"},
        )

        resp2 = http_get(url2)
        cache_key2 = cache._make_cache_key(url2)
        assert cache_key2 not in cache._cache  # Should not be cached


def test_http_get_cache_errors_dont_break_requests():
    """Test that cache errors don't prevent HTTP requests."""
    with requests_mock.Mocker() as m:
        url = "https://api.example.com/resilient"
        m.get(url, text="data")

        # Temporarily break cache by making it raise errors
        cache = get_cache()
        original_get = cache.get

        def broken_get(*args, **kwargs):
            raise RuntimeError("Cache broken")

        cache.get = broken_get

        # Request should still work despite cache error
        resp = http_get(url)
        assert resp.text == "data"
        assert m.call_count == 1

        # Restore cache
        cache.get = original_get


def test_http_get_cache_stats_integration():
    """Test that cache statistics work with http_get."""
    with requests_mock.Mocker() as m:
        url = "https://api.example.com/stats"
        m.get(url, text="data")

        # Initial stats
        cache = get_cache()
        initial_stats = cache.get_stats()
        initial_misses = initial_stats["misses"]
        initial_hits = initial_stats["hits"]

        # Make requests
        http_get(url)  # Miss
        http_get(url)  # Hit
        http_get(url)  # Hit

        # Check updated stats
        stats = cache.get_stats()
        assert stats["misses"] == initial_misses + 1
        assert stats["hits"] == initial_hits + 2
        assert stats["size"] >= 1


def test_http_get_concurrent_requests_cache_safe():
    """Test that concurrent requests handle cache safely."""
    import threading

    with requests_mock.Mocker() as m:
        url = "https://api.example.com/concurrent"
        m.get(url, text="shared data")

        errors = []

        def make_requests():
            try:
                for _ in range(5):
                    resp = http_get(url)
                    assert resp.text == "shared data"
            except Exception as e:
                errors.append(e)

        # Make concurrent requests
        threads = [threading.Thread(target=make_requests) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # No errors should occur
        assert len(errors) == 0

        # First request should miss, rest should hit
        cache = get_cache()
        stats = cache.get_stats()
        # At least one miss and multiple hits
        assert stats["misses"] >= 1
        assert stats["hits"] >= 1


def test_http_get_cache_with_env_disabled(monkeypatch):
    """Test that caching can be disabled via environment variable."""
    # Disable cache via environment
    monkeypatch.setenv("INKYPI_HTTP_CACHE_ENABLED", "false")

    # Reset to pick up new env
    _reset_cache_for_tests()

    with requests_mock.Mocker() as m:
        url = "https://api.example.com/env_disabled"
        m.get(url, text="data")

        # Make two requests
        http_get(url)
        http_get(url)

        # Both should hit the server (cache disabled)
        assert m.call_count == 2


def test_http_get_real_world_weather_api_pattern():
    """Test cache behavior with a realistic weather API pattern."""
    with requests_mock.Mocker() as m:
        weather_url = "https://api.openweathermap.org/data/3.0/onecall"

        # Mock weather response with Cache-Control
        m.get(
            weather_url,
            json={"temp": 72, "conditions": "sunny"},
            headers={"Cache-Control": "max-age=600"},  # 10 minutes
        )

        # First request with params
        params = {"lat": "40.7", "lon": "-74.0", "appid": "test"}
        resp1 = http_get(weather_url, params=params)
        assert resp1.json()["temp"] == 72
        assert m.call_count == 1

        # Second request with same params - should hit cache
        resp2 = http_get(weather_url, params=params)
        assert resp2.json()["temp"] == 72
        assert m.call_count == 1  # No new request

        # Request with different location - should miss cache
        params2 = {"lat": "34.0", "lon": "-118.2", "appid": "test"}
        resp3 = http_get(weather_url, params=params2)
        assert m.call_count == 2  # New request for different location
