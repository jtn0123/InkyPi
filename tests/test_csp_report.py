# pyright: reportMissingImports=false
"""Tests for the CSP violation report endpoint (POST /api/csp-report).

Coverage:
- POST with sample CSP report JSON returns 204
- Report body is logged via logger.warning
- Accepts application/csp-report content-type (legacy)
- Accepts application/json content-type (modern)
- Empty body returns 204 (don't crash)
- GET returns 405 Method Not Allowed
- CSP response header now includes report-uri /api/csp-report
"""

from __future__ import annotations

import json
import logging
import os
import sys

import pytest
from flask import Flask

SRC_ABS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_ABS not in sys.path:
    sys.path.insert(0, SRC_ABS)

# ---------------------------------------------------------------------------
# Minimal app fixture (no DB / plugins needed)
# ---------------------------------------------------------------------------

_SAMPLE_CSP_REPORT = {
    "csp-report": {
        "document-uri": "http://localhost/",
        "referrer": "",
        "violated-directive": "script-src 'self'",
        "effective-directive": "script-src",
        "original-policy": "default-src 'self'",
        "blocked-uri": "https://evil.example.com/bad.js",
        "status-code": 0,
        "source-file": "https://localhost/page?q=secret",
    }
}

_MODERN_CSP_REPORT = [
    {
        "type": "csp-violation",
        "age": 0,
        "url": "https://localhost/",
        "body": {
            "documentURL": "https://localhost/",
            "referrer": "",
            "blockedURL": "https://evil.example.com/x.js",
            "effectiveDirective": "script-src-elem",
            "originalPolicy": "default-src 'self'",
            "statusCode": 0,
            "sourceFile": "https://localhost/page",
            "lineNumber": 42,
            "columnNumber": 7,
        },
    }
]


def _make_csp_app() -> Flask:
    """Build a bare Flask app with only the CSP report blueprint registered."""
    app = Flask(__name__)
    app.secret_key = "test-csp-secret"

    from blueprints.csp_report import csp_report_bp

    app.register_blueprint(csp_report_bp)
    return app


@pytest.fixture()
def csp_client():
    return _make_csp_app().test_client()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_post_with_legacy_csp_report_returns_204(csp_client):
    """POST with application/csp-report and a JSON body returns 204."""
    resp = csp_client.post(
        "/api/csp-report",
        data=json.dumps(_SAMPLE_CSP_REPORT),
        content_type="application/csp-report",
    )
    assert resp.status_code == 204


def test_post_with_application_json_returns_204(csp_client):
    """POST with application/json and a modern report body returns 204."""
    resp = csp_client.post(
        "/api/csp-report",
        data=json.dumps(_MODERN_CSP_REPORT),
        content_type="application/json",
    )
    assert resp.status_code == 204


def test_post_logs_warning_via_caplog(caplog, csp_client):
    """The violation is logged at WARNING level."""
    with caplog.at_level(logging.WARNING, logger="blueprints.csp_report"):
        csp_client.post(
            "/api/csp-report",
            data=json.dumps(_SAMPLE_CSP_REPORT),
            content_type="application/csp-report",
        )

    warning_messages = [
        r.message for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any(
        "CSP violation" in msg for msg in warning_messages
    ), f"Expected 'CSP violation' in warning log; got: {warning_messages}"


def test_post_logs_report_content(caplog, csp_client):
    """Logged message includes the violated directive."""
    with caplog.at_level(logging.WARNING, logger="blueprints.csp_report"):
        csp_client.post(
            "/api/csp-report",
            data=json.dumps(_SAMPLE_CSP_REPORT),
            content_type="application/csp-report",
        )

    combined = " ".join(r.message for r in caplog.records)
    assert "script-src" in combined, f"Expected directive in log; got: {combined}"


def test_source_file_url_is_redacted(caplog, csp_client):
    """Query string is stripped from source-file URLs before logging."""
    with caplog.at_level(logging.WARNING, logger="blueprints.csp_report"):
        csp_client.post(
            "/api/csp-report",
            data=json.dumps(_SAMPLE_CSP_REPORT),
            content_type="application/csp-report",
        )

    combined = " ".join(r.message for r in caplog.records)
    # The query param "?q=secret" must not appear in the logs
    assert "secret" not in combined, f"Query string leaked into log: {combined}"


def test_source_file_url_fragment_is_redacted(caplog, csp_client):
    """Fragment (#...) is stripped from source-file URLs before logging.

    JTN-595 mutmut triage: kills a surviving mutant where the ``#`` entry
    is dropped from the ``("?", "#")`` separator tuple in ``_redact_url``.
    Without fragment stripping, anchor-style identifiers would leak into
    logs alongside the query-string redaction.
    """
    report = {
        "csp-report": {
            "document-uri": "http://localhost/",
            "violated-directive": "script-src 'self'",
            "source-file": "https://localhost/page#leaked-fragment-token",
        }
    }
    with caplog.at_level(logging.WARNING, logger="blueprints.csp_report"):
        csp_client.post(
            "/api/csp-report",
            data=json.dumps(report),
            content_type="application/csp-report",
        )

    combined = " ".join(r.message for r in caplog.records)
    assert (
        "leaked-fragment-token" not in combined
    ), f"Fragment leaked into log: {combined}"
    assert "https://localhost/page" in combined, f"Redacted URL missing: {combined}"


def test_all_url_fields_are_redacted(caplog, csp_client):
    """Every URL-bearing key (document-uri, referrer, blocked-uri, source-file)
    must have its query string + fragment stripped before logging.

    JTN-595 mutmut triage: kills surviving mutants where individual entries
    are dropped from the ``url_keys`` set in ``_sanitise_report``. Without
    per-field coverage, dropping e.g. ``"blocked-uri"`` from the set would
    survive because the sample payload's other fields would still redact.
    """
    report = {
        "csp-report": {
            "document-uri": "http://localhost/doc?doctoken=A",
            "referrer": "http://localhost/ref?reftoken=B",
            "blocked-uri": "https://evil.example.com/x?blocktoken=C",
            "source-file": "https://localhost/src?srctoken=D",
            "violated-directive": "script-src 'self'",
        }
    }
    with caplog.at_level(logging.WARNING, logger="blueprints.csp_report"):
        csp_client.post(
            "/api/csp-report",
            data=json.dumps(report),
            content_type="application/csp-report",
        )

    combined = " ".join(r.message for r in caplog.records)
    for leaked_token in ("doctoken", "reftoken", "blocktoken", "srctoken"):
        assert (
            leaked_token not in combined
        ), f"Query token {leaked_token!r} leaked into log: {combined}"


def test_empty_body_returns_204(csp_client):
    """Empty POST body must not crash — returns 204."""
    resp = csp_client.post(
        "/api/csp-report",
        data=b"",
        content_type="application/csp-report",
    )
    assert resp.status_code == 204


def test_invalid_json_body_returns_400(csp_client):
    """Malformed JSON must be rejected with HTTP 400 (JTN-628)."""
    resp = csp_client.post(
        "/api/csp-report",
        data=b"not-json!!!",
        content_type="application/csp-report",
    )
    assert resp.status_code == 400
    # The response MUST NOT echo the malformed body back (defensive).
    assert b"not-json" not in resp.data


def test_invalid_json_body_reports_application_json(csp_client):
    """400 response uses application/json content-type."""
    resp = csp_client.post(
        "/api/csp-report",
        data=b"{broken",
        content_type="application/csp-report",
    )
    assert resp.status_code == 400
    assert resp.content_type.startswith("application/json")


def test_oversized_body_is_discarded(csp_client):
    """Bodies larger than 16 KiB are discarded without logging."""
    huge = b'{"csp-report":{"blocked-uri":"' + (b"A" * 20_000) + b'"}}'
    resp = csp_client.post(
        "/api/csp-report",
        data=huge,
        content_type="application/csp-report",
    )
    # Oversized bodies get a 204 (silently discarded) — the server MUST
    # NOT fingerprint the limiter by returning a distinct error code.
    assert resp.status_code == 204


def test_reports_api_v2_content_type_accepted(csp_client):
    """application/reports+json (Reporting API v2) is accepted."""
    resp = csp_client.post(
        "/api/csp-report",
        data=json.dumps(_MODERN_CSP_REPORT),
        content_type="application/reports+json",
    )
    assert resp.status_code == 204


def test_get_returns_405(csp_client):
    """GET /api/csp-report must be rejected with 405."""
    resp = csp_client.get("/api/csp-report")
    assert resp.status_code == 405


def test_csp_header_includes_report_uri(monkeypatch):
    """The CSP response header must contain 'report-uri /api/csp-report'."""
    # Clear any custom CSP so we get the default value
    monkeypatch.delenv("INKYPI_CSP", raising=False)
    monkeypatch.delenv("INKYPI_CSP_REPORT_ONLY", raising=False)

    app = Flask(__name__)
    app.secret_key = "test"

    from app_setup.security_middleware import _apply_csp_header

    with app.test_request_context("/"):
        from flask import Response as FlaskResponse

        resp = FlaskResponse("ok")
        _apply_csp_header(resp, dev_mode=False)

    csp = resp.headers.get("Content-Security-Policy", "")
    assert (
        "report-uri /api/csp-report" in csp
    ), f"Expected 'report-uri /api/csp-report' in CSP header; got: {csp!r}"


def test_csp_header_includes_report_uri_in_report_only_mode(monkeypatch):
    """report-uri is also present when the Report-Only header is used."""
    monkeypatch.delenv("INKYPI_CSP", raising=False)
    monkeypatch.setenv("INKYPI_CSP_REPORT_ONLY", "1")

    app = Flask(__name__)
    app.secret_key = "test"

    from app_setup.security_middleware import _apply_csp_header

    with app.test_request_context("/"):
        from flask import Response as FlaskResponse

        resp = FlaskResponse("ok")
        _apply_csp_header(resp, dev_mode=False)

    csp = resp.headers.get("Content-Security-Policy-Report-Only", "")
    assert (
        "report-uri /api/csp-report" in csp
    ), f"Expected 'report-uri /api/csp-report' in Report-Only CSP; got: {csp!r}"


def test_custom_csp_with_existing_report_uri_not_duplicated(monkeypatch):
    """If INKYPI_CSP already contains 'report-uri', it must not be appended again."""
    monkeypatch.setenv(
        "INKYPI_CSP",
        "default-src 'self'; report-uri /api/csp-report",
    )

    app = Flask(__name__)
    app.secret_key = "test"

    from app_setup.security_middleware import _apply_csp_header

    with app.test_request_context("/"):
        from flask import Response as FlaskResponse

        resp = FlaskResponse("ok")
        _apply_csp_header(resp, dev_mode=False)

    csp = resp.headers.get("Content-Security-Policy", "")
    assert (
        csp.count("report-uri") == 1
    ), f"'report-uri' must appear exactly once; got: {csp!r}"


def _make_csp_app_with_full_middleware() -> Flask:
    """Build an app with the real CSRF + rate-limit middleware registered.

    This exercises the exemption added in JTN-628: /api/csp-report MUST
    bypass CSRF and the sliding-window rate limiter even though it is a
    POST to a path that would otherwise be rejected with 403.
    """
    app = Flask(__name__)
    app.secret_key = "test-csp-integration"
    app.config["TESTING"] = True

    from app_setup.security_middleware import (
        setup_csrf_protection,
        setup_rate_limiting,
    )
    from blueprints.csp_report import csp_report_bp

    setup_csrf_protection(app)
    setup_rate_limiting(app)
    app.register_blueprint(csp_report_bp)
    return app


def test_post_without_csrf_token_succeeds_full_middleware():
    """Integration: POST without CSRF token returns 204 (JTN-628)."""
    client = _make_csp_app_with_full_middleware().test_client()
    resp = client.post(
        "/api/csp-report",
        data=json.dumps(_SAMPLE_CSP_REPORT),
        content_type="application/csp-report",
    )
    # Before JTN-628 this returned 403 (CSRF rejection).
    assert resp.status_code == 204


def test_malformed_json_through_full_middleware_returns_400():
    """Integration: malformed JSON yields 400 even with CSRF+rate-limit registered."""
    client = _make_csp_app_with_full_middleware().test_client()
    resp = client.post(
        "/api/csp-report",
        data=b"definitely-not-json",
        content_type="application/csp-report",
    )
    assert resp.status_code == 400


def test_wrong_content_type_still_accepted_if_valid_json():
    """Unexpected content-type with valid JSON is logged and returns 204."""
    client = _make_csp_app_with_full_middleware().test_client()
    resp = client.post(
        "/api/csp-report",
        data=json.dumps(_SAMPLE_CSP_REPORT),
        content_type="text/plain",
    )
    # Browsers sometimes send odd content-types; we accept the body if
    # it parses, and return 204 regardless of content-type.
    assert resp.status_code == 204


def test_modern_report_api_returns_204_and_logs(caplog, csp_client):
    """Modern Reporting API (array payload) is parsed and logged."""
    with caplog.at_level(logging.WARNING, logger="blueprints.csp_report"):
        resp = csp_client.post(
            "/api/csp-report",
            data=json.dumps(_MODERN_CSP_REPORT),
            content_type="application/json",
        )

    assert resp.status_code == 204
    combined = " ".join(r.message for r in caplog.records)
    assert "CSP violation" in combined
