# pyright: reportMissingImports=false
"""Tests that mobile media queries enforce 36px minimum touch targets (JTN-223)."""

import re
from pathlib import Path

_STYLES_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "styles"


def _read_all_css() -> str:
    parts = [
        p.read_text(encoding="utf-8")
        for p in sorted(_STYLES_DIR.glob("partials/_*.css"))
    ]
    return "\n".join(parts)


def _extract_mobile_768_blocks(css: str) -> str:
    """Return concatenated content of all @media (max-width: 768px) blocks."""
    # Use a simple brace-depth scanner to extract block bodies
    pattern = r"@media\s*\(\s*max-width\s*:\s*768px\s*\)"
    blocks: list[str] = []
    for match in re.finditer(pattern, css):
        start = match.end()
        # Skip whitespace to the opening brace
        i = start
        while i < len(css) and css[i] in " \t\n\r":
            i += 1
        if i >= len(css) or css[i] != "{":
            continue
        depth = 0
        block_start = i
        for j in range(i, len(css)):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(css[block_start + 1 : j])
                    break
    return "\n".join(blocks)


def test_mobile_768_enforces_min_height_on_buttons(client):
    """@media (max-width: 768px) block sets min-height: 36px on buttons."""
    mobile = _extract_mobile_768_blocks(_read_all_css())
    assert mobile, "No @media (max-width: 768px) block found"
    assert "min-height: 36px" in mobile, (
        "No min-height: 36px rule found inside @media (max-width: 768px). "
        "Mobile touch targets for buttons must be at least 36px (JTN-223)."
    )


def test_mobile_768_enforces_min_width_on_buttons(client):
    """@media (max-width: 768px) block sets min-width: 36px on buttons."""
    mobile = _extract_mobile_768_blocks(_read_all_css())
    assert "min-width: 36px" in mobile, (
        "No min-width: 36px rule found inside @media (max-width: 768px). "
        "Mobile touch targets must be at least 36px wide (JTN-223)."
    )


def test_mobile_768_covers_core_interactive_selectors(client):
    """Touch-target block covers button, .btn, select and input[type='checkbox']."""
    mobile = _extract_mobile_768_blocks(_read_all_css())
    for selector in ("button", ".btn", "select", 'input[type="checkbox"]'):
        assert selector in mobile, (
            f"Selector '{selector}' not found in @media (max-width: 768px). "
            "All interactive controls need touch-target coverage (JTN-223)."
        )


def test_mobile_768_enlarges_checkbox_radio(client):
    """Checkboxes and radios get explicit width/height inside mobile block."""
    mobile = _extract_mobile_768_blocks(_read_all_css())
    # The block should size checkboxes/radios to 20px so they're tappable
    assert (
        'input[type="checkbox"]' in mobile or "input[type=checkbox]" in mobile
    ), "input[type='checkbox'] missing from @media (max-width: 768px) (JTN-223)."
    assert (
        'input[type="radio"]' in mobile or "input[type=radio]" in mobile
    ), "input[type='radio'] missing from @media (max-width: 768px) (JTN-223)."


def test_touch_target_rules_not_in_desktop_styles(client):
    """The 36px touch-target rules must live inside a mobile media query, not globally."""
    css = _read_all_css()

    # Build a version with media blocks removed entirely
    result: list[str] = []
    depth = 0
    in_media = False
    i = 0
    while i < len(css):
        # Detect '@media'
        if css[i : i + 6] == "@media" and depth == 0:
            in_media = True
            # skip to opening brace
            while i < len(css) and css[i] != "{":
                i += 1
            depth = 1
            i += 1
            continue
        if in_media:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    in_media = False
        else:
            result.append(css[i])
        i += 1

    global_css = "".join(result)
    assert "min-height: 36px" not in global_css, (
        "min-height: 36px was found outside a @media block — "
        "touch-target overrides must be scoped to mobile breakpoints (JTN-223)."
    )
