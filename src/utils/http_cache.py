"""HTTP response caching with TTL support for improved performance.

This module provides a thread-safe, TTL-based cache for HTTP responses,
significantly reducing redundant API calls in plugins.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Represents a cached HTTP response with metadata."""

    cached_data: dict[str, Any]
    cached_at: float
    ttl_seconds: float
    url: str
    hit_count: int = 0

    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return (time.time() - self.cached_at) > self.ttl_seconds

    def age_seconds(self) -> float:
        """Return the age of this cache entry in seconds."""
        return time.time() - self.cached_at

    def build_response(self) -> requests.Response:
        """Reconstruct a lightweight Response from cached data.

        Returns a new Response object with status_code, headers, and content
        populated from the stored data. No socket or connection references are
        held by the returned object.
        """
        resp = requests.models.Response()
        resp.status_code = self.cached_data["status_code"]
        resp.headers.update(self.cached_data["headers"])
        resp._content = self.cached_data["content"]  # type: ignore[attr-defined]
        return resp


@dataclass
class CacheStats:
    """Statistics for cache performance monitoring."""

    hits: int = 0
    misses: int = 0
    expirations: int = 0
    evictions: int = 0
    errors: int = 0

    def hit_rate(self) -> float:
        """Calculate cache hit rate as a percentage."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return (self.hits / total) * 100.0

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "expirations": self.expirations,
            "evictions": self.evictions,
            "errors": self.errors,
            "hit_rate": round(self.hit_rate(), 2),
        }


_DEFAULT_MAX_ENTRIES = 256


class HTTPCache:
    """Thread-safe HTTP response cache with TTL and LRU eviction."""

    def __init__(
        self,
        default_ttl: float = 300.0,  # 5 minutes
        max_size: int = 100,
        enabled: bool = True,
        max_entries: int | None = None,
    ):
        """Initialize the HTTP cache.

        Args:
            default_ttl: Default time-to-live in seconds
            max_size: Maximum number of entries before LRU eviction (legacy param)
            enabled: Whether caching is enabled
            max_entries: Maximum number of entries cap with LRU eviction.
                Defaults to HTTP_CACHE_MAX_ENTRIES env var or 256.
        """
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.enabled = enabled

        # Resolve max_entries: explicit arg > env var > default
        if max_entries is not None:
            self.max_entries = max_entries
        else:
            try:
                self.max_entries = int(
                    os.getenv("HTTP_CACHE_MAX_ENTRIES", str(_DEFAULT_MAX_ENTRIES))
                )
            except ValueError:
                self.max_entries = _DEFAULT_MAX_ENTRIES

        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = CacheStats()

        logger.info(
            "HTTP cache initialized | enabled=%s ttl=%.0fs max_size=%d max_entries=%d",
            enabled,
            default_ttl,
            max_size,
            self.max_entries,
        )

    def _make_cache_key(self, url: str, params: dict[str, Any] | None = None) -> str:
        """Generate a cache key from URL and parameters."""
        # Include params in the key for uniqueness
        key_parts = [url]
        if params:
            # Sort params for consistent key generation
            sorted_params = sorted(params.items())
            param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
            key_parts.append(param_str)

        combined = "|".join(key_parts)
        return hashlib.sha256(combined.encode()).hexdigest()

    def _parse_cache_control(self, response: requests.Response) -> float | None:
        """Extract TTL from Cache-Control header if present.

        Returns:
            TTL in seconds if Cache-Control specifies max-age, else None
        """
        try:
            cache_control = response.headers.get("Cache-Control", "")
            if "no-cache" in cache_control or "no-store" in cache_control:
                return 0.0  # Don't cache

            # Look for max-age directive
            for directive in cache_control.split(","):
                directive = directive.strip()
                if directive.startswith("max-age="):
                    max_age_str = directive.split("=", 1)[1]
                    return float(max_age_str)
        except (ValueError, IndexError):
            pass

        return None

    def _evict_lru(self) -> None:
        """Evict least recently used entry when cache is full.

        The OrderedDict keeps insertion/access order: the front (last=False)
        is the least-recently-used entry, which is removed here.

        Must be called with lock held.
        """
        if not self._cache:
            return

        self._cache.popitem(last=False)
        self._stats.evictions += 1

    def get(
        self, url: str, params: dict[str, Any] | None = None
    ) -> requests.Response | None:
        """Retrieve a cached response if available and not expired.

        Args:
            url: The URL to check
            params: Query parameters (affects cache key)

        Returns:
            Cached response if available and fresh, else None
        """
        if not self.enabled:
            return None

        cache_key = self._make_cache_key(url, params)

        with self._lock:
            entry = self._cache.get(cache_key)

            if entry is None:
                self._stats.misses += 1
                logger.debug(
                    "cache_lookup: miss",
                    extra={
                        "url": url,
                        "hit": False,
                        "reason": "not_found",
                    },
                )
                return None

            if entry.is_expired():
                # Expired, remove it
                ttl_remaining = entry.ttl_seconds - entry.age_seconds()
                del self._cache[cache_key]
                self._stats.expirations += 1
                self._stats.misses += 1
                logger.debug(
                    "cache_lookup: expired",
                    extra={
                        "url": url,
                        "hit": False,
                        "reason": "expired",
                        "age_s": round(entry.age_seconds(), 1),
                        "ttl_remaining_s": round(ttl_remaining, 1),
                    },
                )
                return None

            # Cache hit — move to most-recently-used position (end of OrderedDict)
            entry.hit_count += 1
            self._stats.hits += 1
            self._cache.move_to_end(cache_key)
            ttl_remaining = entry.ttl_seconds - entry.age_seconds()
            logger.debug(
                "cache_lookup: hit",
                extra={
                    "url": url,
                    "hit": True,
                    "age_s": round(entry.age_seconds(), 1),
                    "ttl_remaining_s": round(ttl_remaining, 1),
                    "hit_count": entry.hit_count,
                },
            )
            return entry.build_response()

    def put(
        self,
        url: str,
        response: requests.Response,
        params: dict[str, Any] | None = None,
        ttl: float | None = None,
    ) -> None:
        """Store a response in the cache.

        Args:
            url: The URL being cached
            response: The response object to cache
            params: Query parameters (affects cache key)
            ttl: Time-to-live in seconds (overrides default and Cache-Control)
        """
        if not self.enabled:
            return

        # Don't cache non-successful responses
        if not (200 <= response.status_code < 300):
            return

        cache_key = self._make_cache_key(url, params)

        # Determine TTL
        effective_ttl = ttl
        if effective_ttl is None:
            # Try to get TTL from Cache-Control header
            header_ttl = self._parse_cache_control(response)
            effective_ttl = header_ttl if header_ttl is not None else self.default_ttl

        # Don't cache if TTL is 0
        if effective_ttl <= 0:
            logger.debug("Cache skip | url=%s (no-cache directive)", url)
            return

        # Extract only the essential data from the response.
        # Reading response.content also closes the underlying connection,
        # returning the socket to the pool.
        cached_data = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content": response.content,
        }

        with self._lock:
            # Evict if at capacity (enforce both max_size and max_entries)
            effective_cap = min(self.max_size, self.max_entries)
            while len(self._cache) >= effective_cap and cache_key not in self._cache:
                self._evict_lru()

            self._cache[cache_key] = CacheEntry(
                cached_data=cached_data,
                cached_at=time.time(),
                ttl_seconds=effective_ttl,
                url=url,
            )

            logger.debug(
                "Cache stored | url=%s ttl=%.0fs size=%d",
                url,
                effective_ttl,
                len(self._cache),
            )

    def clear(self) -> int:
        """Clear all cache entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info("Cache cleared | removed=%d", count)
            return count

    def stats(self) -> dict[str, Any]:
        """Return a snapshot of cache statistics.

        Returns:
            Dictionary with hits, misses, evictions, hit_rate, size,
            max_entries, and enabled flag.
        """
        with self._lock:
            result = self._stats.to_dict()
            result["size"] = len(self._cache)
            result["max_entries"] = self.max_entries
            result["max_size"] = self.max_size
            result["enabled"] = self.enabled
            return result

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats including hits, misses, hit rate, etc.
        """
        with self._lock:
            result = self._stats.to_dict()
            result["size"] = len(self._cache)
            result["max_size"] = self.max_size
            result["max_entries"] = self.max_entries
            result["enabled"] = self.enabled
            return result

    def remove_expired(self) -> int:
        """Remove all expired entries from cache.

        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
            for key in expired_keys:
                del self._cache[key]
            if expired_keys:
                logger.debug("Cache cleanup | removed=%d expired", len(expired_keys))
            return len(expired_keys)


# Global cache instance
_global_cache: HTTPCache | None = None
_cache_lock = threading.Lock()


def get_cache() -> HTTPCache:
    """Get or create the global HTTP cache instance.

    Cache configuration is read from environment variables:
    - INKYPI_HTTP_CACHE_ENABLED: Enable/disable caching (default: true)
    - INKYPI_HTTP_CACHE_TTL_S: Default TTL in seconds (default: 300)
    - INKYPI_HTTP_CACHE_MAX_SIZE: Max cache entries (default: 100)
    - HTTP_CACHE_MAX_ENTRIES: Hard cap with LRU eviction (default: 256)
    """
    global _global_cache

    if _global_cache is not None:
        return _global_cache

    with _cache_lock:
        if _global_cache is not None:
            return _global_cache

        # Read configuration from environment
        enabled = os.getenv("INKYPI_HTTP_CACHE_ENABLED", "true").lower() in (
            "true",
            "1",
            "yes",
        )
        try:
            ttl = float(os.getenv("INKYPI_HTTP_CACHE_TTL_S", "300"))
        except ValueError:
            ttl = 300.0
        try:
            max_size = int(os.getenv("INKYPI_HTTP_CACHE_MAX_SIZE", "100"))
        except ValueError:
            max_size = 100
        try:
            max_entries = int(
                os.getenv("HTTP_CACHE_MAX_ENTRIES", str(_DEFAULT_MAX_ENTRIES))
            )
        except ValueError:
            max_entries = _DEFAULT_MAX_ENTRIES

        _global_cache = HTTPCache(
            default_ttl=ttl,
            max_size=max_size,
            enabled=enabled,
            max_entries=max_entries,
        )
        return _global_cache


def clear_cache() -> int:
    """Clear the global HTTP cache.

    Returns:
        Number of entries removed
    """
    return get_cache().clear()


def get_cache_stats() -> dict[str, Any]:
    """Get statistics from the global HTTP cache.

    Returns:
        Dictionary with cache statistics
    """
    return get_cache().get_stats()


def _reset_cache_for_tests() -> None:
    """Reset the global cache (testing only)."""
    global _global_cache
    with _cache_lock:
        _global_cache = None
