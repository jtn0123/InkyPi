# pyright: reportMissingImports=false
from io import BytesIO
from PIL import Image
import types
import pytest


@pytest.fixture()
def plugin_config():
    return {"id": "comic", "class": "Comic", "name": "Comic"}


def _png_bytes(size=(30, 20), color="black"):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_generate_settings_template_contains_comics(plugin_config):
    from plugins.comic.comic import Comic, COMICS
    p = Comic(plugin_config)
    t = p.generate_settings_template()
    assert "comics" in t
    assert set(COMICS).issubset(set(t["comics"]))


def test_generate_image_valid_flow_horizontal(monkeypatch, plugin_config, device_config_dev):
    from plugins.comic.comic import Comic

    # mock RSS image URL parsing
    monkeypatch.setattr("plugins.comic.comic.Comic.get_image_url", lambda self, c: "http://img/latest.png")

    # mock requests.get streaming for image bytes
    class Resp:
        status_code = 200
        content = _png_bytes((400, 300))
        def raise_for_status(self):
            return None

    monkeypatch.setattr("plugins.comic.comic.requests.get", lambda url, stream=True, timeout=20: Resp())

    p = Comic(plugin_config)
    img = p.generate_image({"comic": "XKCD"}, device_config_dev)
    assert img is not None
    assert img.size == device_config_dev.get_resolution()


def test_generate_image_vertical_orientation(monkeypatch, plugin_config, device_config_dev):
    from plugins.comic.comic import Comic

    # set device to vertical
    device_config_dev.update_value("orientation", "vertical")

    monkeypatch.setattr("plugins.comic.comic.Comic.get_image_url", lambda self, c: "http://img/latest.png")

    class Resp:
        status_code = 200
        content = _png_bytes((400, 300))
        def raise_for_status(self):
            return None

    monkeypatch.setattr("plugins.comic.comic.requests.get", lambda url, stream=True, timeout=20: Resp())

    p = Comic(plugin_config)
    img = p.generate_image({"comic": "XKCD"}, device_config_dev)
    assert img is not None
    # ensure swapped
    w, h = device_config_dev.get_resolution()
    assert img.size == (h, w)


def test_generate_image_invalid_comic_raises(plugin_config, device_config_dev):
    from plugins.comic.comic import Comic
    p = Comic(plugin_config)
    with pytest.raises(RuntimeError):
        p.generate_image({"comic": "NotARealOne"}, device_config_dev)


def test_get_image_url_bad_feed_raises(monkeypatch, plugin_config):
    from plugins.comic.comic import Comic

    class Entry:
        def __init__(self):
            self.summary = "<p>No image here</p>"

    class FakeFeed:
        entries = [Entry()]

    # Force path into one of the branches and return no <img>
    monkeypatch.setattr("plugins.comic.comic.feedparser.parse", lambda url: FakeFeed())

    p = Comic(plugin_config)
    with pytest.raises(RuntimeError):
        p.get_image_url("XKCD")


