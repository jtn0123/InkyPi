"""Regression guard: ``copyText`` must work in non-secure contexts.

InkyPi is commonly served on the LAN over plain HTTP. Browsers treat that
as an insecure context, which makes ``navigator.clipboard.writeText``
throw / be unavailable. Without a fallback, every "Copy logs" click ends
in a "Copy failed" toast (as the user reported on 2026-04-25). This test
locks in the fallback path so a future refactor cannot silently regress
the behavior.
"""

from pathlib import Path

JS_PATH = Path("src/static/scripts/settings/shared.js")


def test_copy_text_uses_clipboard_when_secure_context():
    js = JS_PATH.read_text()
    assert "navigator.clipboard && globalThis.isSecureContext" in js, (
        "copyText should still prefer the async Clipboard API when the page "
        "is a secure context (HTTPS / localhost)."
    )


def test_copy_text_falls_back_to_exec_command_for_http_lan():
    js = JS_PATH.read_text()
    assert "copyTextViaExecCommand" in js, (
        "copyText must fall back to a legacy execCommand path so HTTP-on-LAN "
        "deployments can still copy logs."
    )
    assert (
        'document.execCommand("copy")' in js
    ), "Fallback path should call document.execCommand('copy')."


def test_copy_text_does_not_short_circuit_on_insecure_context():
    js = JS_PATH.read_text()
    # The pre-fix code unconditionally returned false when the context was
    # insecure. Make sure that early return is gone.
    assert "!navigator.clipboard || !globalThis.isSecureContext" not in js, (
        "Insecure-context early return must be gone — copyText should fall "
        "through to the execCommand fallback instead of returning false."
    )
