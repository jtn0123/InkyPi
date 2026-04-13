# pyright: reportMissingImports=false
"""Regression tests: /api/client-log must not reflect tainted input in
response bodies (CodeQL py/reflective-xss, JTN-326).

The blueprint validates the ``level`` field against a small allow-list. A
previous implementation echoed the rejected value back inside an f-string
error message, which CodeQL flagged as a reflective-xss sink even though
``json_error`` emits ``application/json``. These tests post crafted
payloads and assert the raw value never appears in the response body.
"""

from __future__ import annotations

import importlib
import json

import pytest
from flask import Flask


def _make_app() -> Flask:
    import blueprints.client_log as cl_mod

    # Reload to reset the per-module rate limiter between tests.
    importlib.reload(cl_mod)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(cl_mod.client_log_bp)
    return app


@pytest.fixture()
def client():
    return _make_app().test_client()


_XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<svg onload=alert(1)>",
    "javascript:alert(1)",
    '"><script>alert(1)</script>',
    "'><script>alert(1)</script>",
]


@pytest.mark.parametrize("payload", _XSS_PAYLOADS)
def test_invalid_level_not_reflected(client, payload: str) -> None:
    """An invalid ``level`` value must not appear verbatim in the response."""
    resp = client.post(
        "/api/client-log",
        data=json.dumps({"level": payload, "message": "x"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert payload not in body
    # Response must declare JSON content-type (defence-in-depth).
    assert resp.content_type.startswith("application/json")
    # The generic error message is still present for UX.
    parsed = json.loads(body)
    assert "Invalid level" in parsed.get("error", "")


def test_invalid_level_missing_still_rejected(client) -> None:
    """Empty level (default) triggers the same branch without reflection."""
    resp = client.post(
        "/api/client-log",
        data=json.dumps({"message": "x"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.content_type.startswith("application/json")


def test_invalid_level_logs_sanitized_value(client, caplog) -> None:
    """The rejected value is logged (sanitized) for debugging."""
    import logging

    payload = "<script>alert(1)</script>"
    with caplog.at_level(logging.WARNING, logger="blueprints.client_log"):
        resp = client.post(
            "/api/client-log",
            data=json.dumps({"level": payload}),
            content_type="application/json",
        )
    assert resp.status_code == 400
    # Sanitized form reaches the log (SecretRedactionFilter / sanitize_log_field
    # strip control chars but leave printable HTML intact — the point is that
    # the string never reaches the HTTP response body).
    assert any("invalid level" in rec.getMessage().lower() for rec in caplog.records)
