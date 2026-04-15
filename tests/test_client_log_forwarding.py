# pyright: reportMissingImports=false
"""Tests for the /api/client-log blueprint (JTN-481).

Coverage:
- POST valid JSON returns 204 and logs the report
- Invalid level returns 400
- GET returns 405
- Oversized body returns 413
- Rate limit triggers 429
- CR/LF in message is stripped (Sonar S5145)
- Logged with the right level prefix
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


def _make_app() -> Flask:
    """Build a minimal Flask app with the client_log blueprint registered."""
    import blueprints.client_log as cl_mod

    # Reset the rate limiter between test app builds so tests are independent.
    importlib.reload(cl_mod)

    app = Flask(__name__)
    app.config["TESTING"] = True

    from blueprints.client_log import client_log_bp

    app.register_blueprint(client_log_bp)
    return app


@pytest.fixture()
def cl_client():
    """Flask test client for the client_log blueprint."""
    app = _make_app()
    return app.test_client()


def _post(client, payload: dict | None = None, *, body: bytes | None = None):
    """POST to /api/client-log with JSON payload or raw body."""
    if body is not None:
        return client.post(
            "/api/client-log",
            data=body,
            content_type="application/json",
        )
    return client.post(
        "/api/client-log",
        data=json.dumps(payload),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


class TestPostValidJson:
    def test_warn_returns_204(self, cl_client):
        resp = _post(cl_client, {"level": "warn", "message": "something may be wrong"})
        assert resp.status_code == 204

    def test_error_returns_204(self, cl_client):
        resp = _post(cl_client, {"level": "error", "message": "something broke"})
        assert resp.status_code == 204

    def test_empty_response_body(self, cl_client):
        resp = _post(cl_client, {"level": "warn", "message": "test"})
        assert resp.data == b""

    def test_all_accepted_fields_logged(self, cl_client, caplog):
        payload = {
            "level": "error",
            "message": "TypeError: x is undefined",
            "args": "extra arg",
            "url": "/dashboard",
            "ts": "2026-04-08T12:00:00.000Z",
        }
        with caplog.at_level(logging.WARNING, logger="blueprints.client_log"):
            resp = _post(cl_client, payload)
        assert resp.status_code == 204
        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("TypeError: x is undefined" in m for m in warning_msgs)


# ---------------------------------------------------------------------------
# Level validation
# ---------------------------------------------------------------------------


class TestInvalidLevel:
    def test_info_level_returns_400(self, cl_client):
        resp = _post(cl_client, {"level": "info", "message": "just info"})
        assert resp.status_code == 400

    def test_debug_level_returns_400(self, cl_client):
        resp = _post(cl_client, {"level": "debug", "message": "debug message"})
        assert resp.status_code == 400

    def test_unknown_level_returns_400(self, cl_client):
        resp = _post(cl_client, {"level": "verbose", "message": "verbose"})
        assert resp.status_code == 400

    def test_missing_level_returns_400(self, cl_client):
        resp = _post(cl_client, {"message": "no level"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Method validation
# ---------------------------------------------------------------------------


class TestGetReturns405:
    def test_get_returns_405(self, cl_client):
        resp = cl_client.get("/api/client-log")
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Body size limits
# ---------------------------------------------------------------------------


class TestOversizedBody:
    def test_body_over_limit_returns_413(self, cl_client):
        """Bodies over the 256 KB cap (JTN-711 raised to fit batches) → 413."""
        giant_message = "x" * (300 * 1024)
        body = json.dumps({"level": "warn", "message": giant_message}).encode()
        assert len(body) > 256 * 1024
        resp = _post(cl_client, body=body)
        assert resp.status_code == 413

    def test_body_under_limit_accepted(self, cl_client):
        resp = _post(cl_client, {"level": "warn", "message": "normal log"})
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_rate_limit_kicks_in_after_capacity(self):
        """After exhausting 60-token burst capacity the next request returns 429 (JTN-711)."""
        import blueprints.client_log as cl_mod

        importlib.reload(cl_mod)
        app = Flask(__name__)
        app.config["TESTING"] = True
        from blueprints.client_log import client_log_bp

        app.register_blueprint(client_log_bp)
        c = app.test_client()

        # First 60 requests should succeed (capacity = 60, JTN-711)
        for _ in range(60):
            resp = _post(c, {"level": "warn", "message": "log"})
            assert resp.status_code == 204

        # The 61st request should be rate-limited
        resp = _post(c, {"level": "warn", "message": "log"})
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# CR/LF stripping
# ---------------------------------------------------------------------------


class TestNewlineStripping:
    def test_cr_lf_in_message_is_stripped(self, cl_client, caplog):
        """CR and LF characters in message must be replaced to prevent log injection."""
        payload = {
            "level": "warn",
            "message": "line one\r\ninjected line\nthird line",
        }
        with caplog.at_level(logging.WARNING, logger="blueprints.client_log"):
            resp = _post(cl_client, payload)
        assert resp.status_code == 204
        warning_msgs = " ".join(
            r.message for r in caplog.records if r.levelno == logging.WARNING
        )
        assert "\r" not in warning_msgs
        assert "\n" not in warning_msgs

    def test_cr_lf_in_args_is_stripped(self, cl_client, caplog):
        payload = {
            "level": "error",
            "message": "test",
            "args": "arg with\r\nnewline",
        }
        with caplog.at_level(logging.WARNING, logger="blueprints.client_log"):
            resp = _post(cl_client, payload)
        assert resp.status_code == 204
        warning_msgs = " ".join(
            r.message for r in caplog.records if r.levelno == logging.WARNING
        )
        assert "\r" not in warning_msgs
        assert "\n" not in warning_msgs


# ---------------------------------------------------------------------------
# Log level prefix
# ---------------------------------------------------------------------------


class TestLogLevelPrefix:
    def test_warn_logged_with_warn_prefix(self, cl_client, caplog):
        with caplog.at_level(logging.WARNING, logger="blueprints.client_log"):
            resp = _post(cl_client, {"level": "warn", "message": "test warn"})
        assert resp.status_code == 204
        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("client log [warn]" in m for m in warning_msgs)

    def test_error_logged_with_error_prefix(self, cl_client, caplog):
        with caplog.at_level(logging.WARNING, logger="blueprints.client_log"):
            resp = _post(cl_client, {"level": "error", "message": "test error"})
        assert resp.status_code == 204
        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("client log [error]" in m for m in warning_msgs)
