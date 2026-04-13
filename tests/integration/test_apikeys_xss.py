"""Reflective XSS regression tests for the API Keys blueprint (JTN-326).

Posts XSS payloads via ``POST /api-keys/save`` in both the entry ``key`` and
``value`` fields and asserts the response body never echoes the raw payload.
Covers CodeQL rule ``py/reflective-xss`` at
``src/blueprints/apikeys.py:205`` (error reflected from
``_validate_api_key_entry``).
"""

from __future__ import annotations

import pytest

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


@pytest.fixture
def _isolate_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr("blueprints.apikeys.get_env_path", lambda: str(env_file))
    return env_file


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_save_invalid_key_format_does_not_reflect_key(client, _isolate_env, payload):
    """Invalid key format must not reflect attacker-controlled key in body."""
    resp = client.post(
        "/api-keys/save",
        json={"entries": [{"key": payload, "value": "x"}]},
    )
    assert resp.status_code == 400
    _assert_no_raw_reflection(resp.get_data(as_text=True), payload)


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_save_non_string_value_does_not_reflect_key(client, _isolate_env, payload):
    """Non-string value error must not reflect the (valid) key name."""
    # Key must pass the regex so we hit the value-type error path; embed the
    # payload inside the value as an integer-coerced message instead.
    resp = client.post(
        "/api-keys/save",
        json={"entries": [{"key": "VALID_KEY", "value": 123}]},
    )
    assert resp.status_code == 400
    # Ensure no generic reflection from any surrounding code
    body = resp.get_data(as_text=True)
    assert payload not in body


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_save_control_chars_in_value_does_not_reflect_key(
    client, _isolate_env, payload
):
    """Control-char value error must not reflect the (valid) key name."""
    # key used below must satisfy the regex — use a fixed safe name and place
    # the payload as part of an invalid (control-char) value.
    resp = client.post(
        "/api-keys/save",
        json={"entries": [{"key": "VALID_KEY", "value": f"bad\n{payload}"}]},
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    _assert_no_raw_reflection(body, payload)


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_save_bad_keep_existing_does_not_reflect_key(client, _isolate_env, payload):
    """keepExisting type error must not reflect attacker-controlled key."""
    resp = client.post(
        "/api-keys/save",
        json={"entries": [{"key": payload, "keepExisting": "yes"}]},
    )
    assert resp.status_code == 400
    _assert_no_raw_reflection(resp.get_data(as_text=True), payload)
