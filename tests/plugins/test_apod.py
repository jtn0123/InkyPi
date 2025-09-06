# pyright: reportMissingImports=false


def test_apod_missing_key(client):
    import os
    if 'NASA_SECRET' in os.environ:
        del os.environ['NASA_SECRET']
    data = {
        'plugin_id': 'apod',
    }
    resp = client.post('/update_now', data=data)
    assert resp.status_code == 500


def test_apod_success(client, monkeypatch):
    import os
    os.environ['NASA_SECRET'] = 'test'

    # Mock NASA APOD API response
    import requests
    def fake_get(url, params=None):
        class R:
            status_code = 200
            def json(self):
                return {"media_type": "image", "hdurl": "http://example.com/apod.png"}
        return R()

    # Mock image fetch
    from PIL import Image
    from io import BytesIO
    def fake_get_image(url):
        img = Image.new('RGB', (64, 64), 'black')
        buf = BytesIO()
        img.save(buf, format='PNG')
        class R:
            content = buf.getvalue()
            status_code = 200
        return R()

    # Route calls: first call with params (APOD), second call to image URL
    calls = []
    def dispatcher(url, params=None):
        if params is not None:
            calls.append('meta')
            return fake_get(url, params=params)
        else:
            calls.append('image')
            return fake_get_image(url)

    monkeypatch.setattr(requests, 'get', dispatcher, raising=True)

    data = {'plugin_id': 'apod'}
    resp = client.post('/update_now', data=data)
    assert resp.status_code == 200
    assert calls == ['meta', 'image']


