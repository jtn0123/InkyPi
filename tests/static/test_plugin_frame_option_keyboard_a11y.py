"""Regression guard for JTN-279: frame-option must be a native button element."""

import re
from pathlib import Path

_TEMPLATE = Path(__file__).resolve().parents[2] / "src" / "templates" / "plugin.html"


def test_frame_option_is_button_not_div():
    """data-frame-option element must be <button>, not <div>.

    A native <button> provides keyboard activation (Enter/Space) for free and
    removes the need for tabindex="0" and role="button" workarounds.
    """
    content = _TEMPLATE.read_text(encoding="utf-8")
    # Must NOT be a <div> with data-frame-option
    div_frame_option = re.search(r"<div[^>]*data-frame-option", content)
    assert div_frame_option is None, (
        "data-frame-option should be a <button>, not a <div>. "
        "Use semantic HTML for built-in keyboard accessibility."
    )


def test_frame_option_button_has_type_button():
    """The frame-option button must have type='button' to prevent form submission."""
    content = _TEMPLATE.read_text(encoding="utf-8")
    button_match = re.search(r"<button[^>]*data-frame-option[^>]*>", content)
    assert button_match is not None, "data-frame-option element not found as <button>"
    assert 'type="button"' in button_match.group(
        0
    ), "Frame option button must have type='button' to avoid accidental form submission."


def test_frame_option_button_has_aria_label():
    """The frame-option button must have an aria-label for screen readers."""
    content = _TEMPLATE.read_text(encoding="utf-8")
    button_match = re.search(r"<button[^>]*data-frame-option[^>]*>", content)
    assert button_match is not None, "data-frame-option element not found as <button>"
    assert "aria-label=" in button_match.group(
        0
    ), "Frame option button must have aria-label for screen reader users."


def test_image_option_css_has_transparent_background():
    """The .image-option CSS must set background: transparent so button elements render correctly."""
    # JTN-504: .image-option moved from _components.css to _form.css during
    # the per-component CSS reshape. Read the built main.css so this test is
    # resilient to future partial reorganizations.
    css_path = (
        Path(__file__).resolve().parents[2] / "src" / "static" / "styles" / "main.css"
    )
    content = css_path.read_text(encoding="utf-8")
    # Find the .image-option block and verify background is reset
    match = re.search(r"\.image-option\s*\{([^}]+)\}", content)
    assert match is not None, ".image-option CSS rule not found"
    rule_body = match.group(1)
    assert (
        "background" in rule_body
    ), ".image-option must set background: transparent so <button> renders like <div>."
