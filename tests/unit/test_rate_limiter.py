"""Tests for utils.rate_limiter module."""

import threading
from collections import deque
from unittest.mock import patch

from utils.rate_limiter import CooldownLimiter, SlidingWindowLimiter

# ---------------------------------------------------------------------------
# CooldownLimiter
# ---------------------------------------------------------------------------


class TestCooldownLimiter:
    def test_check_passes_initially(self):
        limiter = CooldownLimiter(10)
        allowed, retry_after = limiter.check()
        assert allowed is True
        assert retry_after == 0.0

    def test_record_arms_cooldown(self):
        limiter = CooldownLimiter(10)
        limiter.record()
        allowed, retry_after = limiter.check()
        assert allowed is False
        assert retry_after > 0.0

    def test_check_fails_within_window(self):
        limiter = CooldownLimiter(10)
        limiter.record()
        allowed, retry_after = limiter.check()
        assert allowed is False
        assert 0.0 < retry_after <= 10.0

    def test_check_passes_after_window(self):
        limiter = CooldownLimiter(5)
        # Record at a fixed monotonic time
        with patch("utils.rate_limiter.time.monotonic", return_value=100.0):
            limiter.record()
        # Check at time 106 (past the 5s window)
        with patch("utils.rate_limiter.time.monotonic", return_value=106.0):
            allowed, retry_after = limiter.check()
        assert allowed is True
        assert retry_after == 0.0

    def test_reset_clears_cooldown(self):
        limiter = CooldownLimiter(10)
        limiter.record()
        allowed, _ = limiter.check()
        assert allowed is False

        limiter.reset()
        allowed, retry_after = limiter.check()
        assert allowed is True
        assert retry_after == 0.0

    def test_different_keys_are_independent(self):
        limiter = CooldownLimiter(10)
        limiter.record("key-a")
        allowed_a, _ = limiter.check("key-a")
        allowed_b, _ = limiter.check("key-b")
        assert allowed_a is False
        assert allowed_b is True

    def test_reset_only_affects_specified_key(self):
        limiter = CooldownLimiter(10)
        limiter.record("key-a")
        limiter.record("key-b")
        limiter.reset("key-a")
        allowed_a, _ = limiter.check("key-a")
        allowed_b, _ = limiter.check("key-b")
        assert allowed_a is True
        assert allowed_b is False


# ---------------------------------------------------------------------------
# SlidingWindowLimiter
# ---------------------------------------------------------------------------


class TestSlidingWindowLimiter:
    def test_allows_up_to_max_requests(self):
        limiter = SlidingWindowLimiter(5, 60)
        for _ in range(5):
            allowed, retry_after = limiter.check("ip")
            assert allowed is True
            assert retry_after == 0.0

    def test_blocks_at_max_plus_one(self):
        limiter = SlidingWindowLimiter(5, 60)
        for _ in range(5):
            limiter.check("ip")
        allowed, retry_after = limiter.check("ip")
        assert allowed is False
        assert retry_after > 0.0

    def test_allows_again_after_window(self):
        limiter = SlidingWindowLimiter(2, 10)
        # Fill at time 100
        with patch("utils.rate_limiter.time.monotonic", return_value=100.0):
            limiter.check("ip")
            limiter.check("ip")
            allowed, _ = limiter.check("ip")
            assert allowed is False
        # After window at time 111
        with patch("utils.rate_limiter.time.monotonic", return_value=111.0):
            allowed, retry_after = limiter.check("ip")
            assert allowed is True
            assert retry_after == 0.0

    def test_different_keys_are_independent(self):
        limiter = SlidingWindowLimiter(2, 60)
        limiter.check("ip-a")
        limiter.check("ip-a")
        # ip-a is full
        allowed_a, _ = limiter.check("ip-a")
        assert allowed_a is False
        # ip-b is fresh
        allowed_b, _ = limiter.check("ip-b")
        assert allowed_b is True

    def test_pruning_removes_empty_keys(self):
        limiter = SlidingWindowLimiter(10, 60)
        # Add an empty deque manually
        limiter._requests["stale"] = deque()
        assert "stale" in limiter._requests
        limiter._prune_empty_keys()
        assert "stale" not in limiter._requests

    def test_amortised_pruning_triggers(self):
        """After _PRUNE_INTERVAL calls, empty keys should be cleaned up."""
        limiter = SlidingWindowLimiter(1000, 60)
        limiter._requests["stale"] = deque()
        # Set call count to one less than the interval
        limiter._call_count = limiter._PRUNE_INTERVAL - 1
        limiter.check("trigger-ip")
        # After the threshold call, stale key should be pruned
        assert "stale" not in limiter._requests


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_cooldown_limiter_concurrent_access(self):
        limiter = CooldownLimiter(0.1)
        errors = []

        def worker():
            try:
                for _ in range(50):
                    limiter.check()
                    limiter.record()
                    limiter.reset()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"Thread errors: {errors}"

    def test_sliding_window_concurrent_access(self):
        limiter = SlidingWindowLimiter(1000, 60)
        results = {"allowed": 0, "denied": 0}
        lock = threading.Lock()

        def worker():
            local_allowed = 0
            local_denied = 0
            for _ in range(100):
                allowed, _ = limiter.check("shared-ip")
                if allowed:
                    local_allowed += 1
                else:
                    local_denied += 1
            with lock:
                results["allowed"] += local_allowed
                results["denied"] += local_denied

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = results["allowed"] + results["denied"]
        assert total == 1000
        # With max_requests=1000, all 1000 should be allowed
        assert results["allowed"] == 1000

    def test_sliding_window_concurrent_with_limit(self):
        """With a low limit and many threads, total allowed should not exceed max."""
        limiter = SlidingWindowLimiter(50, 60)
        allowed_count = {"value": 0}
        lock = threading.Lock()

        def worker():
            local = 0
            for _ in range(20):
                allowed, _ = limiter.check("shared-ip")
                if allowed:
                    local += 1
            with lock:
                allowed_count["value"] += local

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Total allowed must not exceed max_requests
        assert allowed_count["value"] <= 50
