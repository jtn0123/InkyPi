"""Regression guards for settings page version-check error handling (JTN-751)."""

import re
from pathlib import Path

JS_PATH = Path("src/static/scripts/settings/actions.js")


def test_version_check_aborts_without_warning():
    """AbortError from the version-check fetch should be treated as expected."""
    js = JS_PATH.read_text()

    assert 'e?.name === "AbortError"' in js, (
        "Version check catch block must special-case AbortError so expected "
        "navigation/remount aborts do not emit warnings"
    )
    assert 'console.debug("Version check aborted:", e);' not in js, (
        "AbortError is expected during normal navigation/remounts and should "
        "not add noise to the browser console"
    )
    assert re.search(
        r'if\s*\(\s*e\?\.name\s*===\s*"AbortError"\s*\)\s*\{\s*return;',
        js,
    ), (
        "AbortError branch should return early so the badge is not marked as "
        "a failed update check for an expected abort"
    )
    assert (
        'console.warn("Version check failed:", e);' in js
    ), "Non-abort failures must still be visible as warnings"
