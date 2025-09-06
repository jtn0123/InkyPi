# pyright: reportMissingImports=false
from PIL import Image
from io import BytesIO


def test_image_url_happy(monkeypatch, device_config_dev):
    from plugins.image_url.image_url import ImageURL

    class Resp:
        def __init__(self, content):
            self.content = content
        def raise_for_status(self):
            pass

    def fake_get(url, timeout=None):
        buf = BytesIO()
        Image.new('RGB', (10, 10), 'white').save(buf, format='PNG')
        return Resp(buf.getvalue())

    monkeypatch.setattr('plugins.image_url.image_url.requests.get', fake_get)

    img = ImageURL({"id": "image_url"}).generate_image({"url": "http://img"}, device_config_dev)
    assert img is not None


def test_image_url_missing_url(device_config_dev):
    from plugins.image_url.image_url import ImageURL
    try:
        ImageURL({"id": "image_url"}).generate_image({}, device_config_dev)
        assert False, "Expected error"
    except RuntimeError:
        pass

