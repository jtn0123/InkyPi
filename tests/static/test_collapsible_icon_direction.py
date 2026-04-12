"""Tests for collapsible section arrow icon direction logic.

JTN-244 originally asserted that the toggle function swapped textContent
between ▼ and ▲ to reflect the post-toggle state.

JTN-623 replaced that JS-driven textContent swap with a pure CSS approach:
the chevron character stays ▼ in markup and the `.collapsible-header[aria-expanded="true"]
.collapsible-icon { transform: rotate(180deg); }` rule in _toggle.css rotates it
when the section is open. This avoids a double-flip when both mechanisms were
active, which made the chevron appear unchanged between states.

JTN-643 added a regression guard: the chevron span must remain in a
non-inline box (via `float: right` or an explicit `display:` value) so the
CSS transform actually applies — transforms have no visible effect on plain
inline boxes, which would silently bring the "stuck ▼" bug back.
"""


def test_ui_helpers_script_exists(client):
    resp = client.get("/static/scripts/ui_helpers.js")
    assert resp.status_code == 200


def test_toggle_collapsible_updates_aria_expanded(client):
    """JTN-623: toggleCollapsible must flip aria-expanded between true/false.

    This is the primary a11y contract: screen readers rely on aria-expanded
    to announce the accordion state.
    """
    resp = client.get("/static/scripts/ui_helpers.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    toggle_start = js.find("function toggleCollapsible(")
    assert toggle_start != -1, "toggleCollapsible function not found"
    toggle_end = js.find("\n  }", toggle_start)
    toggle_body = js[toggle_start:toggle_end]

    # The function must set aria-expanded to the inverted pre-toggle state
    assert 'setAttribute("aria-expanded", String(!isOpen))' in toggle_body


def test_toggle_collapsible_does_not_mutate_icon_text(client):
    """JTN-623: Chevron rotation must come from CSS, not JS textContent.

    Before the fix, the JS swapped icon.textContent between ▼ and ▲ while
    CSS also rotated the element 180deg via `[aria-expanded="true"]`. The
    two mechanisms cancelled out and the icon appeared unchanged when the
    section opened. The fix is to drop the textContent swap entirely and
    let CSS own the visual flip.
    """
    resp = client.get("/static/scripts/ui_helpers.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    toggle_start = js.find("function toggleCollapsible(")
    toggle_end = js.find("\n  }", toggle_start)
    toggle_body = js[toggle_start:toggle_end]

    # The JS must no longer mutate the icon's textContent — CSS handles it.
    assert "icon.textContent" not in toggle_body
    # And the ternary that used to swap characters must be gone.
    assert '"▼" : "▲"' not in toggle_body
    assert '"▲" : "▼"' not in toggle_body


def test_collapsible_css_rotates_icon_when_expanded(client):
    """The CSS contract: aria-expanded="true" rotates the chevron 180deg."""
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200
    css = resp.get_data(as_text=True)
    # Normalise whitespace for robust matching
    compact = " ".join(css.split())
    assert (
        '.collapsible-header[aria-expanded="true"] .collapsible-icon' in compact
    ), "CSS rule driving chevron rotation from aria-expanded is missing"
    assert "rotate(180deg)" in compact


def test_collapsible_icon_is_not_inline_so_transform_applies(client):
    """JTN-643: CSS `transform` has no visible effect on plain inline boxes.

    The chevron span relies on being rendered as a block-level box (via
    `float: right`, which implicitly computes display to block) so the
    `rotate(180deg)` rule actually flips it. If a future refactor drops the
    float without replacing it with an explicit non-inline display, the
    chevron would silently stay ▼ in every state — the exact regression
    JTN-643 reported.
    """
    resp = client.get("/static/styles/main.css")
    assert resp.status_code == 200
    css = resp.get_data(as_text=True)
    compact = " ".join(css.split())

    # Locate the `.collapsible-icon { ... }` declaration block.
    needle = ".collapsible-icon {"
    start = compact.find(needle)
    assert start != -1, "`.collapsible-icon` rule not found in bundled CSS"
    block_end = compact.find("}", start)
    block = compact[start:block_end]

    # Either `float: right` (which implicitly makes the box non-inline) or an
    # explicit non-inline `display` is required for `transform` to apply.
    has_float = "float: right" in block or "float:right" in block
    has_block_display = any(
        f"display: {mode}" in block or f"display:{mode}" in block
        for mode in ("block", "inline-block", "flex", "inline-flex", "grid")
    )
    assert has_float or has_block_display, (
        "`.collapsible-icon` must establish a non-inline box so `transform: "
        "rotate(180deg)` can actually flip the chevron. Add `float: right` "
        "or an explicit `display:` declaration."
    )


def test_collapsible_click_is_delegated_in_ui_helpers(client):
    """JTN-623: A document-level delegated click handler guarantees that
    every `[data-collapsible-toggle]` button toggles aria-expanded, even if
    a page-specific script forgot to wire its own listener.
    """
    resp = client.get("/static/scripts/ui_helpers.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)
    assert "[data-collapsible-toggle]" in js
    assert 'document.addEventListener("click"' in js
    # Guard flag prevents double-binding if the module is re-evaluated.
    assert "__inkypiCollapsibleBound" in js
