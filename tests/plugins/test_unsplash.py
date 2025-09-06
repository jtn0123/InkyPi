# pyright: reportMissingImports=false
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


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


def test_unsplash_random_photo_success(device_config_dev, monkeypatch):
    """Test Unsplash plugin with random photo (no search query)."""
    from plugins.unsplash.unsplash import Unsplash

    # Mock key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        # Mock API response for random photo
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {"urls": {"full": "http://example.com/random.png"}}

        # Mock image download response
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b'fake_image_data'

        mock_requests.side_effect = [mock_api_response, mock_img_response]

        # Mock PIL Image
        with patch('plugins.unsplash.unsplash.Image') as mock_image:
            mock_image.open.return_value.__enter__.return_value.resize.return_value = MagicMock()

            p = Unsplash({"id": "unsplash"})
            result = p.generate_image({}, device_config_dev)

            # Verify random endpoint was called (no search query)
            api_call = mock_requests.call_args_list[0]
            assert 'photos/random' in api_call[0][0]
            assert result is not None


def test_unsplash_with_collections(device_config_dev, monkeypatch):
    """Test Unsplash plugin with collections parameter."""
    from plugins.unsplash.unsplash import Unsplash

    # Mock key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        # Mock API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {"urls": {"full": "http://example.com/photo.png"}}

        # Mock image download response
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b'fake_image_data'

        mock_requests.side_effect = [mock_api_response, mock_img_response]

        # Mock PIL Image
        with patch('plugins.unsplash.unsplash.Image') as mock_image:
            mock_image.open.return_value.__enter__.return_value.resize.return_value = MagicMock()

            p = Unsplash({"id": "unsplash"})
            settings = {'collections': '12345,67890'}
            result = p.generate_image(settings, device_config_dev)

            # Verify collections parameter was passed
            api_call = mock_requests.call_args_list[0]
            assert api_call[1]['params']['collections'] == '12345,67890'
            assert result is not None


def test_unsplash_with_color_filter(device_config_dev, monkeypatch):
    """Test Unsplash plugin with color filter."""
    from plugins.unsplash.unsplash import Unsplash

    # Mock key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        # Mock API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {"urls": {"full": "http://example.com/photo.png"}}

        # Mock image download response
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b'fake_image_data'

        mock_requests.side_effect = [mock_api_response, mock_img_response]

        # Mock PIL Image
        with patch('plugins.unsplash.unsplash.Image') as mock_image:
            mock_image.open.return_value.__enter__.return_value.resize.return_value = MagicMock()

            p = Unsplash({"id": "unsplash"})
            settings = {'color': 'blue'}
            result = p.generate_image(settings, device_config_dev)

            # Verify color parameter was passed
            api_call = mock_requests.call_args_list[0]
            assert api_call[1]['params']['color'] == 'blue'
            assert result is not None


def test_unsplash_with_orientation(device_config_dev, monkeypatch):
    """Test Unsplash plugin with orientation filter."""
    from plugins.unsplash.unsplash import Unsplash

    # Mock key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        # Mock API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {"urls": {"full": "http://example.com/photo.png"}}

        # Mock image download response
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b'fake_image_data'

        mock_requests.side_effect = [mock_api_response, mock_img_response]

        # Mock PIL Image
        with patch('plugins.unsplash.unsplash.Image') as mock_image:
            mock_image.open.return_value.__enter__.return_value.resize.return_value = MagicMock()

            p = Unsplash({"id": "unsplash"})
            settings = {'orientation': 'landscape'}
            result = p.generate_image(settings, device_config_dev)

            # Verify orientation parameter was passed
            api_call = mock_requests.call_args_list[0]
            assert api_call[1]['params']['orientation'] == 'landscape'
            assert result is not None


def test_unsplash_search_no_results(device_config_dev, monkeypatch):
    """Test Unsplash plugin search with no results."""
    from plugins.unsplash.unsplash import Unsplash

    # Mock key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests to return empty results
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}

        mock_requests.return_value = mock_response

        p = Unsplash({"id": "unsplash"})
        settings = {'search_query': 'nonexistent'}

        with pytest.raises(RuntimeError, match="No images found for the given search query"):
            p.generate_image(settings, device_config_dev)


def test_unsplash_api_error_handling(device_config_dev, monkeypatch):
    """Test Unsplash plugin with API error."""
    from plugins.unsplash.unsplash import Unsplash

    # Mock key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests to raise RequestException (which is caught by the plugin)
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        import requests
        mock_requests.side_effect = requests.exceptions.RequestException("API Error")

        p = Unsplash({"id": "unsplash"})

        with pytest.raises(RuntimeError, match="Failed to fetch image from Unsplash API"):
            p.generate_image({}, device_config_dev)


def test_unsplash_api_response_parsing_error(device_config_dev, monkeypatch):
    """Test Unsplash plugin with malformed API response."""
    from plugins.unsplash.unsplash import Unsplash

    # Mock key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests to return malformed response
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}  # Missing required fields

        mock_requests.return_value = mock_response

        p = Unsplash({"id": "unsplash"})

        with pytest.raises(RuntimeError, match="Failed to parse Unsplash API response"):
            p.generate_image({}, device_config_dev)


def test_unsplash_image_download_failure(device_config_dev, monkeypatch):
    """Test Unsplash plugin with image download failure."""
    from plugins.unsplash.unsplash import Unsplash

    # Mock key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        # Mock API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {"urls": {"full": "http://example.com/photo.png"}}

        mock_requests.return_value = mock_api_response

        # Mock grab_image to return None
        with patch('plugins.unsplash.unsplash.grab_image') as mock_grab:
            mock_grab.return_value = None

            p = Unsplash({"id": "unsplash"})

            with pytest.raises(RuntimeError, match="Failed to load image"):
                p.generate_image({}, device_config_dev)


def test_unsplash_vertical_orientation(device_config_dev, monkeypatch):
    """Test Unsplash plugin with vertical device orientation."""
    from plugins.unsplash.unsplash import Unsplash

    # Mock key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock device config for vertical orientation
    monkeypatch.setattr(device_config_dev, 'get_config', lambda key, default=None: {
        'orientation': 'vertical'
    }.get(key, default))

    # Mock resolution
    monkeypatch.setattr(device_config_dev, 'get_resolution', lambda: (800, 480))

    # Mock requests
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        # Mock API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {"urls": {"full": "http://example.com/photo.png"}}

        # Mock image download response
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b'fake_image_data'

        mock_requests.side_effect = [mock_api_response, mock_img_response]

        # Mock grab_image to return a mock image
        with patch('plugins.unsplash.unsplash.grab_image') as mock_grab:
            mock_image = MagicMock()
            mock_grab.return_value = mock_image

            p = Unsplash({"id": "unsplash"})
            result = p.generate_image({}, device_config_dev)

            # Verify grab_image was called with reversed dimensions
            mock_grab.assert_called_with("http://example.com/photo.png", (480, 800), timeout_ms=40000)
            assert result is not None


def test_grab_image_success():
    """Test grab_image function with successful image download."""
    from plugins.unsplash.unsplash import grab_image

    # Mock requests
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'fake_image_data'
        mock_requests.return_value = mock_response

        # Mock PIL Image
        with patch('plugins.unsplash.unsplash.Image') as mock_image:
            mock_img_instance = MagicMock()
            mock_image.open.return_value.__enter__.return_value = mock_img_instance
            mock_img_instance.resize.return_value = MagicMock()

            result = grab_image("http://example.com/image.png", (800, 600))

            assert result is not None
            mock_requests.assert_called_with("http://example.com/image.png", timeout=40.0)
            from PIL.Image import Resampling
            mock_img_instance.resize.assert_called_with((800, 600), Resampling.LANCZOS)


def test_grab_image_download_failure():
    """Test grab_image function with download failure."""
    from plugins.unsplash.unsplash import grab_image

    # Mock requests to raise exception
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        mock_requests.side_effect = Exception("Download failed")

        result = grab_image("http://example.com/image.png", (800, 600))

        assert result is None


def test_grab_image_invalid_image_data():
    """Test grab_image function with invalid image data."""
    from plugins.unsplash.unsplash import grab_image

    # Mock requests
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'invalid_image_data'
        mock_requests.return_value = mock_response

        # Mock PIL Image to raise exception
        with patch('plugins.unsplash.unsplash.Image') as mock_image:
            mock_image.open.side_effect = Exception("Invalid image format")

            result = grab_image("http://example.com/image.png", (800, 600))

            assert result is None


def test_unsplash_content_filter_settings(device_config_dev, monkeypatch):
    """Test Unsplash plugin with different content filter settings."""
    from plugins.unsplash.unsplash import Unsplash

    # Mock key
    monkeypatch.setattr(device_config_dev, 'load_env_key', lambda key: 'test_key')

    # Mock requests
    with patch('plugins.unsplash.unsplash.requests.get') as mock_requests:
        # Mock API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {"urls": {"full": "http://example.com/photo.png"}}

        # Mock image download response
        mock_img_response = MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b'fake_image_data'

        mock_requests.side_effect = [mock_api_response, mock_img_response]

        # Mock PIL Image
        with patch('plugins.unsplash.unsplash.Image') as mock_image:
            mock_image.open.return_value.__enter__.return_value.resize.return_value = MagicMock()

            p = Unsplash({"id": "unsplash"})

            # Test different content filter values
            for content_filter in ['low', 'high']:
                mock_requests.reset_mock()
                mock_requests.side_effect = [mock_api_response, mock_img_response]

                settings = {'content_filter': content_filter}
                result = p.generate_image(settings, device_config_dev)

                # Verify content_filter parameter was passed
                api_call = mock_requests.call_args_list[0]  # Get the API call
                assert api_call[1]['params']['content_filter'] == content_filter
                assert result is not None

