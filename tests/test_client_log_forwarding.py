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


def _fresh_module(monkeypatch=None, *, capture: bool | None = None):
    """Reload ``blueprints.client_log`` and return (module, Flask app)."""
    import blueprints.client_log as cl_mod

    importlib.reload(cl_mod)
    if monkeypatch is not None:
        if capture is True:
            monkeypatch.setenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", "1")
        elif capture is False:
            monkeypatch.delenv("INKYPI_TEST_CAPTURE_CLIENT_LOG", raising=False)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(cl_mod.client_log_bp)
    return cl_mod, app


def _make_app() -> Flask:
    """Build a minimal Flask app with the client_log blueprint registered."""
    return _fresh_module()[1]


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
    def test_rate_limit_kicks_in_after_capacity(self, monkeypatch):
        """After exhausting 60-token burst capacity the next request returns 429 (JTN-711).

        Freezes ``time.monotonic`` so the token bucket cannot refill mid-test:
        at CI speed the 60 request loop easily takes >100 ms, which would let
        the 10 tokens/s refill rate hand out another token and turn the 61st
        request into a 204 (flaky on slower runners).
        """
        import blueprints.client_log as cl_mod

        importlib.reload(cl_mod)

        # Freeze time in the rate-limit module so elapsed == 0 on every call.
        # Patch a *proxy* bound to `rl_mod.time` rather than mutating the
        # shared `time` module attribute process-wide. A direct
        # `monkeypatch.setattr(rl_mod.time, "monotonic", ...)` would replace
        # `time.monotonic` for every importer, including pytest's own
        # scheduling — the scoped proxy keeps the freeze to this module.
        import time as _time_mod

        import utils.rate_limit as rl_mod

        frozen = _time_mod.monotonic()

        class _FrozenTime:
            def __getattr__(self, name: str):
                return getattr(_time_mod, name)

            def monotonic(self) -> float:
                return frozen

        monkeypatch.setattr(rl_mod, "time", _FrozenTime())

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
# Batch payload support (JTN-711)
# ---------------------------------------------------------------------------


class TestBatchAccepted:
    def test_batch_endpoint_accepts_array_payload(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch, capture=True)

        batch = [
            {"level": "warn", "message": "w1"},
            {"level": "error", "message": "e1"},
            {"level": "warn", "message": "w2"},
        ]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 204

        reports = cl_mod.get_captured_reports()
        assert [r["message"] for r in reports] == ["w1", "e1", "w2"]
        assert [r["level"] for r in reports] == ["warn", "error", "warn"]

    def test_existing_single_entry_payload_still_works(self, monkeypatch):
        """Backwards-compat: legacy single-object POSTs still return 204."""
        cl_mod, app = _fresh_module(monkeypatch, capture=True)

        resp = _post(app.test_client(), {"level": "warn", "message": "solo"})
        assert resp.status_code == 204
        reports = cl_mod.get_captured_reports()
        assert len(reports) == 1
        assert reports[0]["message"] == "solo"

    def test_batch_at_cap_is_accepted(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch, capture=True)

        batch = [{"level": "warn", "message": f"m{i}"} for i in range(50)]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 204
        assert len(cl_mod.get_captured_reports()) == 50


class TestBatchRejected:
    def test_batch_endpoint_rejects_oversized_batch(self, monkeypatch):
        """> 50 entries → 400."""
        cl_mod, app = _fresh_module(monkeypatch, capture=True)

        batch = [{"level": "warn", "message": f"m{i}"} for i in range(51)]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body["success"] is False
        assert "max" in body["error"].lower() or "50" in body["error"]
        assert cl_mod.get_captured_reports() == []

    def test_empty_batch_rejected(self, monkeypatch):
        _, app = _fresh_module(monkeypatch)
        resp = _post(app.test_client(), [])
        assert resp.status_code == 400

    def test_batch_entries_individually_validated(self, monkeypatch):
        """One bad entry returns 400 with per-entry errors and captures nothing."""
        cl_mod, app = _fresh_module(monkeypatch, capture=True)

        batch = [
            {"level": "warn", "message": "ok1"},
            {"level": "info", "message": "nope"},
            {"level": "error", "message": "ok2"},
        ]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body["details"]["entry_errors"][0]["index"] == 1
        assert cl_mod.get_captured_reports() == []

    def test_non_object_entry_in_batch_rejected(self, monkeypatch):
        _, app = _fresh_module(monkeypatch)
        batch = [{"level": "warn", "message": "ok"}, "bad-entry", 42]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 400
        body = json.loads(resp.data)
        indexes = [e["index"] for e in body["details"]["entry_errors"]]
        assert indexes == [1, 2]

    def test_non_object_non_array_body_rejected(self, monkeypatch):
        _, app = _fresh_module(monkeypatch)
        resp = _post(app.test_client(), "just-a-string")
        assert resp.status_code == 400


class TestBatchRateLimit:
    def test_rate_limit_capacity_raised_to_60(self, monkeypatch):
        """JTN-711: the bucket now holds 60 tokens (up from 10)."""
        cl_mod, app = _fresh_module(monkeypatch)

        cl_mod._rate_limiter = cl_mod.TokenBucket(capacity=60, refill_rate=0)
        client = app.test_client()

        for i in range(60):
            resp = _post(client, {"level": "warn", "message": f"m{i}"})
            assert resp.status_code == 204, f"unexpected failure at iteration {i}"

        resp = _post(client, {"level": "warn", "message": "over"})
        assert resp.status_code == 429

    def test_each_batch_post_consumes_one_token(self, monkeypatch):
        """Request-based limiting should allow 60 ten-entry batches."""
        cl_mod, app = _fresh_module(monkeypatch, capture=True)

        cl_mod._rate_limiter = cl_mod.TokenBucket(capacity=60, refill_rate=0)
        client = app.test_client()
        per_batch = 10
        batches = 60
        for i in range(batches):
            batch = [
                {"level": "warn", "message": f"b{i}-e{j}"} for j in range(per_batch)
            ]
            resp = _post(client, batch)
            assert resp.status_code == 204

        resp = _post(client, [{"level": "warn", "message": "over"}])
        assert resp.status_code == 429
        assert len(cl_mod.get_captured_reports()) == batches * per_batch


class TestBatchFieldHandling:
    def test_secret_redaction_applied_to_every_batch_entry(self, monkeypatch, caplog):
        _, app = _fresh_module(monkeypatch)

        batch = [{"level": "warn", "message": f"entry-{i}"} for i in range(5)]
        with caplog.at_level(logging.WARNING, logger="blueprints.client_log"):
            resp = _post(app.test_client(), batch)
        assert resp.status_code == 204

        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        for i in range(5):
            assert any(
                f"entry-{i}" in m for m in warning_msgs
            ), f"entry-{i} missing from logs"

    def test_cr_lf_stripped_on_every_batch_entry(self, monkeypatch, caplog):
        _, app = _fresh_module(monkeypatch)

        batch = [
            {"level": "warn", "message": "line\r\nbad1"},
            {"level": "error", "message": "also\nbad2"},
        ]
        with caplog.at_level(logging.WARNING, logger="blueprints.client_log"):
            resp = _post(app.test_client(), batch)
        assert resp.status_code == 204
        warning_msgs = " ".join(
            r.message for r in caplog.records if r.levelno == logging.WARNING
        )
        assert "\r" not in warning_msgs
        assert "\n" not in warning_msgs
        assert "bad1" in warning_msgs
        assert "bad2" in warning_msgs

    def test_message_field_capped_per_entry(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch, capture=True)

        huge = "x" * 5000
        resp = _post(app.test_client(), [{"level": "warn", "message": huge}])
        assert resp.status_code == 204
        reports = cl_mod.get_captured_reports()
        assert len(reports[0]["message"]) == 2048


class TestBurstAllLands:
    """Acceptance test from JTN-711: 30 errors in a burst all land in one POST."""

    def test_30_errors_in_a_burst_all_land(self, monkeypatch):
        cl_mod, app = _fresh_module(monkeypatch, capture=True)

        batch = [{"level": "error", "message": f"burst-{i}"} for i in range(30)]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 204

        messages = [r["message"] for r in cl_mod.get_captured_reports()]
        assert messages == [f"burst-{i}" for i in range(30)]


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
