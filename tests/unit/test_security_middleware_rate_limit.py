# pyright: reportMissingImports=false
"""Unit tests for security_middleware rate-limiting helpers (JTN-513).

Exercises _is_mutating_path, _apply_token_bucket_limits, and
setup_rate_limiting to ensure the new mutating-endpoint bucket is wired
correctly into the middleware chain.
"""

from __future__ import annotations

import pytest
from flask import Flask

# ---------------------------------------------------------------------------
# _is_mutating_path
# ---------------------------------------------------------------------------


class TestIsMutatingPath:
    def test_save_plugin_settings_is_mutating(self):
        from app_setup.security_middleware import _is_mutating_path

        assert _is_mutating_path("/save_plugin_settings") is True

    def test_update_now_is_mutating(self):
        from app_setup.security_middleware import _is_mutating_path

        assert _is_mutating_path("/update_now") is True

    def test_api_refresh_subpath_is_mutating(self):
        from app_setup.security_middleware import _is_mutating_path

        assert _is_mutating_path("/api/refresh/all") is True
        assert _is_mutating_path("/api/refresh/plugin/42") is True

    def test_api_refresh_exact_prefix_not_mutating(self):
        """Only paths starting with /api/refresh/ (with trailing slash) match."""
        from app_setup.security_middleware import _is_mutating_path

        # This deliberately does NOT start with "/api/refresh/" (note trailing slash)
        assert _is_mutating_path("/api/refreshment") is False

    def test_login_not_mutating(self):
        from app_setup.security_middleware import _is_mutating_path

        assert _is_mutating_path("/login") is False

    def test_display_next_not_mutating(self):
        from app_setup.security_middleware import _is_mutating_path

        assert _is_mutating_path("/display-next") is False

    def test_healthz_not_mutating(self):
        from app_setup.security_middleware import _is_mutating_path

        assert _is_mutating_path("/healthz") is False

    def test_other_path_not_mutating(self):
        from app_setup.security_middleware import _is_mutating_path

        assert _is_mutating_path("/api/logs") is False


# ---------------------------------------------------------------------------
# _apply_token_bucket_limits
# ---------------------------------------------------------------------------


@pytest.fixture()
def ctx_app():
    """Minimal Flask app used to provide an application context for direct helper tests."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    return app


@pytest.fixture(autouse=True)
def _reset_module_buckets():
    """Reset module-level bucket references before/after each test."""
    import app_setup.security_middleware as mw
    from utils.rate_limit import TokenBucket

    orig_auth = mw._auth_bucket
    orig_refresh = mw._refresh_bucket
    orig_mutating = mw._mutating_bucket
    # Install fresh zero-refill buckets so tests are deterministic
    mw._auth_bucket = TokenBucket(capacity=5, refill_rate=0)
    mw._refresh_bucket = TokenBucket(capacity=10, refill_rate=0)
    mw._mutating_bucket = TokenBucket(capacity=10, refill_rate=0)
    yield
    mw._auth_bucket = orig_auth
    mw._refresh_bucket = orig_refresh
    mw._mutating_bucket = orig_mutating


class TestApplyTokenBucketLimits:
    """Tests for _apply_token_bucket_limits helper (JTN-513)."""

    _TEST_ADDR = "127.0.0.1"

    def _call(self, ctx_app, path: str, addr: str | None = None):
        from app_setup.security_middleware import _apply_token_bucket_limits

        if addr is None:
            addr = self._TEST_ADDR
        with ctx_app.app_context():
            return _apply_token_bucket_limits(path, addr)

    def _drained_bucket(self, addr: str | None = None):
        """Return a TokenBucket(capacity=1) already drained for *addr*."""
        from utils.rate_limit import TokenBucket

        if addr is None:
            addr = self._TEST_ADDR
        b = TokenBucket(capacity=1, refill_rate=0)
        b.try_acquire(addr)  # consume the single token for the target key
        return b

    def test_auth_path_allowed_returns_none(self, ctx_app):
        assert self._call(ctx_app, "/login") is None

    def test_auth_path_exhausted_returns_429(self, ctx_app):
        import app_setup.security_middleware as mw

        mw._auth_bucket = self._drained_bucket()
        resp = self._call(ctx_app, "/login")
        assert resp is not None
        assert resp.status_code == 429

    def test_auth_path_exhausted_has_retry_after_30(self, ctx_app):
        import app_setup.security_middleware as mw

        mw._auth_bucket = self._drained_bucket()
        resp = self._call(ctx_app, "/login")
        assert resp.headers.get("Retry-After") == "30"

    def test_refresh_path_allowed_returns_none(self, ctx_app):
        assert self._call(ctx_app, "/display-next") is None
        assert self._call(ctx_app, "/refresh") is None

    def test_refresh_path_exhausted_returns_429(self, ctx_app):
        import app_setup.security_middleware as mw

        mw._refresh_bucket = self._drained_bucket()
        resp = self._call(ctx_app, "/display-next")
        assert resp is not None
        assert resp.status_code == 429

    def test_refresh_path_exhausted_has_retry_after_6(self, ctx_app):
        import app_setup.security_middleware as mw

        mw._refresh_bucket = self._drained_bucket()
        resp = self._call(ctx_app, "/display-next")
        assert resp.headers.get("Retry-After") == "6"

    def test_mutating_path_allowed_returns_none(self, ctx_app):
        assert self._call(ctx_app, "/update_now") is None
        assert self._call(ctx_app, "/save_plugin_settings") is None
        assert self._call(ctx_app, "/api/refresh/all") is None

    def test_mutating_path_exhausted_returns_429(self, ctx_app):
        import app_setup.security_middleware as mw

        mw._mutating_bucket = self._drained_bucket()
        resp = self._call(ctx_app, "/update_now")
        assert resp is not None
        assert resp.status_code == 429

    def test_mutating_path_exhausted_has_retry_after_6(self, ctx_app):
        import app_setup.security_middleware as mw

        mw._mutating_bucket = self._drained_bucket()
        resp = self._call(ctx_app, "/update_now")
        assert resp.headers.get("Retry-After") == "6"

    def test_mutating_path_exhausted_has_json_error_body(self, ctx_app):
        import app_setup.security_middleware as mw

        mw._mutating_bucket = self._drained_bucket()
        resp = self._call(ctx_app, "/update_now")
        data = resp.get_json()
        assert data is not None
        assert "error" in data

    def test_unknown_path_returns_none(self, ctx_app):
        assert self._call(ctx_app, "/api/logs") is None

    def test_different_ips_tracked_independently(self, ctx_app):
        import app_setup.security_middleware as mw
        from utils.rate_limit import TokenBucket

        # capacity=1: first call for new key consumes the 1 token (returns True)
        # second call for same key → denied (returns False)
        mw._mutating_bucket = TokenBucket(capacity=1, refill_rate=0)
        # First call for ip-a succeeds
        assert self._call(ctx_app, "/update_now", "10.0.0.1") is None
        # Second call for ip-a is denied
        assert self._call(ctx_app, "/update_now", "10.0.0.1") is not None
        # ip-b still has its own fresh bucket
        assert self._call(ctx_app, "/update_now", "10.0.0.2") is None


# ---------------------------------------------------------------------------
# setup_rate_limiting integration (through Flask app)
# ---------------------------------------------------------------------------


@pytest.fixture()
def middleware_app():
    """Flask app with the real setup_rate_limiting wired up (JTN-513)."""
    from app_setup.security_middleware import setup_rate_limiting

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True

    setup_rate_limiting(app)

    @app.route("/update_now", methods=["POST"])
    def update_now():
        return {"ok": True}

    @app.route("/save_plugin_settings", methods=["POST"])
    def save_plugin_settings():
        return {"ok": True}

    @app.route("/login", methods=["POST"])
    def login():
        return {"ok": True}

    @app.route("/healthz", methods=["GET", "POST"])
    def healthz():
        return {"ok": True}

    return app


class TestSetupRateLimitingIntegration:
    """Integration tests verifying setup_rate_limiting applies the mutating bucket."""

    def test_update_now_burst_then_429(self, middleware_app, monkeypatch):
        """POST /update_now → first 10 succeed, 11th returns 429."""
        import app_setup.security_middleware as mw
        from utils.rate_limit import TokenBucket

        # Replace bucket with a zero-refill one for determinism
        mw._mutating_bucket = TokenBucket(capacity=10, refill_rate=0)
        client = middleware_app.test_client()
        for _ in range(10):
            resp = client.post("/update_now")
            assert resp.status_code == 200
        resp = client.post("/update_now")
        assert resp.status_code == 429

    def test_save_plugin_settings_burst_then_429(self, middleware_app, monkeypatch):
        import app_setup.security_middleware as mw
        from utils.rate_limit import TokenBucket

        mw._mutating_bucket = TokenBucket(capacity=10, refill_rate=0)
        client = middleware_app.test_client()
        for _ in range(10):
            client.post("/save_plugin_settings")
        resp = client.post("/save_plugin_settings")
        assert resp.status_code == 429

    def test_healthz_get_not_rate_limited(self, middleware_app):
        client = middleware_app.test_client()
        for _ in range(20):
            resp = client.get("/healthz")
            assert resp.status_code == 200

    def test_429_response_has_retry_after_header(self, middleware_app):
        import app_setup.security_middleware as mw
        from utils.rate_limit import TokenBucket

        # Use capacity=1, zero refill; first call drains the token, second gets 429
        mw._mutating_bucket = TokenBucket(capacity=1, refill_rate=0)
        client = middleware_app.test_client()
        client.post("/update_now")  # consumes the single token
        resp = client.post("/update_now")  # denied
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "6"
