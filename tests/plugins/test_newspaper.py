import pytest
from PIL import Image
from plugins.newspaper.constants import NEWSPAPERS

def _png_image(size=(600, 800), color="white"):
    return Image.new("RGB", size, color)

def test_newspaper_initialization():
    from plugins.newspaper.newspaper import Newspaper

    plugin = Newspaper({"id": "newspaper"})
    template = plugin.generate_settings_template()

    assert template["newspapers"] == sorted(NEWSPAPERS, key=lambda n: n["name"])

def test_newspaper_success_with_expand_height(monkeypatch, device_config_dev):
    from plugins.newspaper.newspaper import Newspaper

    # Mock utils.image_utils.get_image to return a portrait image on first try
    def fake_get_image(url):
        return _png_image((400, 800))

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "NYT"}, device_config_dev
    )
    assert img is not None
    # device_config_dev has horizontal orientation, so dimensions are swapped (480, 800)
    # new_height = int((img_width * desired_width) / desired_height) = int((400 * 480) / 800) = 240
    assert img.size == (400, 240)

def test_newspaper_tries_multiple_days_then_fails(monkeypatch, device_config_dev):
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

def test_newspaper_slug_case_variants(monkeypatch, device_config_dev):
    from plugins.newspaper.newspaper import Newspaper

    # Succeeds only for uppercase slug to ensure we try variants
    def fake_get_image(url):
        if url.endswith("/WSJ.jpg"):
            return _png_image((300, 600))
        return None

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "wsj"}, device_config_dev
    )
    assert img is not None


def test_newspaper_missing_slug_raises(device_config_dev):
    """Empty or missing slug raises RuntimeError."""
    from plugins.newspaper.newspaper import Newspaper

    plugin = Newspaper({"id": "newspaper"})

    # Empty string slug
    with pytest.raises(RuntimeError, match="Newspaper input not provided"):
        plugin.generate_image({"newspaperSlug": ""}, device_config_dev)

    # None slug
    with pytest.raises(RuntimeError, match="Newspaper input not provided"):
        plugin.generate_image({"newspaperSlug": None}, device_config_dev)

    # Missing slug key
    with pytest.raises(RuntimeError, match="Newspaper input not provided"):
        plugin.generate_image({}, device_config_dev)


def test_newspaper_image_wider_than_display(monkeypatch, device_config_dev):
    """Image wider than display ratio is returned without height expansion."""
    from plugins.newspaper.newspaper import Newspaper

    # Create a very wide image (landscape)
    # device_config_dev is horizontal, so desired dimensions are (480, 800)
    # desired_ratio = 480/800 = 0.6
    # For no expansion, img_ratio must be >= desired_ratio
    # Use 800x800 image: img_ratio = 1.0 > 0.6, so no expansion
    def fake_get_image(url):
        return _png_image((800, 800))

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "NYT"}, device_config_dev
    )
    assert img is not None
    # Image should be unchanged since img_ratio >= desired_ratio
    assert img.size == (800, 800)


def test_newspaper_vertical_orientation(monkeypatch, device_config_dev):
    """Vertical orientation uses dimensions as-is (not swapped)."""
    from plugins.newspaper.newspaper import Newspaper

    # Set orientation to vertical
    device_config_dev.update_value("orientation", "vertical")

    def fake_get_image(url):
        return _png_image((400, 800))

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "NYT"}, device_config_dev
    )
    assert img is not None
    # In vertical mode, dimensions are (800, 480) - not swapped
    # img_ratio = 400/800 = 0.5, desired_ratio = 800/480 = 1.67
    # Since img_ratio < desired_ratio, height is expanded
    # new_height = int((400 * 800) / 480) = 666
    assert img.size == (400, 666)


def test_newspaper_finds_on_second_day(monkeypatch, device_config_dev):
    """Newspaper found on second day in retry sequence."""
    from plugins.newspaper.newspaper import Newspaper
    from datetime import datetime

    call_count = [0]

    def fake_get_image(url):
        call_count[0] += 1
        # Fail on first call (tomorrow), succeed on second call (today)
        if call_count[0] == 1:
            return None
        return _png_image((300, 600))

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "NYT"}, device_config_dev
    )
    assert img is not None
    assert call_count[0] == 2  # First call failed, second succeeded
