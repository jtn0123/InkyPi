"""Tests for HTTP response caching functionality."""

import time
from unittest.mock import Mock

import pytest
import requests

from utils.http_cache import (
    HTTPCache,
    CacheEntry,
    CacheStats,
    get_cache,
    clear_cache,
    get_cache_stats,
    _reset_cache_for_tests,
)


@pytest.fixture
def cache():
    """Create a fresh cache instance for testing."""
    return HTTPCache(default_ttl=1.0, max_size=5, enabled=True)


@pytest.fixture
def mock_response():
    """Create a mock HTTP response."""
    resp = Mock(spec=requests.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.content = b"test response body"
    return resp


@pytest.fixture(autouse=True)
def reset_global_cache():
    """Reset global cache before each test."""
    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()


def test_cache_entry_expiration():
    """Test CacheEntry expiration logic."""
    resp = Mock(spec=requests.Response)

    # Entry with 0.1 second TTL
    entry = CacheEntry(
        response=resp,
        cached_at=time.time(),
        ttl_seconds=0.1,
        url="https://example.com",
    )

    # Should not be expired immediately
    assert not entry.is_expired()

    # Wait for expiration
    time.sleep(0.15)

    # Should now be expired
    assert entry.is_expired()


def test_cache_entry_age():
    """Test CacheEntry age calculation."""
    resp = Mock(spec=requests.Response)
    entry = CacheEntry(
        response=resp,
        cached_at=time.time(),
        ttl_seconds=10.0,
        url="https://example.com",
    )

    # Age should be near 0
    assert entry.age_seconds() < 0.1

    time.sleep(0.1)

    # Age should be around 0.1 seconds
    assert 0.05 < entry.age_seconds() < 0.2


def test_cache_stats_hit_rate():
    """Test cache statistics hit rate calculation."""
    stats = CacheStats()

    # No requests yet
    assert stats.hit_rate() == 0.0

    # 3 hits, 2 misses = 60% hit rate
    stats.hits = 3
    stats.misses = 2
    assert stats.hit_rate() == 60.0

    # 10 hits, 0 misses = 100% hit rate
    stats.hits = 10
    stats.misses = 0
    assert stats.hit_rate() == 100.0


def test_cache_basic_put_and_get(cache, mock_response):
    """Test basic cache put and get operations."""
    url = "https://api.example.com/data"

    # Cache should be empty initially
    assert cache.get(url) is None

    # Store response in cache
    cache.put(url, mock_response)

    # Should retrieve the cached response
    cached = cache.get(url)
    assert cached is not None
    assert cached.status_code == 200
    assert cached.content == b"test response body"


def test_cache_with_params(cache, mock_response):
    """Test that query parameters affect cache keys."""
    url = "https://api.example.com/data"

    # Store with params
    cache.put(url, mock_response, params={"key": "value1"})

    # Get with same params should hit
    cached = cache.get(url, params={"key": "value1"})
    assert cached is not None

    # Get with different params should miss
    cached = cache.get(url, params={"key": "value2"})
    assert cached is None

    # Get without params should also miss
    cached = cache.get(url)
    assert cached is None


def test_cache_expiration(cache, mock_response):
    """Test that expired entries are not returned."""
    url = "https://api.example.com/data"

    # Store with short TTL
    cache.put(url, mock_response, ttl=0.1)

    # Should be available immediately
    assert cache.get(url) is not None

    # Wait for expiration
    time.sleep(0.15)

    # Should no longer be available
    assert cache.get(url) is None

    # Stats should show an expiration
    stats = cache.get_stats()
    assert stats["expirations"] == 1


def test_cache_control_headers(cache):
    """Test that Cache-Control headers are respected."""
    url = "https://api.example.com/data"

    # Response with max-age
    resp_with_maxage = Mock(spec=requests.Response)
    resp_with_maxage.status_code = 200
    resp_with_maxage.headers = {"Cache-Control": "max-age=3600"}
    resp_with_maxage.content = b"cached data"

    cache.put(url, resp_with_maxage)
    entry = cache._cache[cache._make_cache_key(url)]
    assert entry.ttl_seconds == 3600.0

    # Response with no-cache
    resp_no_cache = Mock(spec=requests.Response)
    resp_no_cache.status_code = 200
    resp_no_cache.headers = {"Cache-Control": "no-cache"}
    resp_no_cache.content = b"no cache"

    cache.clear()
    cache.put(url + "/nocache", resp_no_cache)

    # Should not be cached
    cache_key = cache._make_cache_key(url + "/nocache")
    assert cache_key not in cache._cache


def test_cache_lru_eviction(cache, mock_response):
    """Test LRU eviction when cache reaches max size."""
    # Cache max_size is 5

    # Fill cache to capacity
    for i in range(5):
        cache.put(f"https://example.com/item{i}", mock_response)

    assert len(cache._cache) == 5
    assert cache.get_stats()["evictions"] == 0

    # Add one more - should trigger eviction
    cache.put("https://example.com/item5", mock_response)

    assert len(cache._cache) == 5
    assert cache.get_stats()["evictions"] == 1


def test_cache_hit_count_affects_lru(cache, mock_response):
    """Test that hit count affects LRU eviction."""
    # Add 5 items
    for i in range(5):
        cache.put(f"https://example.com/item{i}", mock_response)

    # Access item0 multiple times to increase hit count
    for _ in range(10):
        cache.get("https://example.com/item0")

    # Add a new item to trigger eviction
    cache.put("https://example.com/item5", mock_response)

    # item0 should still be in cache due to high hit count
    assert cache.get("https://example.com/item0") is not None


def test_cache_non_200_responses_not_cached(cache):
    """Test that non-2xx responses are not cached."""
    url = "https://api.example.com/error"

    # 404 response
    resp_404 = Mock(spec=requests.Response)
    resp_404.status_code = 404
    resp_404.headers = {}

    cache.put(url, resp_404)

    # Should not be cached
    assert cache.get(url) is None

    # 500 response
    resp_500 = Mock(spec=requests.Response)
    resp_500.status_code = 500
    resp_500.headers = {}

    cache.put(url, resp_500)

    # Should not be cached
    assert cache.get(url) is None


def test_cache_disabled(mock_response):
    """Test that caching can be disabled."""
    disabled_cache = HTTPCache(enabled=False)

    url = "https://example.com/data"
    disabled_cache.put(url, mock_response)

    # Should not cache when disabled
    assert disabled_cache.get(url) is None


def test_cache_clear(cache, mock_response):
    """Test clearing the cache."""
    # Add some entries
    for i in range(3):
        cache.put(f"https://example.com/item{i}", mock_response)

    assert len(cache._cache) == 3

    # Clear cache
    removed = cache.clear()

    assert removed == 3
    assert len(cache._cache) == 0

    # Verify entries are gone
    assert cache.get("https://example.com/item0") is None


def test_cache_remove_expired(cache, mock_response):
    """Test manual removal of expired entries."""
    # Add entry with short TTL
    cache.put("https://example.com/short", mock_response, ttl=0.1)

    # Add entry with long TTL
    cache.put("https://example.com/long", mock_response, ttl=10.0)

    assert len(cache._cache) == 2

    # Wait for one to expire
    time.sleep(0.15)

    # Remove expired
    removed = cache.remove_expired()

    assert removed == 1
    assert len(cache._cache) == 1

    # Long TTL entry should still be there
    assert cache.get("https://example.com/long") is not None


def test_global_cache_instance():
    """Test global cache singleton."""
    # Get cache twice
    cache1 = get_cache()
    cache2 = get_cache()

    # Should be same instance
    assert cache1 is cache2


def test_global_cache_operations(mock_response):
    """Test global cache operations."""
    # Clear first
    clear_cache()

    # Get cache and add entry
    cache = get_cache()
    url = "https://example.com/global"
    cache.put(url, mock_response)

    # Stats should show the entry
    stats = get_cache_stats()
    assert stats["size"] == 1

    # Clear via helper
    cleared = clear_cache()
    assert cleared == 1

    # Stats should show empty
    stats = get_cache_stats()
    assert stats["size"] == 0


def test_cache_key_consistency(cache):
    """Test that cache keys are generated consistently."""
    url = "https://api.example.com/data"
    params = {"a": "1", "b": "2"}

    # Generate keys multiple times
    key1 = cache._make_cache_key(url, params)
    key2 = cache._make_cache_key(url, params)

    # Should be identical
    assert key1 == key2

    # Different order of params should produce same key
    key3 = cache._make_cache_key(url, {"b": "2", "a": "1"})
    assert key1 == key3


def test_cache_stats_tracking(cache, mock_response):
    """Test that cache statistics are tracked correctly."""
    url = "https://example.com/stats"

    # Miss
    cache.get(url)
    stats = cache.get_stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 1

    # Add to cache
    cache.put(url, mock_response)

    # Hit
    cache.get(url)
    stats = cache.get_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 50.0


def test_cache_thread_safety(cache, mock_response):
    """Test that cache is thread-safe."""
    import threading

    url = "https://example.com/concurrent"
    errors = []

    def add_and_get():
        try:
            for i in range(10):
                cache.put(f"{url}/{i}", mock_response)
                cache.get(f"{url}/{i}")
        except Exception as e:
            errors.append(e)

    # Run concurrent operations
    threads = [threading.Thread(target=add_and_get) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    # No errors should occur
    assert len(errors) == 0


def test_cache_custom_ttl_override(cache, mock_response):
    """Test that custom TTL overrides default."""
    url = "https://example.com/custom_ttl"

    # Put with custom TTL
    cache.put(url, mock_response, ttl=0.2)

    # Check the actual TTL
    entry = cache._cache[cache._make_cache_key(url)]
    assert entry.ttl_seconds == 0.2
