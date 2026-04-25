"""Token-bucket rate limiter (stdlib-only, thread-safe).

Designed for per-IP limiting of specific Flask endpoints such as /login and
/display-next.  No external dependencies — uses only threading, time, and
os from the standard library.

Usage::

    limiter = TokenBucket(capacity=5, refill_rate=1/30)
    if limiter.try_acquire("192.168.1.1"):
        # process request
    else:
        # return 429
"""

from __future__ import annotations

import os
import threading
import time


class TokenBucket:
    """Per-key token-bucket rate limiter.

    Args:
        capacity:    Maximum number of tokens (burst size).
        refill_rate: Tokens added per second (e.g. ``1/30`` ≈ one token per
                     30 seconds).
        ttl:         Seconds of inactivity before a bucket is evicted.
                     Defaults to 300 (5 minutes).
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        ttl: float = 300.0,
    ) -> None:
        self._capacity = float(capacity)
        self._refill_rate = float(refill_rate)
        self._ttl = float(ttl)
        # keyed by (str -> [tokens: float, last_refill: float, last_used: float])
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def try_acquire(self, key: str) -> bool:
        """Attempt to consume one token from the bucket for *key*.

        Returns ``True`` when a token was available (request allowed),
        ``False`` otherwise (request should be rate-limited).

        Side-effect: performs cheap O(n) eviction of stale buckets on every
        call so memory stays bounded without a background thread.
        """
        with self._lock:
            now = time.monotonic()
            self._evict_stale(now)

            bucket = self._buckets.get(key)
            if bucket is None:
                # New bucket: start at capacity minus the one token we consume.
                self._buckets[key] = [self._capacity - 1.0, now, now]
                return True

            tokens, last_refill, _last_used = bucket
            # Refill tokens based on elapsed time
            elapsed = now - last_refill
            tokens = min(self._capacity, tokens + elapsed * self._refill_rate)

            if tokens < 1.0:
                # No token available — update last_used so we don't evict while
                # the IP is still hammering us.
                bucket[2] = now
                return False

            bucket[0] = tokens - 1.0
            bucket[1] = now
            bucket[2] = now
            return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _evict_stale(self, now: float) -> None:
        """Remove buckets idle for longer than *ttl* seconds.

        Must be called while holding ``self._lock``.
        """
        stale = [k for k, v in self._buckets.items() if now - v[2] > self._ttl]
        for k in stale:
            del self._buckets[k]


# ---------------------------------------------------------------------------
# Env-var config helpers
# ---------------------------------------------------------------------------

_DEFAULT_AUTH_CAPACITY = 5
_DEFAULT_AUTH_REFILL = 1 / 30  # 1 token per 30 s

_DEFAULT_REFRESH_CAPACITY = 10
_DEFAULT_REFRESH_REFILL = 1 / 6  # 1 token per 6 s

_DEFAULT_MUTATING_CAPACITY = 10
_DEFAULT_MUTATING_REFILL = 10 / 60  # 10 tokens per minute


def _parse_rate_env(
    name: str, capacity_default: int, rate_default: float
) -> tuple[float, float]:
    """Parse ``N/Sseconds`` from *name* env var.

    Format: ``"5/30"`` → capacity=5, refill_rate=1/30.
    Returns *(capacity, refill_rate)* as floats.
    """
    raw = os.getenv(name, "").strip()
    if raw:
        try:
            parts = raw.split("/")
            cap = float(parts[0])
            secs = float(parts[1]) if len(parts) > 1 else 1.0
            if cap > 0 and secs > 0:
                return cap, 1.0 / secs
        except (ValueError, IndexError):
            pass
    return float(capacity_default), rate_default


def make_auth_bucket() -> TokenBucket:
    """Return a TokenBucket configured for the /login endpoint."""
    cap, rate = _parse_rate_env(
        "INKYPI_RATE_LIMIT_AUTH", _DEFAULT_AUTH_CAPACITY, _DEFAULT_AUTH_REFILL
    )
    return TokenBucket(capacity=cap, refill_rate=rate)


def make_refresh_bucket() -> TokenBucket:
    """Return a TokenBucket configured for the /display-next endpoint."""
    cap, rate = _parse_rate_env(
        "INKYPI_RATE_LIMIT_REFRESH", _DEFAULT_REFRESH_CAPACITY, _DEFAULT_REFRESH_REFILL
    )
    return TokenBucket(capacity=cap, refill_rate=rate)


def make_mutating_bucket() -> TokenBucket:
    """Return a TokenBucket configured for high-cost mutating endpoints.

    Applied to endpoints such as /save_plugin_settings and /update_now that
    can saturate CPU or hardware resources if hammered.  Looser than the auth
    bucket (3/min) but stricter than the global sliding-window (60/min).
    Default: burst of 10, refill at 10/min per IP.

    Override with env var ``INKYPI_RATE_LIMIT_MUTATING`` in ``N/Sseconds``
    format (e.g. ``"10/60"``).
    """
    cap, rate = _parse_rate_env(
        "INKYPI_RATE_LIMIT_MUTATING",
        _DEFAULT_MUTATING_CAPACITY,
        _DEFAULT_MUTATING_REFILL,
    )
    return TokenBucket(capacity=cap, refill_rate=rate)
