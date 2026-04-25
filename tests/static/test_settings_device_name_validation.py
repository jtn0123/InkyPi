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


def test_device_name_pattern_requires_non_whitespace_character():
    """The HTML pattern must require at least one non-whitespace char.
    Otherwise `"   "` is accepted client-side and only the server rejects it."""
    tag = _device_name_input_tag()
    pattern_match = re.search(r'pattern="([^"]*)"', tag)
    assert pattern_match, "device name input has no pattern attribute"
    pattern = pattern_match.group(1)
    # The simplest reliable signal: the pattern must contain `\S` somewhere
    # (anchored or otherwise). Without it, whitespace-only is admissible.
    assert r"\S" in pattern, (
        f"device name pattern {pattern!r} does not require any non-whitespace "
        "character — whitespace-only input would pass client validation"
    )


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
