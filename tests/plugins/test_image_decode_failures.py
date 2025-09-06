from unittest.mock import patch

import pytest


def test_apod_decode_failure(device_config_dev, monkeypatch):
    from plugins.apod.apod import Apod

    p = Apod({"id": "apod"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "fake")

    # Mock APOD API JSON response
    class R:
        status_code = 200

        def json(self):
            return {"media_type": "image", "url": "https://example.com/x.png"}

    # Mock image response with invalid bytes
    class R2:
        status_code = 200
        content = b"not-an-image"

    # Track call count to return different responses
    call_count = [0]
    def mock_http_get(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return R()  # First call returns JSON
        else:
            return R2()  # Second call returns invalid image

    monkeypatch.setattr("plugins.apod.apod.http_get", mock_http_get)

    with pytest.raises(RuntimeError):
        p.generate_image({}, device_config_dev)


def test_unsplash_decode_failure(device_config_dev, monkeypatch):
    from plugins.unsplash.unsplash import Unsplash, grab_image

    u = Unsplash({"id": "unsplash"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "fake")

    # Mock Unsplash API JSON
    class R:
        status_code = 200

        def json(self):
            return {"urls": {"full": "https://example.com/x.jpg"}}

    monkeypatch.setattr("plugins.unsplash.unsplash.http_get", lambda *a, **k: R(), raising=True)

    # Make grab_image return None (decode failure path)
    monkeypatch.setattr("plugins.unsplash.unsplash.grab_image", lambda *a, **k: None, raising=True)

    with pytest.raises(RuntimeError):
        u.generate_image({}, device_config_dev)


def test_image_url_decode_failure(device_config_dev, monkeypatch):
    from plugins.image_url.image_url import ImageURL

    p = ImageURL({"id": "image_url"})

    # Make grab_image return None (decode failure path)
    monkeypatch.setattr("plugins.image_url.image_url.grab_image", lambda *a, **k: None, raising=True)

    with pytest.raises(RuntimeError):
        p.generate_image({"url": "https://example.com/x.png"}, device_config_dev)


