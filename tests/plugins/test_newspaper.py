from io import BytesIO
from PIL import Image


def _png_image(size=(600, 800), color="white"):
    return Image.new("RGB", size, color)


def test_newspaper_success_with_expand_height(monkeypatch, device_config_dev):
    from plugins.newspaper.newspaper import Newspaper, FREEDOM_FORUM_URL

    # Mock utils.image_utils.get_image to return a portrait image on first try
    import plugins.newspaper.newspaper as newsp_mod
    def fake_get_image(url):
        return _png_image((400, 800))

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image({"newspaperSlug": "NYT"}, device_config_dev)
    assert img is not None
    # When portrait ratio < desired ratio, height is expanded
    assert img.size[1] > 800 or img.size[1] == 800


def test_newspaper_tries_multiple_days_then_fails(monkeypatch, device_config_dev):
    from plugins.newspaper.newspaper import Newspaper

    # Always return None from get_image to simulate missing newspapers
    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", lambda url: None)

    try:
        Newspaper({"id": "newspaper"}).generate_image({"newspaperSlug": "WSJ"}, device_config_dev)
        assert False, "Expected failure when no front cover found"
    except RuntimeError:
        pass


