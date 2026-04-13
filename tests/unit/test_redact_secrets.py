"""Unit tests for utils.logging_utils.redact_secrets (JTN-326).

Covers the public sanitizer used by call sites that log values which CodeQL
flags as potentially sensitive (e.g. plugin ``template_params`` derived
fields). The filter-level behaviour is covered elsewhere; these tests just
exercise the direct function entry point.
"""

from utils.logging_utils import redact_secrets


def test_redact_secrets_masks_api_key_assignment():
    out = redact_secrets("api_key=supersecret123")
    assert "supersecret123" not in out
    assert "***REDACTED***" in out


def test_redact_secrets_masks_bearer_token():
    out = redact_secrets("Authorization: Bearer abc.def-XYZ_123=")
    assert "abc.def-XYZ_123=" not in out
    assert "***REDACTED***" in out


def test_redact_secrets_masks_long_hex_string():
    token = "a" * 40
    out = redact_secrets(f"token value {token} trailing")
    assert token not in out
    assert "***REDACTED***" in out


def test_redact_secrets_leaves_benign_string_unchanged():
    text = "/opt/inkypi/plugins/foo/render/style.css"
    assert redact_secrets(text) == text


def test_redact_secrets_coerces_non_string_input():
    err = FileNotFoundError("missing: /tmp/style.css")
    out = redact_secrets(err)
    assert isinstance(out, str)
    assert "/tmp/style.css" in out
