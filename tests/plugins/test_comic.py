# pyright: reportMissingImports=false
from io import BytesIO

import pytest
from PIL import Image

@pytest.fixture()
def plugin_config():
    return {"id": "comic", "class": "Comic", "name": "Comic"}

def _png_bytes(size=(30, 20), color="black"):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()

def test_generate_settings_template_contains_comics(plugin_config):
    from plugins.comic.comic import COMICS, Comic

    p = Comic(plugin_config)
    t = p.generate_settings_template()
    assert "comics" in t
    assert set(COMICS).issubset(set(t["comics"]))

def test_generate_image_valid_flow_horizontal(
    monkeypatch, plugin_config, device_config_dev
):
    from plugins.comic.comic import Comic

    # mock get_panel (upstream uses comic_parser.get_panel instead of get_image_url)
    monkeypatch.setattr(
        "plugins.comic.comic_parser.get_panel",
        lambda c: {"image_url": "http://img/latest.png", "title": "Test", "caption": "Test caption"},
    )

    # mock requests.get streaming for image bytes
    class Resp:
        status_code = 200
        raw = BytesIO(_png_bytes((400, 300)))

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "requests.get", lambda url, **kwargs: Resp()
    )

    p = Comic(plugin_config)
    img = p.generate_image({"comic": "XKCD"}, device_config_dev)
    assert img is not None
    assert img.size == device_config_dev.get_resolution()

def test_generate_image_vertical_orientation(
    monkeypatch, plugin_config, device_config_dev
):
    from plugins.comic.comic import Comic

    # set device to vertical
    device_config_dev.update_value("orientation", "vertical")

    monkeypatch.setattr(
        "plugins.comic.comic_parser.get_panel",
        lambda c: {"image_url": "http://img/latest.png", "title": "Test", "caption": "Test caption"},
    )

    class Resp:
        status_code = 200
        raw = BytesIO(_png_bytes((400, 300)))

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "requests.get", lambda url, **kwargs: Resp()
    )

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

def test_generate_image_centering(monkeypatch, plugin_config, device_config_dev):
    from plugins.comic.comic import Comic

    monkeypatch.setattr(
        "plugins.comic.comic_parser.get_panel",
        lambda c: {"image_url": "http://img/latest.png", "title": "", "caption": ""},
    )

    # create a tall/narrow source so centering is apparent
    src_w, src_h = 100, 300

    class Resp:
        status_code = 200
        raw = BytesIO(_png_bytes((src_w, src_h), color="black"))

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "requests.get", lambda url, **kwargs: Resp()
    )

    p = Comic(plugin_config)
    img = p.generate_image({"comic": "XKCD", "titleCaption": "false"}, device_config_dev)

    # Ensure white background and image centered (check corners are white)
    w, h = device_config_dev.get_resolution()
    assert img.getpixel((0, 0)) == (255, 255, 255)
    assert img.getpixel((w - 1, 0)) == (255, 255, 255)
    assert img.getpixel((0, h - 1)) == (255, 255, 255)
    assert img.getpixel((w - 1, h - 1)) == (255, 255, 255)
