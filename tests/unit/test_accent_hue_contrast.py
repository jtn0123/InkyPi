"""Accent buttons stay readable at every hue the Tweaks slider allows.

The slider sets only ``--accent-h``; the tokens build ``--accent`` and
``--accent-hover`` from it with each theme's own lightness and chroma. This
reads those values from ``_tokens.css`` and checks the WCAG contrast of the
button text (``--accent-ink``) on both, for every whole hue from 0 to 360, so
a lightness change in the tokens can't quietly make some hues unreadable.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

_TOKENS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "static"
    / "styles"
    / "partials"
    / "_tokens.css"
)

# WCAG AA for normal-size text; button labels are 14-16px.
_MIN_CONTRAST = 4.5

_HUE_OKLCH = re.compile(
    r"oklch\(\s*([\d.]+)%\s+([\d.]+)\s+var\(--accent-h,\s*([\d.]+)\)\s*\)"
)
_HEX = re.compile(r"#[0-9a-fA-F]{6}")

Rgb = tuple[float, float, float]


def _block(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.DOTALL)
    assert match, f"{selector} block not found in {_TOKENS.name}"
    return match.group(1)


def _value(block: str, name: str) -> str:
    match = re.search(rf"^\s*{re.escape(name)}:\s*([^;]+);", block, re.MULTILINE)
    assert match, f"{name} not declared"
    return match.group(1).strip()


def _oklch_to_linear_srgb(lightness: float, chroma: float, hue: float) -> Rgb:
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rgb = (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )
    # A few hover hues sit just outside sRGB; the browser maps them in.
    r, g, bl = (min(1.0, max(0.0, c)) for c in rgb)
    return r, g, bl


def _hex_to_linear_srgb(value: str) -> Rgb:
    channels = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    )
    return r, g, b


def _colour(value: str, hue: int) -> Rgb:
    """Resolve a token value to linear sRGB with ``--accent-h`` set to hue."""
    if match := _HUE_OKLCH.fullmatch(value):
        return _oklch_to_linear_srgb(
            float(match.group(1)) / 100, float(match.group(2)), hue
        )
    if _HEX.fullmatch(value):
        return _hex_to_linear_srgb(value)
    raise AssertionError(f"unexpected accent token value: {value}")


def _contrast(a: Rgb, b: Rgb) -> float:
    def luminance(c: Rgb) -> float:
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _theme_tokens() -> dict[str, dict[str, str]]:
    css = _TOKENS.read_text(encoding="utf-8")
    names = ("--accent", "--accent-hover", "--accent-ink")
    light = {n: _value(_block(css, ":root"), n) for n in names}
    dark = {n: _value(_block(css, '[data-theme="dark"]'), n) for n in names}
    paper_block = _block(css, '[data-theme="dark"][data-aesthetic="paper"]')
    paper = {**dark, **{n: _value(paper_block, n) for n in names}}
    return {"light": light, "dark": dark, "dark-paper": paper}


_THEMES = _theme_tokens()


def test_accent_tokens_follow_the_hue_variable() -> None:
    """The slider can only recolour accents that are built from --accent-h."""
    for theme, tokens in _THEMES.items():
        for name in ("--accent", "--accent-hover"):
            assert _HUE_OKLCH.fullmatch(tokens[name]), (theme, name, tokens[name])


@pytest.mark.parametrize("theme", sorted(_THEMES))
@pytest.mark.parametrize("background", ["--accent", "--accent-hover"])
def test_button_text_is_readable_at_every_hue(theme: str, background: str) -> None:
    tokens = _THEMES[theme]
    worst = min(
        (
            _contrast(
                _colour(tokens["--accent-ink"], hue), _colour(tokens[background], hue)
            ),
            hue,
        )
        for hue in range(361)
    )
    assert worst[0] >= _MIN_CONTRAST, (
        f"{theme}: --accent-ink on {background} is {worst[0]:.2f}:1 at hue "
        f"{worst[1]}"
    )
