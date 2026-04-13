"""Regression tests for CodeQL py/reflective-xss in ``history`` blueprint.

Covers alerts previously raised at
``src/blueprints/history.py`` lines 355, 359, 378, 382. Every POST route
that accepts a user-controlled ``filename`` is hit with a selection of
XSS payloads; the raw payload must never appear in the response body and
the response must be ``application/json``.
"""

from __future__ import annotations

import pytest

# Payloads that would execute if reflected un-escaped into an HTML context.
_XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "<svg/onload=alert(1)>",
    "javascript:alert(1)",
    "<iframe srcdoc='<script>alert(1)</script>'></iframe>",
]


@pytest.mark.parametrize("payload", _XSS_PAYLOADS)
def test_history_redisplay_rejects_xss_filename(client, payload):
    resp = client.post("/history/redisplay", json={"filename": payload})
    assert resp.status_code in (400, 404)
    assert resp.mimetype == "application/json"
    body = resp.get_data(as_text=True)
    assert payload not in body
    # Defence in depth: no raw HTML tag markers from the payloads should appear.
    assert "<script" not in body.lower()
    assert "onerror" not in body.lower()
    assert "onload" not in body.lower()
    assert "<iframe" not in body.lower()


@pytest.mark.parametrize("payload", _XSS_PAYLOADS)
def test_history_delete_rejects_xss_filename(client, payload):
    resp = client.post("/history/delete", json={"filename": payload})
    assert resp.status_code in (400, 404)
    assert resp.mimetype == "application/json"
    body = resp.get_data(as_text=True)
    assert payload not in body
    assert "<script" not in body.lower()
    assert "onerror" not in body.lower()
    assert "onload" not in body.lower()
    assert "<iframe" not in body.lower()


def test_history_redisplay_rejects_non_json_body(client):
    # Non-JSON body exercises the ``BadRequest`` branch that used to build
    # an error response inside the helper. Result must still be generic.
    resp = client.post(
        "/history/redisplay",
        data="not json at all <script>",
        content_type="text/plain",
    )
    assert resp.status_code == 400
    assert resp.mimetype == "application/json"
    body = resp.get_data(as_text=True)
    assert "<script" not in body.lower()


def test_history_delete_rejects_non_object_body(client):
    resp = client.post("/history/delete", json=["<script>alert(1)</script>"])
    assert resp.status_code == 400
    assert resp.mimetype == "application/json"
    body = resp.get_data(as_text=True)
    assert "<script" not in body.lower()
    assert "Request body must be a JSON object" in body


def test_history_redisplay_missing_filename(client):
    resp = client.post("/history/redisplay", json={})
    assert resp.status_code == 400
    assert resp.mimetype == "application/json"
    body = resp.get_data(as_text=True)
    assert "filename is required" in body


def test_history_delete_empty_filename(client):
    resp = client.post("/history/delete", json={"filename": "   "})
    assert resp.status_code == 400
    assert resp.mimetype == "application/json"
    body = resp.get_data(as_text=True)
    assert "filename is required" in body


def test_history_image_invalid_filename_not_reflected(client):
    # ``history_image`` uses ``_resolve_history_path`` directly and returns
    # ``_ERR_INVALID_FILENAME``; confirm traversal attempts don't reflect.
    resp = client.get("/history/image/%3Cscript%3Ealert(1)%3C%2Fscript%3E")
    # Depending on routing, Flask may 400/404; either way, no reflection.
    assert resp.status_code in (400, 404)
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
