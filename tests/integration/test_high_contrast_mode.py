"""With "Increase contrast" on, the UI switches to stronger colours.

Checked in Chromium with the system preference emulated, in light and dark
mode and with each look from the Tweaks panel, since the paper and minimal
looks set their own dark colours.
"""

from __future__ import annotations

from typing import Literal

import pytest
from playwright.sync_api import Page

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
  };
}
"""

_LOOKS = [
    ("light", None, "#000"),
    ("dark", None, "#fff"),
    ("dark", "paper", "#fff"),
    ("dark", "minimal", "#fff"),
]


def _tokens(
    page: Page, live_server: str, contrast: Literal["more", "no-preference"]
) -> list[dict[str, str]]:
    page.emulate_media(contrast=contrast)
    page.goto(f"{live_server}/settings", wait_until="domcontentloaded")
    page.wait_for_selector(".settings-console-layout")
    return [page.evaluate(_READ_TOKENS, [theme, look]) for theme, look, _ in _LOOKS]


def test_increase_contrast_uses_strong_colours(
    live_server: str, browser_page: Page
) -> None:
    got = _tokens(browser_page, live_server, "more")
    expected = [{"text": colour, "border": colour} for _, _, colour in _LOOKS]
    assert got == expected


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
