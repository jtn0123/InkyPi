"""Thread-safe rate limiters for cooldowns and sliding windows."""

import threading
import time
from collections import deque


class CooldownLimiter:
    """Fixed-window cooldown that arms only after a successful action.

    Usage:
        limiter = CooldownLimiter(10)  # 10-second cooldown
        allowed, retry_after = limiter.check()
        if allowed:
            do_action()
            limiter.record()
    """

    def __init__(self, cooldown_seconds: float) -> None:
        self._cooldown = cooldown_seconds
        self._timestamps: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, key: str = "global") -> tuple[bool, float]:
        """Read-only test: (allowed, retry_after_seconds).

        *retry_after* is 0.0 when allowed.
        """
        with self._lock:
            last = self._timestamps.get(key)
            if last is None:
                return True, 0.0
            elapsed = time.monotonic() - last
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
