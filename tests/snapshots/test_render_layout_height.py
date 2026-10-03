# pyright: reportMissingImports=false
"""Plugin render pages must fill the viewport in standards mode.

``base_plugin/render/plugin.html`` declares ``<!DOCTYPE html>``. In standards
mode ``body`` gets an auto height, so every ``height: 100%`` and container-query
(``cqh``) layout beneath it collapses to zero. That silently blanked AI Text
(0px fonts) and To-Do List (empty cards) and pinned Countdown to the top edge.
These checks render through real Chromium so a regression shows up as a test
failure rather than a blank e-ink panel.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

_requires_browser = pytest.mark.skipif(
    os.getenv("REQUIRE_BROWSER_SMOKE", "").lower() not in ("1", "true"),
    reason=(
        "Renders HTML via Playwright Chromium. Set REQUIRE_BROWSER_SMOKE=1 to "
        "run it (see tests/snapshots/README.md)."
    ),
)

_PLUGINS_DIR = Path(__file__).resolve().parents[2] / "src" / "plugins"


def _dark_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of non-white pixels, or None when the render is blank."""
    gray = image.convert("L").point(lambda value: 255 if value < 200 else 0)
    return gray.getbbox()


def _ai_text_plugin() -> Any:
    from plugins.ai_text.ai_text import AIText

    info = json.loads((_PLUGINS_DIR / "ai_text" / "plugin-info.json").read_text())
    return AIText(info)


@_requires_browser
def test_ai_text_render_is_not_blank_and_is_vertically_centred() -> None:
    plugin = _ai_text_plugin()
    image = plugin.render_image(
        (800, 480),
        "ai_text.html",
        "ai_text.css",
        {
            "title": "Title",
            "content": "A short quote for the panel.",
            "plugin_settings": {},
        },
    )

    bbox = _dark_bbox(image)
    assert bbox is not None, "AI Text rendered a blank image"
    top, bottom = bbox[1], bbox[3]
    # Collapsed layouts either draw nothing or pin text to the top edge.
    assert top > 100, f"text starts at y={top}; layout is not vertically centred"
    assert bottom < 380, f"text ends at y={bottom}; layout is not vertically centred"


@_requires_browser
def test_body_height_tracks_custom_margins() -> None:
    plugin = _ai_text_plugin()
    image = plugin.render_image(
        (800, 480),
        "ai_text.html",
        "ai_text.css",
        {
            "title": "Title",
            "content": "Body",
            "plugin_settings": {"topMargin": "40", "bottomMargin": "40"},
        },
    )

    bbox = _dark_bbox(image)
    assert bbox is not None, "AI Text rendered a blank image with custom margins"
    centre = (bbox[1] + bbox[3]) / 2
    assert abs(centre - 240) < 40, f"content centre y={centre} drifted from 240"
