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

    # mock RSS image URL parsing
    monkeypatch.setattr(
        "plugins.comic.comic.Comic.get_image_url",
        lambda self, c: "http://img/latest.png",
    )

    # mock requests.get streaming for image bytes
    class Resp:
        status_code = 200
        content = _png_bytes((400, 300))

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "plugins.comic.comic.requests.get", lambda url, stream=True, timeout=20: Resp()
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
        "plugins.comic.comic.Comic.get_image_url",
        lambda self, c: "http://img/latest.png",
    )

    class Resp:
        status_code = 200
        content = _png_bytes((400, 300))

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "plugins.comic.comic.requests.get", lambda url, stream=True, timeout=20: Resp()
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


def test_get_image_url_bad_feed_raises(monkeypatch, plugin_config):
    from plugins.comic.comic import Comic

    class Entry:
        def __init__(self):
            self.summary = "<p>No image here</p>"
            self.description = "<div>still none</div>"
            self.content = []

    class FakeFeed:
        entries = [Entry()]

    # Force path into one of the branches and return no <img>
    monkeypatch.setattr("plugins.comic.comic.feedparser.parse", lambda url: FakeFeed())

    p = Comic(plugin_config)
    with pytest.raises(RuntimeError):
        p.get_image_url("XKCD")


def test_get_image_url_parsing_all_comics(monkeypatch, plugin_config):
    from plugins.comic.comic import Comic

    # Entry stub that supports attribute access and dict-like get for 'content'
    class Entry:
        def __init__(self):
            self._map = {}

        def get(self, key, default=None):
            return self._map.get(key, default)

    class Feed:
        def __init__(self, setter):
            e = Entry()
            setter(e)
            self.entries = [e]

    # Map actual feed URLs used in implementation to a setter that populates entry
    def feed_for_url(url: str):
        mapping = {
            "https://xkcd.com/atom.xml": lambda e: setattr(
                e, "summary", '<p><img src="http://xkcd/latest.png"></p>'
            ),
            "http://www.smbc-comics.com/comic/rss": lambda e: setattr(
                e, "description", '<div><img src="http://smbc/latest.jpg"/></div>'
            ),
            "http://www.questionablecontent.net/QCRSS.xml": lambda e: setattr(
                e, "description", '<div><img src="http://qc/latest.jpg"/></div>'
            ),
            "https://pbfcomics.com/feed/": lambda e: setattr(
                e, "description", '<div><img src="http://pbf/latest.png"/></div>'
            ),
            # For Poorly Drawn Lines, implementation uses entry.get('content', [{}])[0]['value']
            "https://poorlydrawnlines.com/feed/": lambda e: e._map.update(
                {
                    "content": [
                        {"value": '<div><img src="http://pdl/latest.png"/></div>'}
                    ]
                }
            ),
            "https://www.qwantz.com/rssfeed.php": lambda e: setattr(
                e, "summary", '<p><img src="http://dino/latest.png"></p>'
            ),
            "https://explosm-1311.appspot.com/": lambda e: setattr(
                e, "summary", '<p><img src="http://cnh/latest.png"></p>'
            ),
        }
        setter = mapping.get(url)
        assert setter is not None, f"Unexpected URL called: {url}"
        return Feed(setter)

    monkeypatch.setattr("plugins.comic.comic.feedparser.parse", feed_for_url)

    p = Comic(plugin_config)
    # Validate each branch returns an image URL
    assert p.get_image_url("XKCD").endswith((".png", ".jpg"))
    assert p.get_image_url("Saturday Morning Breakfast Cereal").endswith(
        (".png", ".jpg")
    )
    assert p.get_image_url("Questionable Content").endswith((".png", ".jpg"))
    assert p.get_image_url("The Perry Bible Fellowship").endswith((".png", ".jpg"))
    assert p.get_image_url("Poorly Drawn Lines").endswith((".png", ".jpg"))
    assert p.get_image_url("Dinosaur Comics").endswith((".png", ".jpg"))
    assert p.get_image_url("Cyanide & Happiness").endswith((".png", ".jpg"))


def test_generate_image_retries_without_timeout_arg(
    monkeypatch, plugin_config, device_config_dev
):
    from plugins.comic.comic import Comic

    monkeypatch.setattr(
        "plugins.comic.comic.Comic.get_image_url",
        lambda self, c: "http://img/latest.png",
    )

    class Resp:
        status_code = 200
        content = _png_bytes((50, 50))

        def raise_for_status(self):
            return None

    calls = {"count": 0}

    def fake_get(url, stream=True, timeout=20):
        if calls["count"] == 0:
            calls["count"] += 1
            raise TypeError("timeout not supported")
        return Resp()

    monkeypatch.setattr("plugins.comic.comic.requests.get", fake_get)

    p = Comic(plugin_config)
    img = p.generate_image({"comic": "XKCD"}, device_config_dev)
    assert img is not None
    assert calls["count"] == 1  # retried once without timeout


def test_generate_image_centering(monkeypatch, plugin_config, device_config_dev):
    from plugins.comic.comic import Comic

    monkeypatch.setattr(
        "plugins.comic.comic.Comic.get_image_url",
        lambda self, c: "http://img/latest.png",
    )

    # create a tall/narrow source so centering is apparent
    src_w, src_h = 100, 300

    class Resp:
        status_code = 200
        content = _png_bytes((src_w, src_h), color="black")

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "plugins.comic.comic.requests.get", lambda url, stream=True, timeout=20: Resp()
    )

    p = Comic(plugin_config)
    img = p.generate_image({"comic": "XKCD"}, device_config_dev)

    # Ensure white background and image centered (check corners are white)
    w, h = device_config_dev.get_resolution()
    assert img.getpixel((0, 0)) == (255, 255, 255)
    assert img.getpixel((w - 1, 0)) == (255, 255, 255)
    assert img.getpixel((0, h - 1)) == (255, 255, 255)
    assert img.getpixel((w - 1, h - 1)) == (255, 255, 255)
