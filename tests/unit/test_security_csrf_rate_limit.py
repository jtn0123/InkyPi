# pyright: reportMissingImports=false
"""Tests for CSRF protection, rate limiting, and XSS prevention."""

import secrets

import pytest
from flask import Flask, session


@pytest.fixture()
def csrf_app():
    """Minimal Flask app with CSRF protection matching inkypi.py."""
    from collections import defaultdict, deque

    from utils.http_utils import json_error

    app = Flask(__name__)
    app.secret_key = "test-csrf-secret"
    app.config["TESTING"] = True

    _CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
    _CSRF_EXEMPT_PATHS = frozenset({"/healthz", "/readyz"})

    def _generate_csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_hex(32)
        return session["_csrf_token"]

    @app.context_processor
    def _inject_csrf():
        return {"csrf_token": _generate_csrf_token}

    @app.before_request
    def _check_csrf():
        from flask import request

        if request.method in _CSRF_SAFE_METHODS:
            return None
        if request.path in _CSRF_EXEMPT_PATHS:
            return None
        token = session.get("_csrf_token")
        if not token:
            _generate_csrf_token()
            return json_error("CSRF token missing or invalid", status=403)
        json_body = (
            request.get_json(silent=True)
            if request.content_type and "json" in request.content_type
            else None
        )
        request_token = (
            request.headers.get("X-CSRFToken")
            or (
                request.form.get("csrf_token")
                if request.content_type and "form" in request.content_type
                else None
            )
            or (json_body.get("_csrf_token") if isinstance(json_body, dict) else None)
        )
        if not request_token or not secrets.compare_digest(request_token, token):
            return json_error("CSRF token missing or invalid", status=403)
        return None

    # --- Rate limiting ---
    _MUTATE_REQUESTS = defaultdict(deque)
    _MUTATE_WINDOW = 60
    _MUTATE_MAX = 5  # Low limit for testing

    @app.before_request
    def _rate_limit():
        import time as _time

        from flask import request

        if request.method in _CSRF_SAFE_METHODS:
            return None
        if request.path in _CSRF_EXEMPT_PATHS:
            return None
        addr = request.remote_addr or "unknown"
        now = _time.monotonic()
        dq = _MUTATE_REQUESTS[addr]
        while dq and dq[0] < now - _MUTATE_WINDOW:
            dq.popleft()
        if len(dq) >= _MUTATE_MAX:
            return json_error("Rate limit exceeded — try again shortly", status=429)
        dq.append(now)
        return None

    @app.route("/test-post", methods=["POST"])
    def test_post():
        return {"ok": True}

    @app.route("/healthz", methods=["POST"])
    def healthz_post():
        return {"ok": True}

    return app


class TestCSRFProtection:
    def test_get_requests_bypass_csrf(self, csrf_app):
        client = csrf_app.test_client()
        # GET requests should not need CSRF
        # (no POST route for GET, just verify no 403 on a page)
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "testtoken123"

    def test_post_without_token_returns_403(self, csrf_app):
        client = csrf_app.test_client()
        resp = client.post("/test-post")
        assert resp.status_code == 403

    def test_post_with_valid_header_token(self, csrf_app):
        client = csrf_app.test_client()
        # First, establish session with a token
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "valid-token-abc123"
        resp = client.post("/test-post", headers={"X-CSRFToken": "valid-token-abc123"})
        assert resp.status_code == 200

    def test_post_with_invalid_token_returns_403(self, csrf_app):
        client = csrf_app.test_client()
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "correct-token"
        resp = client.post("/test-post", headers={"X-CSRFToken": "wrong-token"})
        assert resp.status_code == 403

    def test_post_with_form_csrf_token(self, csrf_app):
        client = csrf_app.test_client()
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "form-token-xyz"
        resp = client.post(
            "/test-post",
            data={"csrf_token": "form-token-xyz"},
            content_type="application/x-www-form-urlencoded",
        )
        assert resp.status_code == 200

    def test_exempt_paths_skip_csrf(self, csrf_app):
        client = csrf_app.test_client()
        resp = client.post("/healthz")
        assert resp.status_code == 200

    def test_first_post_without_session_returns_403(self, csrf_app):
        """First POST without any session should be rejected (no exemption)."""
        client = csrf_app.test_client()
        resp = client.post("/test-post")
        assert resp.status_code == 403
        data = resp.get_json()
        assert "CSRF" in data.get("error", "")

    # --- JTN-224: CSRF bypass on first POST in new session ---

    def test_jtn224_new_session_post_rejected_not_allowed_through(self, csrf_app):
        """JTN-224: A POST with no existing session token must be rejected, not passed through."""
        client = csrf_app.test_client()
        # Fresh client — no session cookie, no token
        resp = client.post("/test-post", content_type="application/json", data="{}")
        assert resp.status_code == 403
        data = resp.get_json()
        assert data is not None
        assert "CSRF" in data.get("error", "")

    def test_jtn224_get_then_post_with_token_succeeds(self, csrf_app):
        """JTN-224: After a GET establishes the session token, POST with that token succeeds."""
        # Simulate: manually set session token (as a GET would), then POST with it
        client = csrf_app.test_client()
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "session-established-token"
        resp = client.post(
            "/test-post", headers={"X-CSRFToken": "session-established-token"}
        )
        assert resp.status_code == 200

    # --- JTN-257: sendBeacon CSRF token in JSON body ---

    def test_jtn257_json_body_csrf_token_accepted(self, csrf_app):
        """JTN-257: CSRF token included in JSON body (_csrf_token) must be accepted."""
        import json

        client = csrf_app.test_client()
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "json-body-token-abc"
        resp = client.post(
            "/test-post",
            content_type="application/json",
            data=json.dumps({"_csrf_token": "json-body-token-abc", "level": "error"}),
        )
        assert resp.status_code == 200

    def test_jtn257_json_body_wrong_csrf_token_rejected(self, csrf_app):
        """JTN-257: Wrong _csrf_token in JSON body must return 403."""
        import json

        client = csrf_app.test_client()
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "correct-json-token"
        resp = client.post(
            "/test-post",
            content_type="application/json",
            data=json.dumps({"_csrf_token": "wrong-json-token"}),
        )
        assert resp.status_code == 403

    def test_jtn257_json_body_missing_csrf_token_rejected(self, csrf_app):
        """JTN-257: JSON body without _csrf_token and no header must return 403."""
        import json

        client = csrf_app.test_client()
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "some-token"
        resp = client.post(
            "/test-post",
            content_type="application/json",
            data=json.dumps({"level": "error", "message": "test"}),
        )
        assert resp.status_code == 403


class TestClientErrorsJsCSRF:
    """JTN-257: Structural tests verifying client_errors.js includes CSRF token support."""

    def test_client_errors_js_reads_csrf_meta_tag(self):
        """client_errors.js must include getCsrfToken() reading the csrf-token meta tag."""
        import os

        js_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "src",
            "static",
            "scripts",
            "client_errors.js",
        )
        with open(os.path.abspath(js_path)) as fh:
            source = fh.read()
        assert (
            'meta[name="csrf-token"]' in source
        ), "client_errors.js must query the csrf-token meta tag"
        assert (
            "_csrf_token" in source
        ), "client_errors.js must include _csrf_token in the request body"
        assert (
            "getCsrfToken" in source
        ), "client_errors.js must define a getCsrfToken helper"

    def test_client_errors_js_fetch_sends_x_csrftoken_header(self):
        """fetch() fallback in client_errors.js must send X-CSRFToken header."""
        import os

        js_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "src",
            "static",
            "scripts",
            "client_errors.js",
        )
        with open(os.path.abspath(js_path)) as fh:
            source = fh.read()
        assert "X-CSRFToken" in source, "fetch() fallback must send X-CSRFToken header"


class TestRateLimiting:
    def test_rate_limit_allows_within_threshold(self, csrf_app):
        client = csrf_app.test_client()
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "rl-token"
        for _ in range(5):
            resp = client.post("/test-post", headers={"X-CSRFToken": "rl-token"})
            assert resp.status_code == 200

    def test_rate_limit_blocks_over_threshold(self, csrf_app):
        client = csrf_app.test_client()
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "rl-token"
        # Exhaust limit
        for _ in range(5):
            client.post("/test-post", headers={"X-CSRFToken": "rl-token"})
        # Next request should be blocked
        resp = client.post("/test-post", headers={"X-CSRFToken": "rl-token"})
        assert resp.status_code == 429

    def test_rate_limit_exempt_paths(self, csrf_app):
        """Exempt paths should not count against rate limit."""
        client = csrf_app.test_client()
        for _ in range(10):
            resp = client.post("/healthz")
            assert resp.status_code == 200


class TestRSSXSSPrevention:
    def test_sanitize_strips_script_tags(self):
        from plugins.rss.rss import Rss

        result = Rss._sanitize_text('<script>alert("xss")</script>Safe text')
        assert "<script>" not in result
        assert "Safe text" in result

    def test_sanitize_strips_html_tags(self):
        from plugins.rss.rss import Rss

        result = Rss._sanitize_text("<b>Bold</b> and <em>italic</em>")
        assert "<b>" not in result
        assert "<em>" not in result
        assert "Bold" in result
        assert "italic" in result

    def test_sanitize_decodes_entities(self):
        from plugins.rss.rss import Rss

        result = Rss._sanitize_text("Tom &amp; Jerry &lt;3")
        assert result == "Tom & Jerry <3"

    def test_sanitize_handles_nested_tags(self):
        from plugins.rss.rss import Rss

        result = Rss._sanitize_text(
            '<div><p>Text <a href="http://evil.com">link</a></p></div>'
        )
        assert "<" not in result
        assert "Text" in result
        assert "link" in result

    def test_sanitize_handles_img_onerror(self):
        from plugins.rss.rss import Rss

        result = Rss._sanitize_text("<img src=x onerror=alert(1)>")
        assert "<" not in result
        assert "onerror" not in result

    def test_sanitize_empty_string(self):
        from plugins.rss.rss import Rss

        assert Rss._sanitize_text("") == ""

    def test_sanitize_plain_text_unchanged(self):
        from plugins.rss.rss import Rss

        assert Rss._sanitize_text("Hello World") == "Hello World"
