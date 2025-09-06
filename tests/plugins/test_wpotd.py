from io import BytesIO
import pytest
from PIL import Image
from unittest.mock import patch, MagicMock


def _png_bytes(size=(10, 6), color="white"):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_wpotd_happy_path(monkeypatch, device_config_dev):
    from plugins.wpotd.wpotd import Wpotd

    def fake_session_get(self, url, params=None, headers=None, timeout=None):
        class R:
            status_code = 200
            def raise_for_status(self):
                return None
            def json(self_inner):
                if params and params.get("prop") == "images":
                    return {"query": {"pages": [{"images": [{"title": "File:Example.png"}]}]}}
                if params and params.get("prop") == "imageinfo":
                    return {"query": {"pages": {"1": {"imageinfo": [{"url": "http://example.com/img.png"}]}}}}
                return {}

        return R()

    # Patch requests.Session.get so Wpotd.SESSION.get uses our fake
    import requests
    monkeypatch.setattr(requests.Session, "get", fake_session_get, raising=True)

    # Patch download step to avoid PIL open complexities
    import plugins.wpotd.wpotd as wpotd_mod
    monkeypatch.setattr(wpotd_mod.Wpotd, "_download_image", lambda self, u: Image.open(BytesIO(_png_bytes())).copy())

    img = Wpotd({"id": "wpotd"}).generate_image({"shrinkToFitWpotd": "false"}, device_config_dev)
    assert img is not None
    assert img.size[0] > 0


def test_wpotd_bad_status_raises(monkeypatch, device_config_dev):
    from plugins.wpotd.wpotd import Wpotd

    class BadResp:
        status_code = 500
        def raise_for_status(self):
            raise RuntimeError("boom")
        def json(self):
            return {}

    def fake_session_get(self, url, params=None, headers=None, timeout=None):
        return BadResp()

    import requests
    monkeypatch.setattr(requests.Session, "get", fake_session_get, raising=True)

    try:
        Wpotd({"id": "wpotd"}).generate_image({}, device_config_dev)
        assert False, "Expected Wikipedia API request failure"
    except RuntimeError:
        pass


def test_wpotd_missing_fields_raises(monkeypatch, device_config_dev):
    from plugins.wpotd.wpotd import Wpotd

    def fake_session_get(self, url, params=None, headers=None, timeout=None):
        class R:
            status_code = 200
            def raise_for_status(self):
                return None
            def json(self_inner):
                # Missing images array content
                return {"query": {"pages": [{"images": []}]}}
        return R()

    import requests
    monkeypatch.setattr(requests.Session, "get", fake_session_get, raising=True)

    try:
        Wpotd({"id": "wpotd"}).generate_image({}, device_config_dev)
        assert False, "Expected failure to retrieve POTD filename"
    except RuntimeError:
        pass


def test_wpotd_randomize_date(monkeypatch, device_config_dev):
    """Test WPOTD plugin with random date generation."""
    from plugins.wpotd.wpotd import Wpotd

    # Mock the date determination to return a specific date
    with patch.object(Wpotd, '_determine_date') as mock_determine_date, \
         patch.object(Wpotd, '_fetch_potd') as mock_fetch_potd, \
         patch.object(Wpotd, '_download_image') as mock_download:

        mock_determine_date.return_value = MagicMock()  # Mock date object
        mock_fetch_potd.return_value = {"image_src": "http://example.com/image.png"}
        mock_download.return_value = Image.new("RGB", (100, 100), "white")

        p = Wpotd({"id": "wpotd"})
        settings = {'randomizeWpotd': 'true'}

        result = p.generate_image(settings, device_config_dev)

        # Verify _determine_date was called with correct settings
        mock_determine_date.assert_called_once_with(settings)
        assert result is not None


def test_wpotd_custom_date(monkeypatch, device_config_dev):
    """Test WPOTD plugin with custom date."""
    from plugins.wpotd.wpotd import Wpotd

    # Mock the date determination
    with patch.object(Wpotd, '_determine_date') as mock_determine_date, \
         patch.object(Wpotd, '_fetch_potd') as mock_fetch_potd, \
         patch.object(Wpotd, '_download_image') as mock_download:

        mock_determine_date.return_value = MagicMock()
        mock_fetch_potd.return_value = {"image_src": "http://example.com/image.png"}
        mock_download.return_value = Image.new("RGB", (100, 100), "white")

        p = Wpotd({"id": "wpotd"})
        custom_date = "2023-12-25"
        settings = {'customDate': custom_date}

        result = p.generate_image(settings, device_config_dev)

        # Verify _determine_date was called with custom date settings
        mock_determine_date.assert_called_once_with(settings)
        assert result is not None


def test_wpotd_svg_format_detection(device_config_dev, monkeypatch):
    """Test WPOTD plugin SVG format handling."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})

    # Test SVG URL detection - the SVG exception gets caught by general handler
    with pytest.raises(RuntimeError, match="Failed to load WPOTD image"):
        p._download_image("http://example.com/image.svg")


def test_wpotd_shrink_to_fit_enabled(device_config_dev, monkeypatch):
    """Test WPOTD plugin with shrink to fit enabled."""
    from plugins.wpotd.wpotd import Wpotd

    # Mock device resolution
    monkeypatch.setattr(device_config_dev, 'get_resolution', lambda: (800, 480))

    # Mock the plugin methods
    with patch.object(Wpotd, '_determine_date') as mock_determine_date, \
         patch.object(Wpotd, '_fetch_potd') as mock_fetch_potd, \
         patch.object(Wpotd, '_download_image') as mock_download, \
         patch.object(Wpotd, '_shrink_to_fit') as mock_shrink:

        mock_determine_date.return_value = MagicMock()
        mock_fetch_potd.return_value = {"image_src": "http://example.com/image.png"}
        mock_download.return_value = Image.new("RGB", (1000, 600), "white")  # Large image
        mock_shrink.return_value = Image.new("RGB", (800, 480), "white")  # Resized image

        p = Wpotd({"id": "wpotd"})
        settings = {'shrinkToFitWpotd': 'true'}

        result = p.generate_image(settings, device_config_dev)

        # Verify shrink_to_fit was called
        mock_shrink.assert_called_once()
        assert result is not None


def test_wpotd_shrink_to_fit_disabled(device_config_dev, monkeypatch):
    """Test WPOTD plugin with shrink to fit disabled."""
    from plugins.wpotd.wpotd import Wpotd

    # Mock the plugin methods
    with patch.object(Wpotd, '_determine_date') as mock_determine_date, \
         patch.object(Wpotd, '_fetch_potd') as mock_fetch_potd, \
         patch.object(Wpotd, '_download_image') as mock_download, \
         patch.object(Wpotd, '_shrink_to_fit') as mock_shrink:

        mock_determine_date.return_value = MagicMock()
        mock_fetch_potd.return_value = {"image_src": "http://example.com/image.png"}
        original_image = Image.new("RGB", (1000, 600), "white")
        mock_download.return_value = original_image

        p = Wpotd({"id": "wpotd"})
        settings = {'shrinkToFitWpotd': 'false'}

        result = p.generate_image(settings, device_config_dev)

        # Verify shrink_to_fit was NOT called
        mock_shrink.assert_not_called()
        assert result is original_image


def test_determine_date_today():
    """Test _determine_date with no special settings (uses today)."""
    from plugins.wpotd.wpotd import Wpotd
    from datetime import datetime

    p = Wpotd({"id": "wpotd"})
    result = p._determine_date({})

    assert result == datetime.today().date()


def test_determine_date_random(monkeypatch):
    """Test _determine_date with random date enabled."""
    from plugins.wpotd.wpotd import Wpotd
    from datetime import datetime, timedelta

    p = Wpotd({"id": "wpotd"})

    # Mock randint to return a predictable value
    with patch('plugins.wpotd.wpotd.randint') as mock_randint:
        mock_randint.return_value = 100  # 100 days from start

        result = p._determine_date({'randomizeWpotd': 'true'})

        expected_date = datetime(2015, 1, 1).date() + timedelta(days=100)
        assert result == expected_date


def test_determine_date_custom():
    """Test _determine_date with custom date."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})
    result = p._determine_date({'customDate': '2023-12-25'})

    assert str(result) == '2023-12-25'


def test_download_image_success():
    """Test _download_image with successful download."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})

    # Mock the session get
    with patch.object(p.SESSION, 'get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = _png_bytes()
        mock_get.return_value = mock_response

        # Mock PIL Image
        with patch('plugins.wpotd.wpotd.Image') as mock_image:
            mock_image.open.return_value.__enter__.return_value.copy.return_value = MagicMock()

            result = p._download_image("http://example.com/image.png")

            assert result is not None
            mock_get.assert_called_once()


def test_download_image_network_error():
    """Test _download_image with network error."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})

    # Mock the session get to raise exception
    with patch.object(p.SESSION, 'get') as mock_get:
        mock_get.side_effect = Exception("Network error")

        with pytest.raises(RuntimeError, match="Failed to load WPOTD image"):
            p._download_image("http://example.com/image.png")


def test_download_image_invalid_format():
    """Test _download_image with invalid image format."""
    from plugins.wpotd.wpotd import Wpotd
    from PIL import UnidentifiedImageError

    p = Wpotd({"id": "wpotd"})

    # Mock the session get
    with patch.object(p.SESSION, 'get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'invalid_image_data'
        mock_get.return_value = mock_response

        # Mock PIL Image to raise UnidentifiedImageError
        with patch('plugins.wpotd.wpotd.Image') as mock_image:
            mock_image.open.side_effect = UnidentifiedImageError("Cannot identify image")

            with pytest.raises(RuntimeError, match="Unsupported image format"):
                p._download_image("http://example.com/image.png")


def test_fetch_image_src_success():
    """Test _fetch_image_src with successful response."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})

    # Mock _make_request
    with patch.object(p, '_make_request') as mock_make_request:
        mock_make_request.return_value = {
            "query": {
                "pages": {
                    "123": {
                        "imageinfo": [{"url": "http://example.com/full_image.png"}]
                    }
                }
            }
        }

        result = p._fetch_image_src("File:Example.png")

        assert result == "http://example.com/full_image.png"
        mock_make_request.assert_called_once()


def test_fetch_image_src_missing_url():
    """Test _fetch_image_src with missing URL in response."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})

    # Mock _make_request with missing URL
    with patch.object(p, '_make_request') as mock_make_request:
        mock_make_request.return_value = {
            "query": {
                "pages": {
                    "123": {
                        "imageinfo": [{}]  # Empty imageinfo
                    }
                }
            }
        }

        with pytest.raises(RuntimeError, match="Image URL missing in response"):
            p._fetch_image_src("File:Example.png")


def test_fetch_image_src_api_error():
    """Test _fetch_image_src with API error."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})

    # Mock _make_request to raise RuntimeError (as the method does)
    with patch.object(p, '_make_request') as mock_make_request:
        mock_make_request.side_effect = RuntimeError("Wikipedia API request failed")

        with pytest.raises(RuntimeError, match="Wikipedia API request failed"):
            p._fetch_image_src("File:Example.png")


def test_shrink_to_fit_no_resize_needed():
    """Test _shrink_to_fit when image is already within bounds."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})

    # Create small image that doesn't need resizing
    small_image = Image.new("RGB", (400, 300), "white")

    result = p._shrink_to_fit(small_image, 800, 600)

    # Should return the original image unchanged
    assert result is small_image


def test_shrink_to_fit_landscape_resize():
    """Test _shrink_to_fit with landscape image that needs resizing."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})

    # Create large landscape image
    large_image = Image.new("RGB", (1200, 800), "white")

    result = p._shrink_to_fit(large_image, 800, 600)

    # Should create new image with target dimensions and paste resized image centered
    assert result.size[0] == 800  # Target width
    assert result.size[1] == 600  # Target height


def test_shrink_to_fit_portrait_resize():
    """Test _shrink_to_fit with portrait image that needs resizing."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})

    # Create large portrait image
    large_image = Image.new("RGB", (600, 1000), "white")

    result = p._shrink_to_fit(large_image, 800, 600)

    # Should create new image with target dimensions and paste resized image centered
    assert result.size[0] == 800  # Target width
    assert result.size[1] == 600  # Target height


def test_wpotd_generate_settings_template():
    """Test WPOTD plugin settings template generation."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})
    template = p.generate_settings_template()

    assert "style_settings" in template
    assert template["style_settings"] is False


def test_make_request_success():
    """Test _make_request with successful API call."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})

    # Mock session get
    with patch.object(p.SESSION, 'get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"query": {"pages": []}}
        mock_get.return_value = mock_response

        result = p._make_request({"action": "query"})

        assert result == {"query": {"pages": []}}
        mock_get.assert_called_once()


def test_make_request_api_error():
    """Test _make_request with API error."""
    from plugins.wpotd.wpotd import Wpotd

    p = Wpotd({"id": "wpotd"})

    # Mock session get to raise exception
    with patch.object(p.SESSION, 'get') as mock_get:
        mock_get.side_effect = Exception("API Error")

        with pytest.raises(RuntimeError, match="Wikipedia API request failed"):
            p._make_request({"action": "query"})


def test_fetch_potd_api_error():
    """Test _fetch_potd with API error."""
    from plugins.wpotd.wpotd import Wpotd
    from datetime import date

    p = Wpotd({"id": "wpotd"})

    # Mock _make_request to raise RuntimeError (as the method does)
    with patch.object(p, '_make_request') as mock_make_request:
        mock_make_request.side_effect = RuntimeError("Wikipedia API request failed")

        with pytest.raises(RuntimeError, match="Wikipedia API request failed"):
            p._fetch_potd(date.today())


def test_fetch_potd_missing_images():
    """Test _fetch_potd with missing images in response."""
    from plugins.wpotd.wpotd import Wpotd
    from datetime import date

    p = Wpotd({"id": "wpotd"})

    # Mock _make_request with malformed response
    with patch.object(p, '_make_request') as mock_make_request:

        mock_make_request.return_value = {
            "query": {
                "pages": [{"images": []}]  # Empty images array
            }
        }

        with pytest.raises(RuntimeError, match="Failed to retrieve POTD filename"):
            p._fetch_potd(date.today())

 