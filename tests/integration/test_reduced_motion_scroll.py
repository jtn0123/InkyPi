"""With "reduce motion" on, the settings page jumps instead of gliding.

On a phone, "Show live logs" scrolls down to the logs panel. With the
system's reduce-motion setting it must land there at once; otherwise it
animates. Checked on the real page in Chromium, which (unlike the
stylesheet's prefers-reduced-motion rule) is what a scripted
``scrollIntoView`` actually obeys.
"""

from __future__ import annotations

from typing import Literal

import pytest
from playwright.sync_api import Page

# Read straight after the click, before the next animation frame can move
# the page. A jump is already at its target; a smooth scroll has barely
# started.
_CLICK_AND_READ = """
() => {
  const button = document.querySelector('[aria-controls="settingsLogsPanel"]');
  button.click();
  return {
    scrollY: window.scrollY,
    target: document.getElementById("settingsLogsPanel").getBoundingClientRect().top
      + window.scrollY,
  };
}
"""


def _open_live_logs(
    page: Page, live_server: str, reduced_motion: Literal["reduce", "no-preference"]
) -> dict[str, float]:
    page.emulate_media(reduced_motion=reduced_motion)
    page.goto(f"{live_server}/settings", wait_until="domcontentloaded")
    page.wait_for_selector(".settings-console-layout")
    position: dict[str, float] = page.evaluate(_CLICK_AND_READ)
    return position


def test_live_logs_jump_when_motion_is_reduced(
    live_server: str, mobile_page: Page
) -> None:
    position = _open_live_logs(mobile_page, live_server, "reduce")
    assert position["target"] > 500, "the logs panel should be below the fold"
    assert position["scrollY"] == pytest.approx(position["target"], abs=80)


def test_live_logs_glide_otherwise(live_server: str, mobile_page: Page) -> None:
    position = _open_live_logs(mobile_page, live_server, "no-preference")
    assert position["target"] > 500
    assert position["scrollY"] < position["target"] / 2
