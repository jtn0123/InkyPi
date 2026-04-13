"""Reflective XSS regression tests for the playlist blueprint.

These tests craft payloads with user-controlled values (``playlist_name``,
``new_name``) that contain raw HTML/JS and assert the response body does NOT
echo the tags verbatim.  All playlist endpoints return JSON via
``jsonify(...)``; JSON responses are served with
``Content-Type: application/json`` and do not execute as HTML, but we still
want to ensure error messages are generic and never interpolate the raw
attacker-controlled value.
"""

from __future__ import annotations

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "<svg/onload=alert(1)>",
    "javascript:alert(1)",
]


def _assert_no_raw_reflection(body: bytes | str, payload: str) -> None:
    text = body.decode() if isinstance(body, bytes) else body
    assert (
        payload not in text
    ), f"Response echoed raw XSS payload {payload!r}; body was: {text[:300]!r}"


def test_create_playlist_duplicate_does_not_reflect_name(client):
    """create_playlist duplicate error must not echo playlist_name."""
    # Seed a baseline playlist first
    resp = client.post(
        "/create_playlist",
        json={
            "playlist_name": "SafeName",
            "start_time": "00:00",
            "end_time": "01:00",
        },
    )
    assert resp.status_code == 200

    for payload in XSS_PAYLOADS:
        # Try creating a duplicate-by-name with an XSS payload name.
        # The validator will usually reject the name as invalid, but if a
        # duplicate path is hit, it still must not reflect.
        r = client.post(
            "/create_playlist",
            json={
                "playlist_name": payload,
                "start_time": "00:00",
                "end_time": "01:00",
            },
        )
        # Any 4xx is acceptable; the critical check is no reflection.
        assert r.status_code >= 400
        assert r.headers.get("Content-Type", "").startswith("application/json")
        _assert_no_raw_reflection(r.data, payload)


def test_update_playlist_missing_does_not_reflect_name(client):
    for payload in XSS_PAYLOADS:
        r = client.put(
            f"/update_playlist/{payload}",
            json={
                "new_name": "Whatever",
                "start_time": "00:00",
                "end_time": "01:00",
            },
        )
        assert r.status_code >= 400
        assert r.headers.get("Content-Type", "").startswith("application/json")
        _assert_no_raw_reflection(r.data, payload)


def test_delete_playlist_missing_does_not_reflect_name(client):
    for payload in XSS_PAYLOADS:
        r = client.delete(f"/delete_playlist/{payload}")
        assert r.status_code >= 400
        # A Flask 404 from URL routing (no matching rule) serves HTML but does
        # not echo the raw path segment, so only require JSON content-type when
        # the route actually matched and our handler produced the response.
        if r.status_code != 404:
            assert r.headers.get("Content-Type", "").startswith("application/json")
        _assert_no_raw_reflection(r.data, payload)


def test_reorder_plugins_missing_does_not_reflect_name(client):
    for payload in XSS_PAYLOADS:
        r = client.post(
            "/reorder_plugins",
            json={"playlist_name": payload, "ordered": []},
        )
        assert r.status_code >= 400
        assert r.headers.get("Content-Type", "").startswith("application/json")
        _assert_no_raw_reflection(r.data, payload)


def test_display_next_missing_does_not_reflect_name(client):
    for payload in XSS_PAYLOADS:
        r = client.post(
            "/display_next_in_playlist",
            json={"playlist_name": payload},
        )
        assert r.status_code >= 400
        assert r.headers.get("Content-Type", "").startswith("application/json")
        _assert_no_raw_reflection(r.data, payload)


def test_playlist_eta_missing_does_not_reflect_name(client):
    for payload in XSS_PAYLOADS:
        r = client.get(f"/playlist/eta/{payload}")
        assert r.status_code >= 400
        if r.status_code != 404:
            assert r.headers.get("Content-Type", "").startswith("application/json")
        _assert_no_raw_reflection(r.data, payload)
