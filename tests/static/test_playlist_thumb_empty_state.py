"""Regression guard: an unrendered playlist instance must not paint a black
box in the light theme (ISSUE-010).

Background: when `plugin_instance.latest_refresh_time` is None the playlist
template used to emit `<div class="pl-item-thumb"></div>` with whitespace
between the tags. The CSS rule `.pl-item-thumb:empty { display: none }` only
matches elements with NO child nodes (text nodes count), so the whitespace
defeated the hide rule. The wrapper rendered with `background: var(--preview-bg)`
which is a hardcoded `#000` for both themes — fine on dark, jarringly black
on the light theme cream backdrop.

The fix moves the `{% if latest_refresh_time %}` guard outside the wrapper
so the entire `<div>` is omitted from the DOM when there's nothing to show.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAYLIST_HTML = ROOT / "src" / "templates" / "playlist.html"


def test_thumb_wrapper_only_emitted_when_there_is_a_refresh_image():
    """The `pl-item-thumb` div must be inside the latest_refresh_time guard,
    not the other way around. Otherwise the wrapper renders empty-but-non-empty
    and shows a hardcoded-black box in the light theme."""
    src = PLAYLIST_HTML.read_text(encoding="utf-8")
    # Find the position of the latest_refresh_time check and the thumb div.
    refresh_guard = src.find("plugin_instance.latest_refresh_time")
    thumb_div = src.find('<div class="pl-item-thumb">')
    assert refresh_guard != -1, "latest_refresh_time guard removed from template"
    assert thumb_div != -1, "pl-item-thumb wrapper removed from template"
    # The Jinja `if` must come BEFORE the wrapper div, so the wrapper itself
    # is conditionally rendered.
    assert refresh_guard < thumb_div, (
        "the {% if plugin_instance.latest_refresh_time %} guard must wrap the "
        "<div class=\"pl-item-thumb\"> wrapper, not just its inner content. "
        "Otherwise an unrefreshed instance leaves the wrapper in the DOM and "
        "paints a hardcoded-black 96×56 box in light theme."
    )


def test_thumb_wrapper_does_not_appear_with_unconditional_whitespace_content():
    """Defensive: the template must NOT have a `<div class="pl-item-thumb">`
    immediately followed (after only whitespace + comments) by the
    `{% if plugin_instance.latest_refresh_time %}` opener. That's the
    pre-fix shape we're guarding against."""
    src = PLAYLIST_HTML.read_text(encoding="utf-8")
    bad_shape = re.search(
        r'<div class="pl-item-thumb">\s*\{%\s*if\s+plugin_instance\.latest_refresh_time',
        src,
    )
    assert bad_shape is None, (
        "Found the regressed shape: thumb wrapper opens before the "
        "latest_refresh_time guard. Move the guard outside the wrapper."
    )
