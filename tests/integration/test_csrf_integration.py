# pyright: reportMissingImports=false
"""Integration tests for CSRF protection using the production middleware.

The standard test ``client`` fixture intentionally omits CSRF enforcement so
that other integration tests are not burdened with token bookkeeping.  These
tests register the **real** ``_setup_csrf_protection`` middleware on a
dedicated app instance to verify it end-to-end.
"""

import json

import pytest


@pytest.fixture()
def csrf_client(client):
    """Client with the production CSRF middleware registered on the existing test app.

    The standard ``client`` fixture omits CSRF enforcement.  This fixture
    imports and applies the real ``_setup_csrf_protection`` from ``inkypi.py``
    so that tests exercise the actual production middleware end-to-end.
    """
    from inkypi import _setup_csrf_protection

    _setup_csrf_protection(client.application)
    return client


def test_new_session_post_rejected_by_production_middleware(csrf_client):
    """JTN-224: First POST in a new session must be rejected by production CSRF middleware."""
    resp = csrf_client.post(
        "/settings/client_log",
        content_type="application/json",
        data=json.dumps({"level": "error", "message": "test"}),
    )
    assert resp.status_code == 403


def test_post_with_valid_csrf_token_succeeds(csrf_client):
    """After establishing a session token, POST with valid token succeeds."""
    # GET the home page to establish a session with a CSRF token
    get_resp = csrf_client.get("/")
    assert get_resp.status_code == 200

    # Extract the CSRF token from the session
    with csrf_client.session_transaction() as sess:
        token = sess.get("_csrf_token")
    assert token, "Session should contain a CSRF token after GET"

    # POST with the valid token in header
    resp = csrf_client.post(
        "/settings/client_log",
        content_type="application/json",
        data=json.dumps({"level": "info", "message": "test"}),
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 200


def test_post_with_wrong_csrf_token_rejected(csrf_client):
    """POST with an incorrect CSRF token must be rejected."""
    # Establish session
    csrf_client.get("/")
    resp = csrf_client.post(
        "/settings/client_log",
        content_type="application/json",
        data=json.dumps({"level": "error", "message": "test"}),
        headers={"X-CSRFToken": "wrong-token-value"},
    )
    assert resp.status_code == 403


def test_json_body_csrf_token_accepted_by_production_middleware(csrf_client):
    """JTN-257: CSRF token in JSON body (_csrf_token) must be accepted by production middleware."""
    # Establish session
    csrf_client.get("/")
    with csrf_client.session_transaction() as sess:
        token = sess.get("_csrf_token")
    assert token

    # Send token in JSON body (sendBeacon path)
    resp = csrf_client.post(
        "/settings/client_log",
        content_type="application/json",
        data=json.dumps({"level": "error", "message": "test", "_csrf_token": token}),
    )
    assert resp.status_code == 200


def test_form_csrf_token_accepted_by_production_middleware(csrf_client):
    """CSRF token in form data (csrf_token field) must be accepted."""
    csrf_client.get("/")
    with csrf_client.session_transaction() as sess:
        token = sess.get("_csrf_token")
    assert token

    resp = csrf_client.post(
        "/settings/client_log",
        data={"csrf_token": token, "level": "info", "message": "test"},
        content_type="application/x-www-form-urlencoded",
    )
    # client_log expects JSON, so form data may error — but CSRF itself passes (not 403)
    assert resp.status_code != 403


def test_extract_csrf_token_prefers_header(csrf_client):
    """When both header and JSON body have tokens, header takes precedence."""
    csrf_client.get("/")
    with csrf_client.session_transaction() as sess:
        token = sess.get("_csrf_token")
    assert token

    resp = csrf_client.post(
        "/settings/client_log",
        content_type="application/json",
        data=json.dumps(
            {"level": "error", "message": "test", "_csrf_token": "wrong-body-token"}
        ),
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 200
