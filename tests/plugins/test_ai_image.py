# pyright: reportMissingImports=false


def test_ai_image_invalid_model(client):
    import os
    os.environ['OPEN_AI_SECRET'] = 'test'
    data = {
        'plugin_id': 'ai_image',
        'textPrompt': 'a cat',
        'imageModel': 'invalid-model',
        'quality': 'standard',
    }
    resp = client.post('/update_now', data=data)
    assert resp.status_code == 500


def test_ai_image_generate_image_success(client, monkeypatch):
    import os
    os.environ['OPEN_AI_SECRET'] = 'test'

    class FakeImages:
        def generate(self, **kwargs):
            # Ensure quality is normalized per model
            model = kwargs.get('model')
            q = kwargs.get('quality')
            if model == 'gpt-image-1':
                assert q in (None, 'standard', 'high')
            if model == 'dall-e-3':
                assert q in (None, 'standard', 'hd')
            class Resp:
                class D:
                    url = 'http://example.com/img.png'
                data = [D()]
            return Resp()

    class FakeOpenAI:
        def __init__(self, api_key=None):
            self.images = FakeImages()

    import plugins.ai_image.ai_image as ai_image_mod
    monkeypatch.setattr(ai_image_mod, 'OpenAI', FakeOpenAI, raising=True)

    # Mock requests.get to image URL
    import requests
    from PIL import Image
    from io import BytesIO
    def fake_get(url):
        img = Image.new('RGB', (64, 64), 'black')
        buf = BytesIO()
        img.save(buf, format='PNG')
        class R:
            content = buf.getvalue()
            status_code = 200
        return R()
    monkeypatch.setattr(requests, 'get', fake_get, raising=True)

    for model, quality in [('dall-e-3','standard'), ('dall-e-3','hd'), ('gpt-image-1','high'), ('gpt-image-1','standard'), ('gpt-image-1','low')]:
        # 'low' should normalize to 'standard' for gpt-image-1
        data = {
            'plugin_id': 'ai_image',
            'textPrompt': 'a cat',
            'imageModel': model,
            'quality': quality,
        }
        resp = client.post('/update_now', data=data)
        assert resp.status_code == 200


