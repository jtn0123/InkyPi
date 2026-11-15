"""The playlist thumbnail preview must request a URL the app actually serves.

modals.js used to build ``/plugin_instance_image/<playlist>/<plugin>/<instance>``,
which matches no route, so clicking a thumbnail opened a broken image.
"""

from __future__ import annotations

import re
from pathlib import Path

from flask import Flask

MODALS_JS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "static"
    / "scripts"
    / "playlist"
    / "modals.js"
)


def _preview_url_template() -> str:
    js = MODALS_JS.read_text(encoding="utf-8")
    fn = js[js.index("function showThumbnailPreview(") :]
    match = re.search(r"img\.src\s*=\s*`([^`]+)`", fn)
    assert match, "showThumbnailPreview no longer sets img.src from a template"
    # Replace each ${...} interpolation with a sample path segment.
    return re.sub(r"\$\{[^}]*\}", "sample", re.sub(r"\s+", "", match.group(1)))


def test_thumbnail_preview_url_matches_the_instance_image_route(
    flask_app: Flask,
) -> None:
    url = _preview_url_template()
    adapter = flask_app.url_map.bind("localhost")
    endpoint, args = adapter.match(url, method="GET")
    assert endpoint == "plugin.plugin_instance_image"
    assert args == {"plugin_id": "sample", "instance_name": "sample"}
