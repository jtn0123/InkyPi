# pyright: reportMissingImports=false
from PIL import Image
from io import BytesIO


def test_unsplash_search_success(monkeypatch, device_config_dev):
    from plugins.unsplash.unsplash import Unsplash

    # Mock key
    monkeypatch.setenv('UNSPLASH_ACCESS_KEY', 'k')

    class RespApi:
        def __init__(self, data):
            self._data = data
        def raise_for_status(self):
            pass
        def json(self):
            return self._data

    class RespImg:
        def __init__(self):
            buf = BytesIO()
            Image.new('RGB', (5, 5), 'white').save(buf, format='PNG')
            self.content = buf.getvalue()
        def raise_for_status(self):
            pass

    def fake_get(url, params=None, **kwargs):
        if 'search' in url:
            return RespApi({"results": [{"urls": {"full": "http://img"}}]})
        if 'http://img' in url:
            return RespImg()
        return RespApi({"urls": {"full": "http://img"}})

    monkeypatch.setattr('plugins.unsplash.unsplash.requests.get', fake_get)

    img = Unsplash({"id": "unsplash"}).generate_image({"search_query": "cat"}, device_config_dev)
    assert img is not None


def test_unsplash_requires_key(monkeypatch, device_config_dev):
    from plugins.unsplash.unsplash import Unsplash
    monkeypatch.delenv('UNSPLASH_ACCESS_KEY', raising=False)
    try:
        Unsplash({"id": "unsplash"}).generate_image({}, device_config_dev)
        assert False, "Expected error"
    except RuntimeError:
        pass

