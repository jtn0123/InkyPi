# pyright: reportMissingImports=false
"""Tests for plugins/comic/comic.py — additional coverage for error paths."""
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


@pytest.fixture()
def plugin_config():
    return {"id": "comic", "class": "Comic", "name": "Comic"}


def test_comic_http_error(monkeypatch, plugin_config, device_config_dev):
    from plugins.comic.comic import Comic

    monkeypatch.setattr(
        "plugins.comic.comic_parser.get_panel",
        lambda c: {"image_url": "http://img/broken.png", "title": "X", "caption": "Y"},
    )

    # Make image_loader.from_url return None to simulate failed download
    p = Comic(plugin_config)
    p.image_loader = MagicMock()
    p.image_loader.from_url.return_value = None

    with pytest.raises(RuntimeError, match="Failed to load comic image"):
        p.generate_image({"comic": "XKCD"}, device_config_dev)


def test_comic_invalid_image(monkeypatch, plugin_config, device_config_dev):
    from plugins.comic.comic import Comic

    monkeypatch.setattr(
        "plugins.comic.comic_parser.get_panel",
        lambda c: {"image_url": "http://img/bad.png", "title": "", "caption": ""},
    )

    # Make image_loader.from_url raise an exception
    p = Comic(plugin_config)
    p.image_loader = MagicMock()
    p.image_loader.from_url.side_effect = Exception("decode error")

    with pytest.raises(Exception):
        p.generate_image({"comic": "XKCD"}, device_config_dev)
