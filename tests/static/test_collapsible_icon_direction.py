"""Tests for collapsible section arrow icon direction logic.

JTN-244: The toggle function must show ▼ when closing and ▲ when opening,
reflecting the *new* (post-toggle) state, not the old state.
"""


def test_ui_helpers_script_exists(client):
    resp = client.get("/static/scripts/ui_helpers.js")
    assert resp.status_code == 200


def test_toggle_collapsible_icon_reflects_post_toggle_state(client):
    """JTN-244: Icon ternary must use the inverted isOpen value.

    Before the fix, ``isOpen ? "▲" : "▼"`` used the pre-toggle state, so the
    arrow was backwards. The correct logic is ``isOpen ? "▼" : "▲"``:
    - when the section *was* open (isOpen=true) we are closing it → show ▼
    - when the section *was* closed (isOpen=false) we are opening it → show ▲
    """
    resp = client.get("/static/scripts/ui_helpers.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # The correct (fixed) ternary must be present
    assert 'isOpen ? "▼" : "▲"' in js

    # The inverted (buggy) ternary must NOT appear in toggleCollapsible
    # (restoreCollapsibles and setCollapsibles use the same icon chars differently,
    # so we narrow the check to the toggle function body)
    toggle_start = js.find("function toggleCollapsible(")
    toggle_end = js.find("\n  }", toggle_start)
    toggle_body = js[toggle_start:toggle_end]
    assert 'isOpen ? "▲" : "▼"' not in toggle_body
