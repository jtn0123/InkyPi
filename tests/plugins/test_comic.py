# pyright: reportMissingImports=false
from io import BytesIO
from typing import Any

import pytest
from PIL import Image


@pytest.fixture()
def plugin_config() -> Any:
    return {"id": "comic", "class": "Comic", "name": "Comic"}


def _png_bytes(size: Any = (30, 20), color: Any = "black") -> Any:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_generate_settings_template_contains_comics(plugin_config: Any) -> None:
    from plugins.comic.comic import COMICS, Comic

    p = Comic(plugin_config)
    t = p.generate_settings_template()
    assert "comics" in t
    assert set(COMICS).issubset(set(t["comics"]))
    assert "settings_schema" in t


def test_generate_image_valid_flow_horizontal(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> Any:
    from plugins.comic.comic import Comic

    # mock get_panel (upstream uses comic_parser.get_panel instead of get_image_url)
    monkeypatch.setattr(
        "plugins.comic.comic_parser.get_panel",
        lambda c: {
            "image_url": "http://img/latest.png",
            "title": "Test",
            "caption": "Test caption",
        },
    )

    # mock requests.get streaming for image bytes
    class Resp:
        status_code = 200
        raw = BytesIO(_png_bytes((400, 300)))

        def raise_for_status(self) -> Any:
            return None

    monkeypatch.setattr("requests.get", lambda url, **kwargs: Resp())

    p = Comic(plugin_config)
    img = p.generate_image({"comic": "XKCD"}, device_config_dev)
    assert img is not None
    assert img.size == device_config_dev.get_resolution()


def test_generate_image_vertical_orientation(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> Any:
    from plugins.comic.comic import Comic

    # set device to vertical
    device_config_dev.update_value("orientation", "vertical")

    monkeypatch.setattr(
        "plugins.comic.comic_parser.get_panel",
        lambda c: {
            "image_url": "http://img/latest.png",
            "title": "Test",
            "caption": "Test caption",
        },
    )

    class Resp:
        status_code = 200
        raw = BytesIO(_png_bytes((400, 300)))

        def raise_for_status(self) -> Any:
            return None

    monkeypatch.setattr("requests.get", lambda url, **kwargs: Resp())

    p = Comic(plugin_config)
    img = p.generate_image({"comic": "XKCD"}, device_config_dev)
    assert img is not None
    # ensure swapped
    w, h = device_config_dev.get_resolution()
    assert img.size == (h, w)


def test_generate_image_invalid_comic_falls_back_to_xkcd(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> Any:
    """JTN-784: an invalid `comic` setting silently falls back to XKCD at
    render time so a bare /update_now renders. Form validation is in the
    settings schema, not here."""
    from plugins.comic import comic as comic_mod
    from plugins.comic.comic import Comic

    captured = {}

    def fake_get_panel(name: Any) -> Any:
        captured["comic"] = name
        return {"image_url": "http://img/latest.png", "title": "", "caption": ""}

    monkeypatch.setattr(comic_mod, "get_panel", fake_get_panel)
    p = Comic(plugin_config)
    monkeypatch.setattr(p, "_compose_image", lambda *a, **kw: object())
    p.generate_image({"comic": "NotARealOne"}, device_config_dev)
    assert captured["comic"] == "XKCD"


def test_generate_image_centering(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> Any:
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

        def raise_for_status(self) -> Any:
            return None

    monkeypatch.setattr("requests.get", lambda url, **kwargs: Resp())

    p = Comic(plugin_config)
    img = p.generate_image(
        {"comic": "XKCD", "titleCaption": "false"}, device_config_dev
    )

    # Ensure white background and image centered (check corners are white)
    w, h = device_config_dev.get_resolution()
    assert img.getpixel((0, 0)) == (255, 255, 255)
    assert img.getpixel((w - 1, 0)) == (255, 255, 255)
    assert img.getpixel((0, h - 1)) == (255, 255, 255)
    assert img.getpixel((w - 1, h - 1)) == (255, 255, 255)


def _compose(
    monkeypatch: pytest.MonkeyPatch,
    plugin_config: Any,
    size: tuple[int, int],
    title: str,
    caption: str,
) -> Any:
    from plugins.comic.comic import Comic

    panel = Image.new("RGB", (740, 360), "black")
    p = Comic(plugin_config)
    monkeypatch.setattr(p.image_loader, "from_url", lambda *a, **kw: panel.copy())
    return p._compose_image(
        {"image_url": "http://img/x.png", "title": title, "caption": caption},
        True,
        "20",
        size[0],
        size[1],
    )


@pytest.mark.parametrize("size", [(250, 122), (122, 250), (800, 480), (1448, 1072)])
def test_compose_image_long_caption_leaves_room_for_the_comic(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, size: tuple[int, int]
) -> None:
    """A long caption on a small panel used to leave no height for the comic,
    and PIL raised "height and width must be > 0"."""
    caption = (
        "Her daughter is named Help I'm trapped in a driver's license factory. " * 4
    )
    img = _compose(monkeypatch, plugin_config, size, "Exploits of a Mom", caption)
    assert img.size == size

    # Title and caption are each capped at a quarter of the panel, so the
    # (black) comic gets at least half the height unless the panel width
    # limits it first.
    gray = img.convert("L")
    dark_rows = [
        y
        for y in range(size[1])
        if sum(1 for x in range(size[0]) if gray.getpixel((x, y)) < 20) > size[0] // 4
    ]
    expected = min(size[1] // 2, size[0] * 360 // 740)
    assert len(dark_rows) >= expected - 2


def test_compose_image_caption_keeps_a_side_margin(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any
) -> None:
    """Caption text used to run flush to the panel edges."""
    size = (800, 480)
    caption = (
        "Her daughter is named Help I'm trapped in a driver's license factory. " * 4
    )
    img = _compose(monkeypatch, plugin_config, size, "", caption)
    # Bottom 60px are caption only; the outermost 8px columns must be blank.
    band = img.convert("L").crop((0, size[1] - 60, size[0], size[1]))
    ink = band.point(lambda v: 255 if v < 128 else 0).getbbox()
    assert ink is not None, "caption was not drawn"
    assert ink[0] >= 8 and ink[2] <= size[0] - 8, ink
