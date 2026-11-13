from typing import Any

import pytest
from PIL import Image

from plugins.newspaper.constants import NEWSPAPERS


def _png_image(size: Any = (600, 800), color: Any = "white") -> Any:
    return Image.new("RGB", size, color)


def _front_page(size: Any, top_height: int) -> Any:
    """A page whose top *top_height* rows are red and the rest blue."""
    page = Image.new("RGB", size, "blue")
    page.paste("red", (0, 0, size[0], top_height))
    return page


def test_newspaper_initialization() -> None:
    from plugins.newspaper.newspaper import Newspaper

    plugin = Newspaper({"id": "newspaper"})
    template = plugin.generate_settings_template()

    assert template["newspapers"] == sorted(NEWSPAPERS, key=lambda n: n["name"])


def test_newspaper_success_with_expand_height(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> Any:
    from plugins.newspaper.newspaper import Newspaper

    # A portrait page: only its top 400 / (800/480) = 240 rows fit the
    # panel's shape at full width. Those are red; everything below is blue.
    def fake_get_image(url: Any) -> Any:
        return _front_page((400, 800), top_height=240)

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "wsj"}, device_config_dev
    )
    assert img is not None
    # Exactly the panel size (it used to come back at 400x240 and be rejected
    # by the refresh task's dimension check, pausing the plugin).
    assert img.size == (800, 480)
    # The top of the page, at full width: no blue from further down.
    assert img.getpixel((400, 470)) == (255, 0, 0)
    assert img.getpixel((5, 5)) == (255, 0, 0)


def test_newspaper_real_freedom_forum_shape_returns_panel_size(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    """A 700-wide front page used to come back as 700x420 for an 800x480 panel."""
    from plugins.newspaper.newspaper import Newspaper

    monkeypatch.setattr(
        "plugins.newspaper.newspaper.get_image",
        lambda url: _png_image((700, 1287)),
    )

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "ny_nyt"}, device_config_dev
    )
    assert img.size == device_config_dev.get_resolution() == (800, 480)


def test_newspaper_tries_multiple_days_then_fails(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> None:
    from plugins.newspaper.newspaper import Newspaper

    # Always return None from get_image to simulate missing newspapers
    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", lambda url: None)

    try:
        Newspaper({"id": "newspaper"}).generate_image(
            {"newspaperSlug": "WSJ"}, device_config_dev
        )
        assert False, "Expected failure when no front cover found"
    except RuntimeError:
        pass


def test_newspaper_slug_case_variants(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> Any:
    from plugins.newspaper.newspaper import Newspaper

    # Succeeds only for uppercase slug to ensure we try variants
    def fake_get_image(url: Any) -> Any:
        if url.endswith("/WSJ.jpg"):
            return _png_image((300, 600))
        return None

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "wsj"}, device_config_dev
    )
    assert img is not None


def test_newspaper_missing_slug_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> Any:
    """JTN-784: missing/empty slug falls back to NY_NYT at render time so a
    bare /update_now produces a visible render."""
    from plugins.newspaper import newspaper as np_mod
    from plugins.newspaper.newspaper import Newspaper

    captured: dict = {}

    def fake_get_image(url: Any) -> Any:
        captured["url"] = url
        return _png_image((400, 800))

    monkeypatch.setattr(np_mod, "get_image", fake_get_image)

    plugin = Newspaper({"id": "newspaper"})
    for empty in ({"newspaperSlug": ""}, {"newspaperSlug": None}, {}):
        plugin.generate_image(empty, device_config_dev)
        assert "NY_NYT" in captured["url"]


def test_newspaper_invalid_slug_raises(device_config_dev: Any) -> None:
    from plugins.newspaper.newspaper import Newspaper

    with pytest.raises(RuntimeError, match="Invalid newspaper selection"):
        Newspaper({"id": "newspaper"}).generate_image(
            {"newspaperSlug": "<script>alert(1)</script>"},
            device_config_dev,
        )


def test_newspaper_image_wider_than_display(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> Any:
    """A page wider than the panel is shown whole, padded with white below."""
    from plugins.newspaper.newspaper import Newspaper

    # device_config_dev is horizontal, so dimensions stay (800, 480)
    # desired_ratio = 800/480 = 1.667
    # For no expansion, img_ratio must be >= desired_ratio
    # Use 1000x500 image: img_ratio = 2.0 > 1.667, so no expansion
    def fake_get_image(url: Any) -> Any:
        return _png_image((1000, 500), "red")

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "WSJ"}, device_config_dev
    )
    assert img is not None
    # 1000x500 scales to 800x400; the remaining 80 rows are white padding at
    # the bottom so the masthead stays at the top of the panel.
    assert img.size == (800, 480)
    assert img.getpixel((400, 0)) == (255, 0, 0)
    assert img.getpixel((400, 395)) == (255, 0, 0)
    assert img.getpixel((400, 479)) == (255, 255, 255)


def test_newspaper_vertical_orientation(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> Any:
    """Vertical orientation swaps dimensions."""
    from plugins.newspaper.newspaper import Newspaper

    # Set orientation to vertical
    device_config_dev.update_value("orientation", "vertical")

    # img_ratio = 400/800 = 0.5 < desired_ratio = 480/800 = 0.6, so the top
    # 400 / 0.6 = 667 rows are kept at full width.
    def fake_get_image(url: Any) -> Any:
        return _front_page((400, 800), top_height=667)

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "wsj"}, device_config_dev
    )
    assert img is not None
    # In vertical mode the panel canvas is portrait (480, 800).
    assert img.size == (480, 800)
    assert img.getpixel((240, 790)) == (255, 0, 0)


def test_newspaper_finds_on_second_day(
    monkeypatch: pytest.MonkeyPatch, device_config_dev: Any
) -> Any:
    """Newspaper found on second day in retry sequence."""

    from plugins.newspaper.newspaper import Newspaper

    call_count = [0]

    def fake_get_image(url: Any) -> Any:
        call_count[0] += 1
        # Fail on first call (tomorrow), succeed on second call (today)
        if call_count[0] == 1:
            return None
        return _png_image((300, 600))

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "WSJ"}, device_config_dev
    )
    assert img is not None
    assert call_count[0] == 2  # First call failed, second succeeded
