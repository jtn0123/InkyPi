"""Tests for utils.rate_limit (TokenBucket) and per-endpoint middleware (JTN-447)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from flask import Flask

from utils.rate_limit import (
    TokenBucket,
    _parse_rate_env,
    make_auth_bucket,
    make_refresh_bucket,
)

# ---------------------------------------------------------------------------
# TokenBucket unit tests
# ---------------------------------------------------------------------------


class TestTokenBucket:
    def test_initial_acquire_succeeds(self):
        bucket = TokenBucket(capacity=5, refill_rate=1 / 30)
        assert bucket.try_acquire("192.168.1.1") is True

    def test_acquire_up_to_capacity(self):
        bucket = TokenBucket(capacity=3, refill_rate=0)
        # First acquisition uses up one token from a new bucket that starts at capacity
        assert bucket.try_acquire("ip") is True  # capacity-1 = 2 tokens remain
        assert bucket.try_acquire("ip") is True  # 1 token remains
        assert bucket.try_acquire("ip") is True  # 0 tokens remain
        assert bucket.try_acquire("ip") is False  # denied

    def test_acquire_denied_when_empty(self):
        bucket = TokenBucket(capacity=1, refill_rate=0)
        assert bucket.try_acquire("ip") is True
        assert bucket.try_acquire("ip") is False

    def test_refill_after_time_passes(self):
        bucket = TokenBucket(capacity=3, refill_rate=1)  # 1 token/second
        with patch("utils.rate_limit.time.monotonic", return_value=100.0):
            # Drain: first call creates bucket at cap-1=2, then two more
            bucket.try_acquire("ip")
            bucket.try_acquire("ip")
            bucket.try_acquire("ip")  # now empty
            assert bucket.try_acquire("ip") is False

        # After 2 seconds, 2 tokens should have refilled
        with patch("utils.rate_limit.time.monotonic", return_value=102.0):
            assert bucket.try_acquire("ip") is True
            assert bucket.try_acquire("ip") is True
            assert bucket.try_acquire("ip") is False

    def test_different_keys_tracked_separately(self):
        bucket = TokenBucket(capacity=1, refill_rate=0)
        assert bucket.try_acquire("ip-a") is True
        assert bucket.try_acquire("ip-a") is False
        # ip-b is unaffected
        assert bucket.try_acquire("ip-b") is True

    def test_stale_buckets_evicted(self):
        bucket = TokenBucket(capacity=5, refill_rate=1, ttl=10)
        with patch("utils.rate_limit.time.monotonic", return_value=100.0):
            bucket.try_acquire("stale-ip")
        assert "stale-ip" in bucket._buckets

        # Advance time past ttl, trigger eviction via a new acquire call
        with patch("utils.rate_limit.time.monotonic", return_value=115.0):
            bucket.try_acquire("new-ip")

        assert "stale-ip" not in bucket._buckets

    def test_capacity_not_exceeded_by_refill(self):
        bucket = TokenBucket(capacity=5, refill_rate=100)  # fast refill
        with patch("utils.rate_limit.time.monotonic", return_value=100.0):
            bucket.try_acquire("ip")  # creates bucket
        # Long time passes — tokens should be capped at capacity
        with patch("utils.rate_limit.time.monotonic", return_value=200.0):
            # Acquire 5 times — should all succeed (capacity = 5)
            results = [bucket.try_acquire("ip") for _ in range(5)]
            assert all(results)
            # 6th should fail
            assert bucket.try_acquire("ip") is False

    def test_thread_safety(self):
        import threading

        bucket = TokenBucket(capacity=100, refill_rate=0)
        allowed_count = {"n": 0}
        lock = threading.Lock()

        def worker():
            local = sum(1 for _ in range(20) if bucket.try_acquire("shared"))
            with lock:
                allowed_count["n"] += local

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Must never exceed capacity
        assert allowed_count["n"] <= 100


# ---------------------------------------------------------------------------
# Env-var config parsing
# ---------------------------------------------------------------------------


class TestParseRateEnv:
    def test_defaults_returned_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("INKYPI_RATE_LIMIT_AUTH", raising=False)
        cap, rate = _parse_rate_env("INKYPI_RATE_LIMIT_AUTH", 5, 1 / 30)
        assert cap == 5.0
        assert rate == pytest.approx(1 / 30)

    def test_parses_valid_env(self, monkeypatch):
        monkeypatch.setenv("INKYPI_RATE_LIMIT_AUTH", "10/60")
        cap, rate = _parse_rate_env("INKYPI_RATE_LIMIT_AUTH", 5, 1 / 30)
        assert cap == 10.0
        assert rate == pytest.approx(1 / 60)

    def test_invalid_env_falls_back_to_defaults(self, monkeypatch):
        monkeypatch.setenv("INKYPI_RATE_LIMIT_AUTH", "bad/value")
        cap, rate = _parse_rate_env("INKYPI_RATE_LIMIT_AUTH", 5, 1 / 30)
        assert cap == 5.0
        assert rate == pytest.approx(1 / 30)

    def test_make_auth_bucket_uses_defaults(self, monkeypatch):
        monkeypatch.delenv("INKYPI_RATE_LIMIT_AUTH", raising=False)
        b = make_auth_bucket()
        assert b._capacity == 5.0

    def test_make_refresh_bucket_uses_defaults(self, monkeypatch):
        monkeypatch.delenv("INKYPI_RATE_LIMIT_REFRESH", raising=False)
        b = make_refresh_bucket()
        assert b._capacity == 10.0

    def test_make_auth_bucket_respects_env(self, monkeypatch):
        monkeypatch.setenv("INKYPI_RATE_LIMIT_AUTH", "7/45")
        b = make_auth_bucket()
        assert b._capacity == 7.0
        assert b._refill_rate == pytest.approx(1 / 45)


# ---------------------------------------------------------------------------
# Per-endpoint middleware integration tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def rate_limit_app():
    """Minimal Flask app with per-endpoint token-bucket rate limiting."""
    from utils.rate_limit import TokenBucket

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True

    # Tight buckets for fast testing
    auth_b = TokenBucket(capacity=5, refill_rate=0)
    refresh_b = TokenBucket(capacity=10, refill_rate=0)

    _AUTH_PATHS = frozenset({"/login"})
    _REFRESH_PATHS = frozenset({"/display-next", "/refresh"})

    from utils.http_utils import json_error

    @app.before_request
    def _rl():
        from flask import make_response, request

        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        addr = request.remote_addr or "unknown"
        if request.path in _AUTH_PATHS and not auth_b.try_acquire(addr):
            body, code = json_error(
                "Too many login attempts — try again later", status=429
            )
            resp = make_response(body, code)
            resp.headers["Retry-After"] = "30"
            return resp
        elif request.path in _REFRESH_PATHS and not refresh_b.try_acquire(addr):
            body, code = json_error(
                "Refresh rate limit exceeded — try again later", status=429
            )
            resp = make_response(body, code)
            resp.headers["Retry-After"] = "6"
            return resp
        return None

    @app.route("/login", methods=["POST"])
    def login():
        return {"ok": True}

    @app.route("/display-next", methods=["POST"])
    def display_next():
        return {"ok": True}

    @app.route("/refresh", methods=["POST"])
    def refresh_alias():
        return {"ok": True}

    @app.route("/api/health", methods=["GET"])
    def health():
        return {"status": "ok"}

    @app.route("/api/other", methods=["POST"])
    def other():
        return {"ok": True}

    return app


class TestLoginEndpointRateLimit:
    def test_five_logins_succeed(self, rate_limit_app):
        client = rate_limit_app.test_client()
        for _ in range(5):
            resp = client.post("/login")
            assert resp.status_code == 200

    def test_sixth_login_returns_429(self, rate_limit_app):
        client = rate_limit_app.test_client()
        for _ in range(5):
            client.post("/login")
        resp = client.post("/login")
        assert resp.status_code == 429

    def test_sixth_login_has_retry_after_header(self, rate_limit_app):
        client = rate_limit_app.test_client()
        for _ in range(5):
            client.post("/login")
        resp = client.post("/login")
        assert resp.headers.get("Retry-After") == "30"

    def test_sixth_login_has_json_error_body(self, rate_limit_app):
        client = rate_limit_app.test_client()
        for _ in range(5):
            client.post("/login")
        resp = client.post("/login")
        data = resp.get_json()
        assert data is not None
        assert (
            "rate" in data.get("error", "").lower()
            or "attempt" in data.get("error", "").lower()
        )


class TestRefreshEndpointRateLimit:
    def test_ten_refresh_calls_succeed(self, rate_limit_app):
        client = rate_limit_app.test_client()
        for _ in range(10):
            resp = client.post("/display-next")
            assert resp.status_code == 200

    def test_eleventh_refresh_returns_429(self, rate_limit_app):
        client = rate_limit_app.test_client()
        for _ in range(10):
            client.post("/display-next")
        resp = client.post("/display-next")
        assert resp.status_code == 429

    def test_eleventh_refresh_has_retry_after_header(self, rate_limit_app):
        client = rate_limit_app.test_client()
        for _ in range(10):
            client.post("/display-next")
        resp = client.post("/display-next")
        assert resp.headers.get("Retry-After") == "6"

    def test_refresh_alias_also_rate_limited(self, rate_limit_app):
        client = rate_limit_app.test_client()
        for _ in range(10):
            client.post("/refresh")
        resp = client.post("/refresh")
        assert resp.status_code == 429


class TestIpIsolation:
    def test_different_ips_tracked_separately(self, rate_limit_app):
        """Exhausting one IP's bucket should not affect another IP."""
        with rate_limit_app.test_client() as client:
            # Exhaust ip-a by overriding remote_addr via environ_base
            for _ in range(5):
                client.post("/login", environ_base={"REMOTE_ADDR": "10.0.0.1"})
            # ip-a is now denied
            resp = client.post("/login", environ_base={"REMOTE_ADDR": "10.0.0.1"})
            assert resp.status_code == 429
            # ip-b is still fine
            resp_b = client.post("/login", environ_base={"REMOTE_ADDR": "10.0.0.2"})
            assert resp_b.status_code == 200


class TestNonRateLimitedEndpoints:
    def test_health_get_not_rate_limited(self, rate_limit_app):
        client = rate_limit_app.test_client()
        for _ in range(20):
            resp = client.get("/api/health")
            assert resp.status_code == 200

    def test_other_post_not_covered_by_endpoint_limiter(self, rate_limit_app):
        """General endpoints should not be blocked by the per-endpoint bucket."""
        client = rate_limit_app.test_client()
        # The other endpoint has no rate limit in this fixture
        for _ in range(15):
            resp = client.post("/api/other")
            assert resp.status_code == 200
