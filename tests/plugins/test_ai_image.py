# pyright: reportMissingImports=false
from unittest.mock import MagicMock, patch

import pytest

@pytest.fixture(autouse=True)
def mock_openai():
    """Mock OpenAI for all ai_image tests."""
    with patch('plugins.ai_image.ai_image.OpenAI') as mock:
        # Create a mock OpenAI client
        mock_client = MagicMock()
        mock.return_value = mock_client

        # Mock chat completions for prompt randomization
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "randomized prompt"
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        # Mock images.generate
        mock_image_response = MagicMock()
        mock_image_response.data = [MagicMock()]
        mock_image_response.data[0].url = "http://example.com/image.png"
        mock_client.images.generate.return_value = mock_image_response

        yield mock

def test_ai_image_missing_api_key(device_config_dev):
    """Test ai_image plugin with missing API key."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    settings = {"textPrompt": "a cat", "imageModel": "dall-e-3", "quality": "standard"}

    # Mock API key to return None (missing key)
    with patch.object(device_config_dev, "load_env_key", lambda key: None):
        with pytest.raises(RuntimeError, match="OPEN AI API Key not configured"):
            p.generate_image(settings, device_config_dev)

def test_ai_image_invalid_model(client, monkeypatch):
    monkeypatch.setenv("OPEN_AI_SECRET", "test")
    data = {
        "plugin_id": "ai_image",
        "textPrompt": "a cat",
        "imageModel": "invalid-model",
        "quality": "standard",
    }
    resp = client.post("/update_now", data=data)
    assert resp.status_code == 500

def test_ai_image_generate_image_success(client, monkeypatch, mock_openai):
    monkeypatch.setenv("OPEN_AI_SECRET", "test")

    # Mock requests.get to image URL (upstream uses requests.get, not http_utils.http_get)
    from io import BytesIO
    import base64
    from PIL import Image

    def fake_get(url):
        img = Image.new("RGB", (64, 64), "black")
        buf = BytesIO()
        img.save(buf, format="PNG")

        class R:
            content = buf.getvalue()
            status_code = 200

        return R()

    monkeypatch.setattr("requests.get", fake_get)

    # For gpt-image-1, mock b64_json response
    img = Image.new("RGB", (64, 64), "black")
    buf = BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    mock_client = mock_openai.return_value
    mock_image_response = mock_client.images.generate.return_value
    mock_image_response.data[0].b64_json = img_b64

    for model, quality in [
        ("dall-e-3", "standard"),
        ("dall-e-3", "hd"),
        ("gpt-image-1", "high"),
        ("gpt-image-1", "standard"),  # should normalize to 'medium'
        ("gpt-image-1", "low"),
        ("gpt-image-1", "medium"),
        ("gpt-image-1", "auto"),
    ]:
        data = {
            "plugin_id": "ai_image",
            "textPrompt": "a cat",
            "imageModel": model,
            "quality": quality,
        }
        resp = client.post("/update_now", data=data)
        assert resp.status_code == 200
        # Just verify successful response - upstream doesn't use same progress tracking

def test_ai_image_openai_api_failure(device_config_dev, monkeypatch):
    """Test ai_image plugin with OpenAI API failure."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})

    # Mock API key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    # Mock OpenAI to raise exception
    with patch("plugins.ai_image.ai_image.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.images.generate.side_effect = Exception("API Error")

        settings = {
            "textPrompt": "a cat",
            "imageModel": "dall-e-3",
            "quality": "standard",
        }

        with pytest.raises(RuntimeError, match="Open AI request failure"):
            p.generate_image(settings, device_config_dev)

def test_ai_image_image_download_failure(device_config_dev, monkeypatch):
    """Test ai_image plugin with image download failure."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})

    # Mock API key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    # Mock OpenAI response
    with (
        patch("plugins.ai_image.ai_image.OpenAI") as mock_openai,
        patch("utils.http_utils.http_get") as mock_requests,
    ):

        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.data = [MagicMock()]
        mock_response.data[0].url = "http://example.com/image.png"
        mock_client.images.generate.return_value = mock_response

        # Mock requests to fail
        mock_requests.side_effect = Exception("Download failed")

        settings = {
            "textPrompt": "a cat",
            "imageModel": "dall-e-3",
            "quality": "standard",
        }

        with pytest.raises(RuntimeError, match="Open AI request failure"):
            p.generate_image(settings, device_config_dev)

def test_ai_image_randomize_prompt_enabled(device_config_dev, monkeypatch):
    """Test ai_image plugin with prompt randomization enabled."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})

    # Mock API key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    # Mock OpenAI client
    with (
        patch("plugins.ai_image.ai_image.OpenAI") as mock_openai,
        patch("utils.http_utils.http_get") as mock_requests,
        patch(
            "plugins.ai_image.ai_image.AIImage.fetch_image_prompt"
        ) as mock_fetch_prompt,
    ):

        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # Mock OpenAI image generation
        mock_response = MagicMock()
        mock_response.data = [MagicMock()]
        mock_response.data[0].url = "http://example.com/image.png"
        mock_client.images.generate.return_value = mock_response

        # Mock requests for image download
        mock_img_response = MagicMock()
        mock_img_response.content = b"fake_image_data"
        mock_requests.return_value = mock_img_response

        # Mock PIL Image
        with patch("plugins.ai_image.ai_image.Image") as mock_image:
            mock_image.open.return_value.__enter__.return_value.copy.return_value = (
                MagicMock()
            )

            mock_fetch_prompt.return_value = "randomized creative prompt"

            settings = {
                "textPrompt": "a cat",
                "imageModel": "dall-e-3",
                "quality": "standard",
                "randomizePrompt": "true",
            }

            result = p.generate_image(settings, device_config_dev)

            # Verify prompt randomization was called
            mock_fetch_prompt.assert_called_once_with(mock_client, "a cat")
            assert result is not None

def test_ai_image_randomize_prompt_blank_input(device_config_dev, monkeypatch):
    """Test ai_image plugin with blank prompt when randomization is enabled."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})

    # Mock API key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    # Mock OpenAI client
    with (
        patch("plugins.ai_image.ai_image.OpenAI") as mock_openai,
        patch("utils.http_utils.http_get") as mock_requests,
        patch(
            "plugins.ai_image.ai_image.AIImage.fetch_image_prompt"
        ) as mock_fetch_prompt,
    ):

        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # Mock OpenAI image generation
        mock_response = MagicMock()
        mock_response.data = [MagicMock()]
        mock_response.data[0].url = "http://example.com/image.png"
        mock_client.images.generate.return_value = mock_response

        # Mock requests for image download
        mock_img_response = MagicMock()
        mock_img_response.content = b"fake_image_data"
        mock_requests.return_value = mock_img_response

        # Mock PIL Image
        with patch("plugins.ai_image.ai_image.Image") as mock_image:
            mock_image.open.return_value.__enter__.return_value.copy.return_value = (
                MagicMock()
            )

            mock_fetch_prompt.return_value = "completely random prompt"

            settings = {
                "textPrompt": "",  # Blank prompt
                "imageModel": "dall-e-3",
                "quality": "standard",
                "randomizePrompt": "true",
            }

            result = p.generate_image(settings, device_config_dev)

            # Verify prompt randomization was called with None/empty
            mock_fetch_prompt.assert_called_once_with(mock_client, "")
            assert result is not None

def test_fetch_image_prompt_basic(monkeypatch):
    """Test fetch_image_prompt with basic functionality."""
    from plugins.ai_image.ai_image import AIImage

    # Mock OpenAI client
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "A surreal painting of a cat riding a bicycle"
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    result = AIImage.fetch_image_prompt(mock_client, "a cat")

    assert result == "A surreal painting of a cat riding a bicycle"
    mock_client.chat.completions.create.assert_called_once()

    # Verify the call arguments
    call_args = mock_client.chat.completions.create.call_args
    assert call_args[1]["model"] == "gpt-4o"
    assert len(call_args[1]["messages"]) == 2
    assert "system" in call_args[1]["messages"][0]["role"]
    assert "user" in call_args[1]["messages"][1]["role"]

def test_fetch_image_prompt_blank_input(monkeypatch):
    """Test fetch_image_prompt with blank input."""
    from plugins.ai_image.ai_image import AIImage

    # Mock OpenAI client
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "A completely random artistic creation"
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    result = AIImage.fetch_image_prompt(mock_client, "")

    assert result == "A completely random artistic creation"
    mock_client.chat.completions.create.assert_called_once()

def test_fetch_image_prompt_none_input(monkeypatch):
    """Test fetch_image_prompt with None input."""
    from plugins.ai_image.ai_image import AIImage

    # Mock OpenAI client
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "An unexpected bizarre combination"
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    result = AIImage.fetch_image_prompt(mock_client, None)

    assert result == "An unexpected bizarre combination"
    mock_client.chat.completions.create.assert_called_once()

def test_fetch_image_prompt_api_failure(monkeypatch):
    """Test fetch_image_prompt with API failure."""
    from plugins.ai_image.ai_image import AIImage

    # Mock OpenAI client to raise exception
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API Error")

    with pytest.raises(Exception, match="API Error"):
        AIImage.fetch_image_prompt(mock_client, "a cat")

def test_ai_image_orientation_handling(device_config_dev, monkeypatch):
    """Test ai_image plugin with different orientations."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})

    # Mock API key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    # Mock device config for vertical orientation
    monkeypatch.setattr(
        device_config_dev,
        "get_config",
        lambda key, default=None: {"orientation": "vertical"}.get(key, default),
    )

    # Mock OpenAI and requests
    with (
        patch("plugins.ai_image.ai_image.OpenAI") as mock_openai,
        patch("utils.http_utils.http_get") as mock_requests,
    ):

        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.data = [MagicMock()]
        mock_response.data[0].url = "http://example.com/image.png"
        mock_client.images.generate.return_value = mock_response

        # Mock image download
        mock_img_response = MagicMock()
        mock_img_response.content = b"fake_image_data"
        mock_requests.return_value = mock_img_response

        with patch("plugins.ai_image.ai_image.Image") as mock_image:
            mock_image.open.return_value.__enter__.return_value.copy.return_value = (
                MagicMock()
            )

            settings = {
                "textPrompt": "a cat",
                "imageModel": "dall-e-3",
                "quality": "standard",
            }

            p.generate_image(settings, device_config_dev)

            # Verify vertical orientation was passed to fetch_image
            mock_client.images.generate.assert_called_once()
            call_kwargs = mock_client.images.generate.call_args[1]
            assert call_kwargs["size"] == "1024x1792"  # Vertical size for dall-e-3

def test_ai_image_quality_normalization_edge_cases(device_config_dev, monkeypatch):
    """Test quality normalization edge cases."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})

    # Mock API key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    # Test various quality inputs
    test_cases = [
        ("dall-e-3", "HD", "hd"),
        ("dall-e-3", "high", "hd"),
        ("dall-e-3", "standard", "standard"),
        ("dall-e-3", "", "standard"),
        ("gpt-image-1", "LOW", "low"),
        ("gpt-image-1", "High", "high"),
        ("gpt-image-1", "auto", "auto"),
        ("gpt-image-1", "invalid", "medium"),  # Should fallback
        ("dall-e-2", "hd", None),  # No quality for dall-e-2
    ]

    for model, input_quality, expected_quality in test_cases:
        with (
            patch("plugins.ai_image.ai_image.OpenAI") as mock_openai,
            patch("requests.get") as mock_requests,
        ):

            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            # Mock OpenAI response
            mock_response = MagicMock()
            mock_response.data = [MagicMock()]
            mock_response.data[0].url = "http://example.com/image.png"
            # For gpt-image-1
            from io import BytesIO
            import base64
            from PIL import Image as PILImage
            img = PILImage.new("RGB", (64, 64), "black")
            buf = BytesIO()
            img.save(buf, format="PNG")
            mock_response.data[0].b64_json = base64.b64encode(buf.getvalue()).decode()
            mock_client.images.generate.return_value = mock_response

            # Mock image download (for dall-e models)
            mock_img_response = MagicMock()
            mock_img_response.content = buf.getvalue()
            mock_requests.return_value = mock_img_response

            with patch("plugins.ai_image.ai_image.Image") as mock_image:
                # Mock Image.open to return a MagicMock that works as context manager
                mock_img_obj = MagicMock()
                mock_image.open.return_value.__enter__.return_value = mock_img_obj
                mock_image.open.return_value.__exit__.return_value = None

                settings = {
                    "textPrompt": "a cat",
                    "imageModel": model,
                    "quality": input_quality,
                }

                p.generate_image(settings, device_config_dev)

                # Verify quality was normalized correctly
                call_kwargs = mock_client.images.generate.call_args[1]
                if expected_quality is None:
                    assert "quality" not in call_kwargs
                else:
                    assert call_kwargs.get("quality") == expected_quality

def test_ai_image_generate_settings_template():
    """Test settings template generation."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    template = p.generate_settings_template()

    assert "api_key" in template
    assert template["api_key"]["service"] == "OpenAI"
    assert template["api_key"]["expected_key"] == "OPEN_AI_SECRET"
    assert template["api_key"]["required"] is True

def test_fetch_image_prompt_api_error_handling():
    """Test fetch_image_prompt with malformed API response."""
    from plugins.ai_image.ai_image import AIImage

    # Mock client with malformed response
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = []  # Empty choices
    mock_client.chat.completions.create.return_value = mock_response

    with pytest.raises(IndexError):
        AIImage.fetch_image_prompt(mock_client, "a cat")

def test_fetch_image_prompt_content_parsing():
    """Test fetch_image_prompt with various content formats."""
    from plugins.ai_image.ai_image import AIImage

    test_cases = [
        ("  Some prompt  ", "Some prompt"),  # Leading/trailing spaces
        ("Prompt with\nnewlines", "Prompt with\nnewlines"),  # Newlines
        ("", ""),  # Empty
        ("   ", ""),  # Only spaces
    ]

    for input_content, expected_output in test_cases:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = input_content
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        result = AIImage.fetch_image_prompt(mock_client, "test")

        assert result == expected_output
