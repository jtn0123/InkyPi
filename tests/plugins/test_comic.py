# pyright: reportMissingImports=false
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import pytest
from PIL import Image

# Comic URLs pass the SSRF guard, which resolves the host; keep that offline.
pytestmark = pytest.mark.usefixtures("public_dns")


@pytest.fixture()
def plugin_config() -> Any:
    return {"id": "comic", "class": "Comic", "name": "Comic"}


def _serve_image(monkeypatch: pytest.MonkeyPatch, png: bytes) -> None:
    """Answer the comic image download offline.

    The loader fetches through ``utils.image_loader.get_http_session`` once
    the SSRF check passes, so patching ``requests.get`` never sees the call.
    """
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.content = png
    resp.iter_content = MagicMock(return_value=[png])
    session = MagicMock()
    session.get.return_value = resp
    monkeypatch.setattr("utils.image_loader.get_http_session", lambda: session)


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

    # comic.py imports get_panel by name, so it must be patched there.
    monkeypatch.setattr(
        "plugins.comic.comic.get_panel",
        lambda c: {
            "image_url": "http://img/latest.png",
            "title": "Test",
            "caption": "Test caption",
        },
    )

    _serve_image(monkeypatch, _png_bytes((400, 300)))

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
        "plugins.comic.comic.get_panel",
        lambda c: {
            "image_url": "http://img/latest.png",
            "title": "Test",
            "caption": "Test caption",
        },
    )

    _serve_image(monkeypatch, _png_bytes((400, 300)))

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


def test_generate_image_refuses_a_download_that_is_not_an_image(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> None:
    """The loader turns undecodable bytes into None; the plugin then fails
    with a message the dashboard can show, not a blank frame."""
    from plugins.comic.comic import Comic

    monkeypatch.setattr(
        "plugins.comic.comic.get_panel",
        lambda c: {"image_url": "http://img/broken.png", "title": "X", "caption": ""},
    )
    _serve_image(monkeypatch, b"<html>not a picture</html>")

    with pytest.raises(RuntimeError, match="^Failed to load comic image$"):
        Comic(plugin_config).generate_image({"comic": "XKCD"}, device_config_dev)


def test_generate_image_asks_for_the_panel_at_full_size_and_keeps_loader_errors(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> None:
    """The panel is fetched unresized at the frame size; a loader error is
    not swallowed or rewrapped."""
    from plugins.comic.comic import Comic

    monkeypatch.setattr(
        "plugins.comic.comic.get_panel",
        lambda c: {"image_url": "http://img/bad.png", "title": "", "caption": ""},
    )
    p = Comic(plugin_config)
    loader = MagicMock()
    loader.from_url.side_effect = OSError("decode error")
    p.image_loader = loader

    with pytest.raises(OSError, match="^decode error$"):
        p.generate_image({"comic": "XKCD"}, device_config_dev)
    loader.from_url.assert_called_once_with(
        "http://img/bad.png",
        dimensions=tuple(device_config_dev.get_resolution()),
        resize=False,
    )


def test_generate_image_centering(
    monkeypatch: pytest.MonkeyPatch, plugin_config: Any, device_config_dev: Any
) -> Any:
    from plugins.comic.comic import Comic

    monkeypatch.setattr(
        "plugins.comic.comic.get_panel",
        lambda c: {"image_url": "http://img/latest.png", "title": "", "caption": ""},
    )

    # create a tall/narrow source so centering is apparent
    src_w, src_h = 100, 300

    _serve_image(monkeypatch, _png_bytes((src_w, src_h), color="black"))

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
