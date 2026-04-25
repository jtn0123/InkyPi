"""Regression guard for the device-name input client validation (ISSUE-008).

Background: in dogfood we discovered that "   " (three spaces) was
accepted by the client as a valid device name and round-tripped to the
server, which then rejected it with 422. The native HTML5 `required`
constraint considers whitespace as truthy length, so the gate has to be
on the `pattern` attribute.

This test verifies the rendered template carries a pattern that
*requires* at least one non-whitespace character, so the failure surfaces
inline before the user clicks Save.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_HTML = ROOT / "src" / "templates" / "settings.html"


def _device_name_input_tag() -> str:
    """Return the raw `<input id="deviceName" …>` tag from settings.html."""
    src = SETTINGS_HTML.read_text(encoding="utf-8")
    match = re.search(r'<input[^>]*\bid="deviceName"[^>]*>', src, flags=re.S)
    assert match, "deviceName <input> not found in settings.html"
    return match.group(0)


def _make_pattern_regex(pattern: str) -> re.Pattern[str]:
    """Translate the HTML5 `pattern` attribute into a fullmatch Python regex.

    HTML5 anchors `pattern` implicitly at both ends; `re.fullmatch` mirrors
    that. The `\\u####` escapes inside the attribute string are real two-char
    sequences (`\\` + `u####`); decode them to actual code points so Python's
    regex engine sees the same character classes the browser sees.
    """
    decoded = pattern.encode("utf-8").decode("unicode_escape")
    return re.compile(decoded, re.S)


def test_device_name_pattern_rejects_whitespace_only_and_lone_control_chars():
    """The HTML pattern must reject:
       - empty / whitespace-only input  (ISSUE-008)
       - a single control character     (CodeRabbit follow-up — closes a
         consistency gap with the server's `_validate_device_name`
         `unicodedata.category(ch) == "Cc"` check)
    while still accepting normal names.
    """
    tag = _device_name_input_tag()
    pattern_match = re.search(r'pattern="([^"]*)"', tag)
    assert pattern_match, "device name input has no pattern attribute"
    pattern = pattern_match.group(1)
    rx = _make_pattern_regex(pattern)
    # Negative cases — must fail client validation:
    assert rx.fullmatch("") is None, "empty value must not match"
    assert rx.fullmatch("   ") is None, "whitespace-only must not match"
    assert rx.fullmatch("\t\t") is None, "tab-only must not match"
    assert rx.fullmatch("\x01") is None, (
        "a lone control character must not match — would otherwise pass the "
        "client and only fail server-side at unicodedata.category 'Cc'"
    )
    # Positive cases — normal names must match:
    assert rx.fullmatch("InkyPi Development") is not None
    assert rx.fullmatch("Kitchen #2") is not None
    assert rx.fullmatch("a") is not None, "single non-space char is fine"


def test_device_name_title_documents_non_space_requirement():
    """The user-facing tooltip should explain the constraint we just added,
    so the rejection message is self-explanatory if the pattern fails."""
    tag = _device_name_input_tag()
    title_match = re.search(r'title="([^"]*)"', tag)
    assert title_match, "device name input has no title attribute"
    title = title_match.group(1).lower()
    assert (
        "non-space" in title or "non-whitespace" in title or "at least one" in title
    ), f"device name title {title!r} should mention the non-whitespace requirement"
