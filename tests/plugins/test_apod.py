# pyright: reportMissingImports=false
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import pytest


def test_apod_success(
    monkeypatch, device_config_dev, realistic_nasa_apod_response, fake_image_response
):
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setenv("NASA_SECRET", "k")

    api_resp = MagicMock()
    api_resp.status_code = 200
    api_resp.json.return_value = realistic_nasa_apod_response

    def fake_get(url, params=None, **kwargs):
        assert urlparse(url).netloc == "api.nasa.gov"
        return api_resp

    mock_session = MagicMock()
    mock_session.get.side_effect = fake_get
    monkeypatch.setattr("plugins.apod.apod.get_http_session", lambda: mock_session)

    plugin = Apod({"id": "apod"})
    fake_image = MagicMock()
    fake_image.size = (64, 64)
    monkeypatch.setattr(
        plugin.image_loader, "from_url", MagicMock(return_value=fake_image)
    )

    img = plugin.generate_image({}, device_config_dev)
    assert img.size[0] > 0


def test_apod_requires_key(monkeypatch, device_config_dev):
    from plugins.apod.apod import Apod

    monkeypatch.delenv("NASA_SECRET", raising=False)
    try:
        Apod({"id": "apod"}).generate_image({}, device_config_dev)
        assert False, "Expected missing key error"
    except RuntimeError:
        pass


def test_apod_missing_key(client):
    import os

    if "NASA_SECRET" in os.environ:
        del os.environ["NASA_SECRET"]
    data = {
        "plugin_id": "apod",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 400


@patch("plugins.apod.apod.get_http_session")
def test_apod_success_via_client(mock_get_session, client):
    import os

    from PIL import Image

    os.environ["NASA_SECRET"] = "test"

    # Mock NASA APOD API response
    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "media_type": "image",
        "hdurl": "http://example.com/apod.png",
    }
    mock_session.get.return_value = mock_response

    fake_image = Image.new("RGB", (64, 64), "black")
    with patch(
        "plugins.base_plugin.base_plugin.AdaptiveImageLoader.from_url",
        return_value=fake_image,
    ):
        data = {"plugin_id": "apod"}
        resp = client.post("/update_now", data=data)
    assert resp.status_code == 200


def test_apod_randomize_date(monkeypatch, device_config_dev):
    """Test APOD plugin with random date generation."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setenv("NASA_SECRET", "test_key")

    # Mock get_http_session
    with patch("plugins.apod.apod.get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Mock NASA API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/apod.png",
        }
        mock_session.get.side_effect = [mock_api_response]

        p = Apod({"id": "apod"})
        fake_image = MagicMock()
        fake_image.size = (64, 64)
        with patch.object(p.image_loader, "from_url", return_value=fake_image):
            settings = {"randomizeApod": "true"}
            result = p.generate_image(settings, device_config_dev)

        # Verify API was called with random date parameter
        api_call = mock_session.get.call_args_list[0]
        assert urlparse(api_call[0][0]).netloc == "api.nasa.gov"
        assert "date" in api_call[1]["params"]
        assert result is not None


def test_apod_custom_date(monkeypatch, device_config_dev):
    """Test APOD plugin with custom date."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setenv("NASA_SECRET", "test_key")

    # Mock get_http_session
    with patch("plugins.apod.apod.get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Mock NASA API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/apod.png",
        }

        mock_session.get.side_effect = [mock_api_response]

        p = Apod({"id": "apod"})
        fake_image = MagicMock()
        fake_image.size = (64, 64)
        with patch.object(p.image_loader, "from_url", return_value=fake_image):
            custom_date = "2023-12-25"
            settings = {"customDate": custom_date}
            result = p.generate_image(settings, device_config_dev)

        # Verify API was called with custom date
        api_call = mock_session.get.call_args_list[0]
        assert api_call[1]["params"]["date"] == custom_date
        assert result is not None


def test_apod_api_error_response(device_config_dev, monkeypatch):
    """Test APOD plugin with NASA API error response."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "test_key")

    # Mock get_http_session to return error status
    with patch("plugins.apod.apod.get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_session.get.return_value = mock_response

        p = Apod({"id": "apod"})

        with pytest.raises(RuntimeError, match="Failed to retrieve NASA APOD"):
            p.generate_image({}, device_config_dev)


def test_apod_hdurl_preference_on_non_low_resource(device_config_dev, monkeypatch):
    """Test APOD plugin prefers HD URL on non-low-resource devices."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "test_key")

    # Mock get_http_session
    with patch("plugins.apod.apod.get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Mock NASA API response with both URLs
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/low_res.png",
            "hdurl": "http://example.com/high_res.png",
        }

        mock_session.get.side_effect = [mock_api_response]

        p = Apod({"id": "apod"})
        p.image_loader.is_low_resource = False
        fake_image = MagicMock()
        fake_image.size = (64, 64)
        with patch.object(
            p.image_loader, "from_url", return_value=fake_image
        ) as mock_from_url:
            result = p.generate_image({}, device_config_dev)

        assert mock_from_url.call_args.args[0] == "http://example.com/high_res.png"
        assert result is not None


def test_apod_prefers_regular_url_on_low_resource_device(
    device_config_dev, monkeypatch
):
    """Low-memory devices should avoid NASA's HD asset when a regular URL exists."""
    from plugins.apod.apod import Apod

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "test_key")

    with patch("plugins.apod.apod.get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/low_res.png",
            "hdurl": "http://example.com/high_res.png",
        }
        mock_session.get.side_effect = [mock_api_response]

        p = Apod({"id": "apod"})
        p.image_loader.is_low_resource = True
        fake_image = MagicMock()
        fake_image.size = (64, 64)
        with patch.object(
            p.image_loader, "from_url", return_value=fake_image
        ) as mock_from_url:
            result = p.generate_image({}, device_config_dev)

        assert mock_from_url.call_args.args[0] == "http://example.com/low_res.png"
        assert result is not None


def test_apod_image_download_failure(device_config_dev, monkeypatch):
    """Test APOD plugin errors when no candidate image URL can be loaded."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "test_key")

    # Mock get_http_session
    with patch("plugins.apod.apod.get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Mock NASA API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/apod.png",
        }

        mock_session.get.side_effect = [mock_api_response]

        p = Apod({"id": "apod"})
        with patch.object(p.image_loader, "from_url", return_value=None):
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
    assert "settings_schema" in template


def test_apod_falls_back_to_second_url_when_first_load_fails(
    device_config_dev, monkeypatch
):
    """APOD should try the alternate URL if the preferred one fails to load."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "test_key")

    # Mock get_http_session
    with patch("plugins.apod.apod.get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Mock NASA API response
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/apod.png",
        }

        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/low_res.png",
            "hdurl": "http://example.com/high_res.png",
        }
        mock_session.get.side_effect = [mock_api_response]

        p = Apod({"id": "apod"})
        p.image_loader.is_low_resource = False
        fake_image = MagicMock()
        fake_image.size = (64, 64)
        with patch.object(
            p.image_loader,
            "from_url",
            side_effect=[None, fake_image],
        ) as mock_from_url:
            result = p.generate_image({}, device_config_dev)

        assert [call.args[0] for call in mock_from_url.call_args_list] == [
            "http://example.com/high_res.png",
            "http://example.com/low_res.png",
        ]
        assert result is fake_image


def test_apod_missing_hdurl_fallback(device_config_dev, monkeypatch):
    """Test APOD plugin falls back to regular URL when HD URL is missing."""
    from plugins.apod.apod import Apod

    # Mock env key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "test_key")

    # Mock get_http_session
    with patch("plugins.apod.apod.get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Mock NASA API response with only regular URL
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "media_type": "image",
            "url": "http://example.com/low_res.png",
            # No hdurl field
        }

        mock_session.get.side_effect = [mock_api_response]

        p = Apod({"id": "apod"})
        fake_image = MagicMock()
        fake_image.size = (64, 64)
        with patch.object(
            p.image_loader, "from_url", return_value=fake_image
        ) as mock_from_url:
            result = p.generate_image({}, device_config_dev)

        assert mock_from_url.call_args.args[0] == "http://example.com/low_res.png"
        assert result is not None
