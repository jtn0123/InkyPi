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
    # Expected height based on plugin formula: new_height = int((img_width * desired_width) / desired_height)
    expected_height = int(
        (400 * device_config_dev.get_resolution()[0])
        / device_config_dev.get_resolution()[1]
    )
    assert img.size == (400, expected_height)


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


def test_newspaper_fallbacks_try_sizes_and_month_padding(monkeypatch, device_config_dev):
    from plugins.newspaper.newspaper import Newspaper
    from datetime import datetime

    # Track attempted URLs to ensure fallbacks are exercised in order
    attempted_urls = []

    # First few URLs (jpgM/lg) should fail; then zero-padded month with md should succeed
    def fake_get_image(url):
        attempted_urls.append(url)
        mm = datetime.today().month
        zero_padded_month_dir = f"/jpg{mm:02d}/"
        if zero_padded_month_dir in url and "/md/" in url and url.endswith("/ny_nyt.jpg"):
            return _png_image((500, 1000))
        return None

    monkeypatch.setattr("plugins.newspaper.newspaper.get_image", fake_get_image)

    img = Newspaper({"id": "newspaper"}).generate_image(
        {"newspaperSlug": "ny_nyt"}, device_config_dev
    )
    assert img is not None
    # Ensure we tried at least the initial lg candidate and later md with zero-padded month
    assert any("/lg/" in u for u in attempted_urls)
    assert any("/md/" in u for u in attempted_urls)
    mm = datetime.today().month
    assert any(f"/jpg{mm:02d}/" in u for u in attempted_urls)


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
