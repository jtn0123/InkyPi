"""Contract tests: canonical JSON envelope (JTN-500).

All JSON API routes that signal an outcome (success or failure) must return a
response shaped like the canonical envelope documented in
``src/utils/http_utils.py``:

Success::

    {
        "success": true,
        "message": "<optional>",
        "request_id": "<uuid when in a request context>",
        ...payload...
    }

Error::

    {
        "success": false,
        "error": "<message>",
        "code": "<optional>",
        "details": {...},
        "request_id": "<uuid>"
    }

These tests exercise a representative set of routes via the Flask test client
and assert the envelope shape.  Pure data-read routes (e.g. ``/api/version``,
``/api/uptime``) are intentionally exempt — see the module docstring.
"""

from __future__ import annotations

import json


def _assert_success_envelope(payload: dict) -> None:
    assert isinstance(payload, dict), f"response not a dict: {payload!r}"
    assert payload.get("success") is True, f"expected success=True, got {payload!r}"
    # request_id should be populated whenever we are inside a request context.
    assert (
        isinstance(payload.get("request_id"), str) and payload["request_id"]
    ), f"missing request_id in success envelope: {payload!r}"


def _assert_error_envelope(payload: dict) -> None:
    assert isinstance(payload, dict), f"response not a dict: {payload!r}"
    assert payload.get("success") is False, f"expected success=False, got {payload!r}"
    assert (
        isinstance(payload.get("error"), str) and payload["error"]
    ), f"missing error string in error envelope: {payload!r}"
    assert (
        isinstance(payload.get("request_id"), str) and payload["request_id"]
    ), f"missing request_id in error envelope: {payload!r}"


# ---------------------------------------------------------------------------
# Success envelope coverage
# ---------------------------------------------------------------------------


def test_plugin_order_success_envelope(client, flask_app):
    """POST /api/plugin_order returns the canonical success envelope."""
    device_config = flask_app.config["DEVICE_CONFIG"]
    plugin_ids = sorted({p["id"] for p in device_config.get_plugins()})
    resp = client.post(
        "/api/plugin_order",
        data=json.dumps({"order": plugin_ids}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    _assert_success_envelope(resp.get_json())


def test_health_plugins_success_envelope(client):
    """GET /api/health/plugins returns the canonical success envelope."""
    resp = client.get("/api/health/plugins")
    assert resp.status_code == 200
    body = resp.get_json()
    _assert_success_envelope(body)
    assert "items" in body


def test_health_system_success_envelope(client):
    """GET /api/health/system returns the canonical success envelope."""
    resp = client.get("/api/health/system")
    assert resp.status_code == 200
    _assert_success_envelope(resp.get_json())


def test_isolation_get_success_envelope(client):
    """GET /settings/isolation returns the canonical success envelope."""
    resp = client.get("/settings/isolation")
    assert resp.status_code == 200
    body = resp.get_json()
    _assert_success_envelope(body)
    assert "isolated_plugins" in body


def test_safe_reset_success_envelope(client):
    """POST /settings/safe_reset returns the canonical success envelope."""
    resp = client.post("/settings/safe_reset")
    assert resp.status_code == 200
    _assert_success_envelope(resp.get_json())


# ---------------------------------------------------------------------------
# Error envelope coverage
# ---------------------------------------------------------------------------


def test_plugin_order_validation_error_envelope(client):
    """POST /api/plugin_order with a bad body returns the error envelope."""
    resp = client.post(
        "/api/plugin_order",
        data="not-json",
        content_type="application/json",
    )
    assert resp.status_code == 400
    _assert_error_envelope(resp.get_json())


def test_isolation_bad_json_error_envelope(client):
    """POST /settings/isolation with a non-object body returns the error envelope."""
    resp = client.post(
        "/settings/isolation",
        data=json.dumps([]),
        content_type="application/json",
    )
    assert resp.status_code == 400
    _assert_error_envelope(resp.get_json())


def test_delete_api_key_invalid_error_envelope(client):
    """POST /settings/delete_api_key with an unknown key returns the error envelope."""
    resp = client.post("/settings/delete_api_key", data={"key": "NOT_A_REAL_KEY"})
    assert resp.status_code == 400
    _assert_error_envelope(resp.get_json())


def test_plugin_history_invalid_name_error_envelope(client):
    """GET /api/plugins/instance/<bad>/history returns the error envelope."""
    # '/' is not in the allowed name charset; flask routing will 404 before
    # the handler runs, so pick something that passes the path but fails the
    # regex check inside the handler.
    resp = client.get("/api/plugins/instance/.hidden/history")
    assert resp.status_code in (400, 404)
    _assert_error_envelope(resp.get_json())


# ---------------------------------------------------------------------------
# request_id propagation
# ---------------------------------------------------------------------------


def test_request_id_header_round_trip(client):
    """If the client supplies X-Request-Id, the envelope echoes it."""
    rid = "test-req-id-12345"
    resp = client.get("/api/health/system", headers={"X-Request-Id": rid})
    assert resp.status_code == 200
    body = resp.get_json()
    _assert_success_envelope(body)
    assert body["request_id"] == rid
