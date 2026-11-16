"""With "Increase contrast" on, the UI switches to stronger colours.

Checked in Chromium with the system preference emulated, in light and dark
mode and with each look from the Tweaks panel, since the paper and minimal
looks set their own dark colours. The accent hue slider sets only
--accent-h, so the high-contrast accent still wins after the user moves it.
"""

from __future__ import annotations

from typing import Literal

import pytest
from playwright.sync_api import Page, expect

_READ_TOKENS = """
([theme, aesthetic]) => {
  const root = document.documentElement;
  root.dataset.theme = theme;
  if (aesthetic) root.dataset.aesthetic = aesthetic;
  else delete root.dataset.aesthetic;
  const style = getComputedStyle(root);
  return {
    text: style.getPropertyValue("--text").trim(),
    border: style.getPropertyValue("--surface-border").trim(),
    accent: style.getPropertyValue("--accent").trim(),
    hue: style.getPropertyValue("--accent-h").trim(),
  };
}
"""

_SLIDER_HUE = "300"

_LOOKS = [
    ("light", None, "#000"),
    ("dark", None, "#fff"),
    ("dark", "paper", "#fff"),
    ("dark", "minimal", "#fff"),
]

# High-contrast accent per theme, and the lightness each look builds its
# normal accent with (so a theme switch also switches the lightness).
_STRONG_ACCENT = {"light": "#0066cc", "dark": "#4d9fff"}
_ACCENT_LIGHTNESS = {
    ("light", None): "50%",
    ("dark", None): "68%",
    ("dark", "paper"): "72%",
    ("dark", "minimal"): "68%",
}


def _tokens(
    page: Page, live_server: str, contrast: Literal["more", "no-preference"]
) -> list[dict[str, str]]:
    page.emulate_media(contrast=contrast)
    page.goto(f"{live_server}/settings", wait_until="domcontentloaded")
    page.wait_for_selector(".settings-console-layout")
    return [page.evaluate(_READ_TOKENS, [theme, look]) for theme, look, _ in _LOOKS]


def _tokens_after_slider(
    page: Page, live_server: str, contrast: Literal["more", "no-preference"]
) -> list[dict[str, str]]:
    """Move the Settings > Appearance hue slider, then read the tokens.

    Returns the live tokens (light theme) followed by the tokens for each look
    after a reload.
    """
    page.emulate_media(contrast=contrast)
    page.goto(f"{live_server}/settings", wait_until="domcontentloaded")
    page.wait_for_selector(".settings-console-layout")
    page.locator('[data-settings-tab="appearance"]').click()
    panel = page.locator("#settings-panel-appearance")
    panel.locator("[data-accent-slider]").fill(_SLIDER_HUE)
    expect(panel.locator("[data-accent-value]")).to_have_text(f"{_SLIDER_HUE}°")
    live = page.evaluate(_READ_TOKENS, ["light", None])
    # The early-paint script in base.html applies the saved hue on the next
    # load, before tweaks_panel.js runs, so check that path too.
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector(".settings-console-layout")
    after_reload = [
        page.evaluate(_READ_TOKENS, [theme, look]) for theme, look, _ in _LOOKS
    ]
    return [live, *after_reload]


def test_increase_contrast_uses_strong_colours(
    live_server: str, browser_page: Page
) -> None:
    got = _tokens(browser_page, live_server, "more")
    expected = [
        {"text": colour, "border": colour, "accent": _STRONG_ACCENT[theme], "hue": ""}
        for theme, _, colour in _LOOKS
    ]
    assert got == expected


def test_increase_contrast_wins_over_accent_slider(
    live_server: str, browser_page: Page
) -> None:
    live, *reloaded = _tokens_after_slider(browser_page, live_server, "more")
    assert live["hue"] == _SLIDER_HUE
    assert live["accent"] == _STRONG_ACCENT["light"]
    for (theme, look, _), tokens in zip(_LOOKS, reloaded, strict=True):
        assert tokens["hue"] == _SLIDER_HUE, (theme, look, tokens)
        assert tokens["accent"] == _STRONG_ACCENT[theme], (theme, look, tokens)


def test_accent_slider_keeps_each_theme_lightness(
    live_server: str, browser_page: Page
) -> None:
    live, *reloaded = _tokens_after_slider(browser_page, live_server, "no-preference")
    assert live["accent"] == f"oklch(50% 0.08 {_SLIDER_HUE})"
    for (theme, look, _), tokens in zip(_LOOKS, reloaded, strict=True):
        lightness = _ACCENT_LIGHTNESS[(theme, look)]
        assert tokens["accent"].startswith(f"oklch({lightness} "), (
            theme,
            look,
            tokens,
        )
        assert tokens["accent"].endswith(f" {_SLIDER_HUE})"), (theme, look, tokens)


def test_normal_contrast_keeps_theme_colours(
    live_server: str, browser_page: Page
) -> None:
    got = _tokens(browser_page, live_server, "no-preference")
    for (theme, look, strong), tokens in zip(_LOOKS, got, strict=True):
        assert tokens["text"], (theme, look)
        assert tokens["text"] != strong, (theme, look, tokens)


@pytest.mark.parametrize("contrast", ["more", "no-preference"])
def test_contrast_preference_is_reported(
    live_server: str, browser_page: Page, contrast: Literal["more", "no-preference"]
) -> None:
    """Guards the emulation itself, so a no-op can't pass the tests above."""
    browser_page.emulate_media(contrast=contrast)
    browser_page.goto(f"{live_server}/settings", wait_until="domcontentloaded")
    assert browser_page.evaluate(
        f"matchMedia('(prefers-contrast: {contrast})').matches"
    )
