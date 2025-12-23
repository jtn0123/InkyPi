# pyright: reportMissingImports=false
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


def test_apod_success(monkeypatch, device_config_dev):
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setenv('NASA_SECRET', 'k')

    class RespApi:
        status_code = 200
        def json(self):
            return {"media_type": "image", "url": "http://img"}

    class RespImg:
        status_code = 200
        def __init__(self):
            buf = BytesIO()
            Image.new('RGB', (5, 5), 'white').save(buf, format='PNG')
            self.content = buf.getvalue()

    calls = {"url": None}

    def fake_get(url, params=None, **kwargs):
        calls["url"] = url
        if 'apod' in url:
            return RespApi()
        return RespImg()

    monkeypatch.setattr('requests.get', fake_get)

    img = Apod({"id": "apod"}).generate_image({}, device_config_dev)
    assert img.size[0] > 0


def test_apod_requires_key(monkeypatch, device_config_dev):
    from plugins.apod.apod import Apod
    monkeypatch.delenv('NASA_SECRET', raising=False)
    try:
        Apod({"id": "apod"}).generate_image({}, device_config_dev)
        assert False, "Expected missing key error"
    except RuntimeError:
        pass
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


@patch('requests.get')
def test_apod_success_via_client(mock_http_get, client, monkeypatch):
    import os
    os.environ['NASA_SECRET'] = 'test'

    # Mock NASA APOD API response and image download
    call_count = [0]
    def fake_get(url, params=None, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:  # First call is to NASA API
            class ApiResponse:
                status_code = 200
                def json(self):
                    return {"media_type": "image", "hdurl": "http://example.com/apod.png"}
            return ApiResponse()
        else:  # Second call is to download the image
            from io import BytesIO
            from PIL import Image
            img = Image.new('RGB', (64, 64), 'black')
            buf = BytesIO()
            img.save(buf, format='PNG')
            class ImageResponse:
                content = buf.getvalue()
                status_code = 200
            return ImageResponse()

    mock_http_get.side_effect = fake_get

    data = {'plugin_id': 'apod'}
    resp = client.post('/update_now', data=data)
    assert resp.status_code == 200


def test_apod_randomize_date(monkeypatch, device_config_dev):
    """Test APOD plugin with random date generation."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setenv('NASA_SECRET', 'test_key')

    # Mock requests
    with patch('requests.get') as mock_requests:
        # Mock NASA API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/apod.png"
        }

        # Mock image download response
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b'fake_image_data'

        # Configure mock to return different responses
        mock_requests.side_effect = [mock_api_response, mock_img_response]

        # Mock PIL Image
        with patch('plugins.apod.apod.Image') as mock_image:
            mock_image.open.return_value.__enter__.return_value.copy.return_value = MagicMock()

            p = Apod({"id": "apod"})
            settings = {'randomizeApod': 'true'}

            result = p.generate_image(settings, device_config_dev)

            # Verify API was called with random date parameter
            assert mock_requests.call_count >= 2
            api_call = mock_requests.call_args_list[0]
            assert 'api.nasa.gov' in api_call[0][0]
            assert 'date' in api_call[1]['params']
            assert result is not None


def test_apod_custom_date(monkeypatch, device_config_dev):
    """Test APOD plugin with custom date."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setenv('NASA_SECRET', 'test_key')

    # Mock requests
    with patch('requests.get') as mock_requests:
        # Mock NASA API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/apod.png"
        }

        # Mock image download response
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b'fake_image_data'

        mock_requests.side_effect = [mock_api_response, mock_img_response]

        # Mock PIL Image
        with patch('plugins.apod.apod.Image') as mock_image:
            mock_image.open.return_value.__enter__.return_value.copy.return_value = MagicMock()

            p = Apod({"id": "apod"})
            custom_date = "2023-12-25"
            settings = {'customDate': custom_date}

            result = p.generate_image(settings, device_config_dev)

            # Verify API was called with custom date
            api_call = mock_requests.call_args_list[0]
            assert api_call[1]['params']['date'] == custom_date
            assert result is not None


def test_apod_api_error_response(device_config_dev, monkeypatch):
    """Test APOD plugin with NASA API error response."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests to return error status
    with patch('requests.get') as mock_requests:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_requests.return_value = mock_response

        p = Apod({"id": "apod"})

        with pytest.raises(RuntimeError, match="Failed to retrieve NASA APOD"):
            p.generate_image({}, device_config_dev)


def test_apod_video_with_thumbnail_fallback(device_config_dev, monkeypatch):
    """Video days should fall back to NASA-provided thumbnail when available."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    with patch('requests.get') as mock_requests:
        # First call: NASA APOD API returns video with thumbnail
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "video",
            "url": "http://example.com/video.mp4",
            "thumbnail_url": "http://example.com/thumb.png",
        }

        # Second call: image bytes for thumbnail
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        from io import BytesIO
        from PIL import Image
        buf = BytesIO()
        Image.new('RGB', (10, 10), 'white').save(buf, format='PNG')
        mock_img_response.content = buf.getvalue()

        mock_requests.side_effect = [mock_api_response, mock_img_response]

        p = Apod({"id": "apod"})
        img = p.generate_image({}, device_config_dev)
        assert img is not None
        assert img.size[0] > 0


def test_apod_sends_thumbs_param(monkeypatch, device_config_dev):
    """Ensure we request APOD with thumbs=True so thumbnail_url is provided on video days."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setenv('NASA_SECRET', 'k')

    calls = {
        'first_params': None,
    }

    class RespApi:
        status_code = 200
        def json(self):
            return {"media_type": "image", "url": "http://img"}

    class RespImg:
        status_code = 200
        def __init__(self):
            from io import BytesIO
            from PIL import Image
            buf = BytesIO()
            Image.new('RGB', (5, 5), 'white').save(buf, format='PNG')
            self.content = buf.getvalue()

    def fake_get(url, params=None, **kwargs):
        # Capture first call params (NASA API call)
        if 'api.nasa.gov/planetary/apod' in url:
            calls['first_params'] = params
            return RespApi()
        return RespImg()

    monkeypatch.setattr('requests.get', fake_get)

    img = Apod({"id": "apod"}).generate_image({}, device_config_dev)
    assert img is not None
    assert calls['first_params'] is not None
    # thumbs should be truthy (True)
    assert calls['first_params'].get('thumbs') in (True, 'true', 'True')


def test_apod_hdurl_preference(device_config_dev, monkeypatch):
    """Test APOD plugin prefers HD URL over regular URL."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests
    with patch('requests.get') as mock_requests:
        # Mock NASA API response with both URLs
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/low_res.png",
            "hdurl": "http://example.com/high_res.png"
        }

        # Mock image download response
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b'fake_hd_image_data'

        mock_requests.side_effect = [mock_api_response, mock_img_response]

        # Mock PIL Image
        with patch('plugins.apod.apod.Image') as mock_image:
            mock_image.open.return_value.__enter__.return_value.copy.return_value = MagicMock()

            p = Apod({"id": "apod"})
            result = p.generate_image({}, device_config_dev)

            # Verify HD URL was requested
            image_call = mock_requests.call_args_list[1]
            assert image_call[0][0] == "http://example.com/high_res.png"
            assert result is not None


def test_apod_image_download_failure(device_config_dev, monkeypatch):
    """Test APOD plugin with image download failure."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests
    with patch('requests.get') as mock_requests:
        # Mock NASA API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/apod.png"
        }

        # Mock image download failure
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b'invalid_image_data'

        mock_requests.side_effect = [mock_api_response, mock_img_response]

        # Mock PIL Image to raise exception
        with patch('plugins.apod.apod.Image') as mock_image:
            mock_image.open.side_effect = Exception("Invalid image format")

            p = Apod({"id": "apod"})

            with pytest.raises(RuntimeError, match="Failed to load APOD image"):
                p.generate_image({}, device_config_dev)


def test_apod_settings_template():
    """Test APOD plugin settings template generation."""
    from plugins.apod.apod import Apod

    p = Apod({"id": "apod"})
    template = p.generate_settings_template()

    assert "api_key" in template
    assert template["api_key"]["service"] == "NASA"
    assert template["api_key"]["expected_key"] == "NASA_SECRET"
    assert template["api_key"]["required"] is True
    assert template["style_settings"] is False




def test_apod_image_download_timeout(device_config_dev, monkeypatch):
    """Test APOD plugin with image download timeout."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests
    with patch('requests.get') as mock_requests:
        # Mock NASA API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/apod.png"
        }

        mock_requests.side_effect = [mock_api_response, Exception("Image download timeout")]

        p = Apod({"id": "apod"})

        with pytest.raises(RuntimeError, match="Failed to load APOD image"):
            p.generate_image({}, device_config_dev)


def test_apod_missing_hdurl_fallback(device_config_dev, monkeypatch):
    """Test APOD plugin falls back to regular URL when HD URL is missing."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests
    with patch('requests.get') as mock_requests:
        # Mock NASA API response with only regular URL
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/low_res.png"
            # No hdurl field
        }

        # Mock image download response
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b'fake_image_data'

        mock_requests.side_effect = [mock_api_response, mock_img_response]

        # Mock PIL Image
        with patch('plugins.apod.apod.Image') as mock_image:
            mock_image.open.return_value.__enter__.return_value.copy.return_value = MagicMock()

            p = Apod({"id": "apod"})
            result = p.generate_image({}, device_config_dev)

            # Verify regular URL was requested
            image_call = mock_requests.call_args_list[1]
            assert image_call[0][0] == "http://example.com/low_res.png"
            assert result is not None


