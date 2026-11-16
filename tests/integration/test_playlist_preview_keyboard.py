# pyright: reportMissingImports=false
"""The playlist thumbnail opens its full-size preview from the keyboard.

The thumbnail was a plain box with a click handler, so only a mouse could
open the preview: Tab skipped it and a screen reader didn't announce it.
It is now a button named after the item.

The preview is the shared lightbox the dashboard and plugin pages use; the
playlist page used to carry its own copy.
"""

from __future__ import annotations

import os
import re
from typing import Any

import pytest
from PIL import Image
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true"),
    reason="UI interactions skipped by env",
)

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402


def _playlist_with_a_rendered_item(device_config_dev: Any) -> None:
    """One playlist item that has been shown, so its thumbnail is on the page."""
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pm.get_playlist("Default").add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock A",
            "plugin_settings": {},
            "refresh": {"interval": 300},
            "latest_refresh_time": "2025-01-01T07:55:00+00:00",
        }
    )
    device_config_dev.write_config()
    path = device_config_dev.get_plugin_image_path("clock", "Clock A")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (80, 48), "white").save(path)


@pytest.mark.parametrize("key", ["Enter", " "])
def test_thumbnail_preview_opens_from_the_keyboard_and_gives_focus_back(
    live_server: str, device_config_dev: Any, browser_page: Page, key: str
) -> None:
    _playlist_with_a_rendered_item(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")

    thumb = page.get_by_role("button", name="Preview Clock A")
    expect(thumb).to_be_visible()  # the image loaded, so the tile stayed
    thumb.focus()
    expect(thumb).to_be_focused()

    page.keyboard.press(key)
    modal = page.locator("#imagePreviewModal")
    expect(modal).to_be_visible()
    image = page.locator("#imagePreviewImg")
    expect(image).to_have_attribute("src", "/instance_image/clock/Clock%20A")
    expect(image).to_have_attribute("alt", "Clock A preview")
    expect(image).to_be_visible()  # loaded, so the spinner made way for it
    expect(page.locator("body")).to_have_class(re.compile(r"\bmodal-open\b"))

    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
    expect(thumb).to_be_focused()
    expect(page.locator("body")).not_to_have_class(re.compile(r"\bmodal-open\b"))


def test_thumbnail_preview_closes_on_a_click_outside_the_image(
    live_server: str, device_config_dev: Any, browser_page: Page
) -> None:
    _playlist_with_a_rendered_item(device_config_dev)
    page = browser_page
    navigate_and_wait(page, live_server, "/playlist")

    page.get_by_role("button", name="Preview Clock A").click()
    modal = page.locator("#imagePreviewModal")
    expect(page.locator("#imagePreviewImg")).to_be_visible()

    modal.click(position={"x": 5, "y": 5})  # the backdrop, not the image
    expect(modal).to_be_hidden()
    expect(page.locator("body")).not_to_have_class(re.compile(r"\bmodal-open\b"))
