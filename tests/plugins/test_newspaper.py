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
