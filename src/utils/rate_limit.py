"""Thread-safe rate limiters (standard library only).

Three kinds, each for a different job:

- :class:`CooldownLimiter`: one action per key every N seconds, where a
  failed action doesn't spend the cooldown (display-next, shutdown).
- :class:`SlidingWindowLimiter`: at most N requests per key in a rolling
  window (all state-changing requests, CSP reports, the logs API).
- :class:`TokenBucket`: a burst of N, then a steady refill (login,
  display-next, costly mutating routes, the client log and error
  endpoints).

Every limiter registers itself so :func:`reset_all_limiters` can clear
them all between tests.
"""

from __future__ import annotations

import os
import threading
import time
import weakref
from collections import deque
from typing import Protocol


class _Clearable(Protocol):
    def clear(self) -> None: ...


#: Every limiter instance, so :func:`reset_all_limiters` can reach the
#: module-level ones in blueprints and middleware without importing them.
#: Weak, so a limiter that goes away is not kept alive by the registry.
_LIMITERS: weakref.WeakSet[_Clearable] = weakref.WeakSet()
_LIMITERS_LOCK = threading.Lock()


def register_limiter(limiter: _Clearable) -> None:
    """Record *limiter* so :func:`reset_all_limiters` clears it."""
    with _LIMITERS_LOCK:
        _LIMITERS.add(limiter)


def reset_all_limiters() -> None:
    """Forget every request recorded by every limiter in the process.

    For test isolation: one test's requests must not count against the next.
    """
    with _LIMITERS_LOCK:
        limiters = list(_LIMITERS)
    for limiter in limiters:
        limiter.clear()


class CooldownLimiter:
    """Fixed-window cooldown that a failed action doesn't spend.

    Usage:
        limiter = CooldownLimiter(10)  # 10-second cooldown
        allowed, retry_after = limiter.acquire()
        if allowed:
            if do_action():
                limiter.record()  # the cooldown runs from the end
            else:
                limiter.reset()  # a failed attempt costs nothing

    ``acquire`` claims the slot in the same step as the test, so two
    requests that arrive together can't both pass. A separate ``check``
    then ``record`` leaves a gap the length of the action between them.
    """

    def __init__(self, cooldown_seconds: float) -> None:
        self._cooldown = cooldown_seconds
        self._timestamps: dict[str, float] = {}
        self._lock = threading.Lock()
        register_limiter(self)

    def check(self, key: str = "global") -> tuple[bool, float]:
        """Read-only test: (allowed, retry_after_seconds).

        *retry_after* is 0.0 when allowed.
        """
        with self._lock:
            return self._check_locked(key, time.monotonic())

    def acquire(self, key: str = "global") -> tuple[bool, float]:
        """Test and, if allowed, arm the cooldown in one step.

        Returns what :meth:`check` would have. Follow an allowed acquire
        with :meth:`record` on success or :meth:`reset` on failure.
        """
        with self._lock:
            now = time.monotonic()
            allowed, retry_after = self._check_locked(key, now)
            if allowed:
                self._timestamps[key] = now
            return allowed, retry_after

    def _check_locked(self, key: str, now: float) -> tuple[bool, float]:
        last = self._timestamps.get(key)
        if last is None:
            return True, 0.0
        elapsed = now - last
        if elapsed >= self._cooldown:
            return True, 0.0
        return False, self._cooldown - elapsed

    def record(self, key: str = "global") -> None:
        """Arm the cooldown (call after a successful action)."""
        with self._lock:
            self._timestamps[key] = time.monotonic()

    def reset(self, key: str = "global") -> None:
        """Clear the cooldown for *key*."""
        with self._lock:
            self._timestamps.pop(key, None)

    def clear(self) -> None:
        """Clear the cooldown for every key."""
        with self._lock:
            self._timestamps.clear()


class SlidingWindowLimiter:
    """Per-key sliding window rate limiter.

    Usage:
        limiter = SlidingWindowLimiter(120, 60)  # 120 requests per 60 s
        allowed, retry_after = limiter.check(remote_addr)
    """

    _PRUNE_INTERVAL = 256  # amortised cleanup every N calls

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._requests: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._call_count = 0
        register_limiter(self)

    def clear(self) -> None:
        """Forget every recorded request for every key."""
        with self._lock:
            self._requests.clear()
            self._call_count = 0

    def check(self, key: str) -> tuple[bool, float]:
        """Atomically test-and-record.

        Returns (allowed, retry_after_seconds).
        """
        with self._lock:
            now = time.monotonic()
            dq = self._requests.get(key)
            if dq is None:
                dq = deque()
                self._requests[key] = dq

            # Prune expired entries for this key
            cutoff = now - self._window
            while dq and dq[0] < cutoff:
                dq.popleft()

            if len(dq) >= self._max:
                retry_after = self._window - (now - dq[0]) if dq else 0.0
                return False, max(retry_after, 0.0)

            dq.append(now)

            # Amortised pruning of empty keys to prevent memory leak
            self._call_count += 1
            if self._call_count >= self._PRUNE_INTERVAL:
                self._call_count = 0
                self._prune_empty_keys()

            return True, 0.0

    def _prune_empty_keys(self) -> None:
        """Remove keys with empty deques. Must be called while holding the lock."""
        empty = [k for k, v in self._requests.items() if not v]
        for k in empty:
            del self._requests[k]


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
        register_limiter(self)

    def clear(self) -> None:
        """Refill every bucket by forgetting all keys."""
        with self._lock:
            self._buckets.clear()

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
