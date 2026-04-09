# pyright: reportMissingImports=false
"""Tests for the /api/client-error blueprint (JTN-454).

Coverage:
- POST valid JSON returns 204 and logs the report
- GET returns 405
- Oversized body returns 413
- Missing required field returns 400
- Rate limit kicks in after capacity
- Secrets in stack trace are redacted in the log output
"""

from __future__ import annotations

import importlib
import json
import logging

import pytest
from flask import Flask  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SRC_ABS = __import__("os").path.abspath(
    __import__("os").path.join(__import__("os").path.dirname(__file__), "..", "src")
)


def _make_app() -> Flask:
    """Build a minimal Flask app with the client_error blueprint registered."""
    import blueprints.client_error as ce_mod

    # Reset the rate limiter between test app builds so tests are independent.
    importlib.reload(ce_mod)

    app = Flask(__name__)
    app.config["TESTING"] = True

    from blueprints.client_error import client_error_bp

    app.register_blueprint(client_error_bp)
    return app


@pytest.fixture()
def ce_client():
    """Flask test client for the client_error blueprint."""
    app = _make_app()
    return app.test_client()


@pytest.fixture()
def fresh_ce_client():
    """Re-import module each time so rate-limiter starts fresh."""
    app = _make_app()
    return app.test_client()


def _post(client, payload: dict | None = None, *, body: bytes | None = None):
    """POST to /api/client-error with JSON payload or raw body."""
    if body is not None:
        return client.post(
            "/api/client-error",
            data=body,
            content_type="application/json",
        )
    return client.post(
        "/api/client-error",
        data=json.dumps(payload),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


class TestPostValidJson:
    def test_returns_204(self, ce_client):
        resp = _post(ce_client, {"message": "TypeError: x is undefined"})
        assert resp.status_code == 204

    def test_logs_report_as_warning(self, ce_client, caplog):
        with caplog.at_level(logging.WARNING, logger="blueprints.client_error"):
            resp = _post(ce_client, {"message": "something broke"})
        assert resp.status_code == 204
        assert any(
            "client error" in rec.message and "something broke" in rec.message
            for rec in caplog.records
        )

    def test_all_accepted_fields_logged(self, ce_client, caplog):
        payload = {
            "message": "ReferenceError: foo is not defined",
            "source": "/static/scripts/app.js",
            "line": 42,
            "column": 7,
            "stack": "ReferenceError: foo\n  at <anonymous>:42:7",
            "user_agent": "Mozilla/5.0",
            "url": "/dashboard",
        }
        with caplog.at_level(logging.WARNING, logger="blueprints.client_error"):
            resp = _post(ce_client, payload)
        assert resp.status_code == 204
        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("ReferenceError" in m for m in warning_msgs)

    def test_empty_response_body(self, ce_client):
        resp = _post(ce_client, {"message": "boom"})
        assert resp.data == b""


# ---------------------------------------------------------------------------
# Method validation
# ---------------------------------------------------------------------------


class TestGetReturns405:
    def test_get_returns_405(self, ce_client):
        resp = ce_client.get("/api/client-error")
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Body size limits
# ---------------------------------------------------------------------------


class TestOversizedBody:
    def test_body_over_16kb_returns_413(self, ce_client):
        # Build a body that exceeds 16 384 bytes
        giant_message = "x" * 20_000
        body = json.dumps({"message": giant_message}).encode()
        assert len(body) > 16_384
        resp = _post(ce_client, body=body)
        assert resp.status_code == 413

    def test_body_under_limit_accepted(self, ce_client):
        normal_message = "normal error"
        resp = _post(ce_client, {"message": normal_message})
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestMissingRequiredFields:
    def test_missing_message_returns_400(self, ce_client):
        resp = _post(ce_client, {"source": "/app.js", "line": 10})
        assert resp.status_code == 400

    def test_empty_object_returns_400(self, ce_client):
        resp = _post(ce_client, {})
        assert resp.status_code == 400

    def test_non_object_body_returns_400(self, ce_client):
        body = json.dumps(["list", "not", "object"]).encode()
        resp = _post(ce_client, body=body)
        assert resp.status_code == 400

    def test_invalid_json_returns_400(self, ce_client):
        resp = _post(ce_client, body=b"{not valid json}")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_rate_limit_kicks_in_after_capacity(self):
        """After exhausting 5-token burst capacity the next request returns 429."""
        # Reload module so we get a clean rate limiter.
        import blueprints.client_error as ce_mod

        importlib.reload(ce_mod)
        app = Flask(__name__)
        app.config["TESTING"] = True
        from blueprints.client_error import client_error_bp

        app.register_blueprint(client_error_bp)
        c = app.test_client()

        # First 5 requests should succeed (capacity = 5)
        for _ in range(5):
            resp = _post(c, {"message": "err"})
            assert resp.status_code == 204

        # The 6th request should be rate-limited
        resp = _post(c, {"message": "err"})
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


class TestSecretRedactionInLogs:
    def test_api_key_in_stack_is_redacted(self, ce_client, caplog):
        """Secrets embedded in stack traces must be stripped before hitting logs."""
        # Wire up the redaction filter the same way production does.
        from utils.logging_utils import SecretRedactionFilter

        ce_logger = logging.getLogger("blueprints.client_error")
        redaction_filter = SecretRedactionFilter()
        ce_logger.addFilter(redaction_filter)
        try:
            stack_with_secret = (
                "Error at api_key=TOPSECRET123456789012 in app.js"  # gitleaks:allow
            )
            payload = {
                "message": "something failed",
                "stack": stack_with_secret,
            }
            with caplog.at_level(logging.WARNING, logger="blueprints.client_error"):
                resp = _post(ce_client, payload)
            assert resp.status_code == 204

            warning_messages = " ".join(
                r.message for r in caplog.records if r.levelno == logging.WARNING
            )
            # The raw secret value must not appear in logs.
            assert "TOPSECRET123456789012" not in warning_messages
            assert "***REDACTED***" in warning_messages
        finally:
            ce_logger.removeFilter(redaction_filter)

    def test_bearer_token_in_message_is_redacted(self, ce_client, caplog):
        from utils.logging_utils import SecretRedactionFilter

        ce_logger = logging.getLogger("blueprints.client_error")
        redaction_filter = SecretRedactionFilter()
        ce_logger.addFilter(redaction_filter)
        try:
            payload = {
                "message": "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.sig",
            }
            with caplog.at_level(logging.WARNING, logger="blueprints.client_error"):
                resp = _post(ce_client, payload)
            assert resp.status_code == 204

            warning_messages = " ".join(
                r.message for r in caplog.records if r.levelno == logging.WARNING
            )
            assert "eyJhbGciOiJSUzI1NiJ9" not in warning_messages
            assert "***REDACTED***" in warning_messages
        finally:
            ce_logger.removeFilter(redaction_filter)
