# pyright: reportMissingImports=false
import base64
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image as PILImage


class _FakeOpenAIImageError(Exception):
    def __init__(self) -> None:
        super().__init__("provider rejected request req_testblocked123")
        self.body = {
            "error": {
                "message": "Your request was rejected by the safety system.",
                "type": "image_generation_user_error",
                "code": "moderation_blocked",
            }
        }
        self.request_id = "req_testblocked123"


@pytest.fixture(autouse=True)
def mock_openai():
    """Mock OpenAI for all ai_image tests."""
    with patch("plugins.ai_image.ai_image.OpenAI") as mock:
        mock_client = MagicMock()
        mock.return_value = mock_client

        # Mock chat completions for prompt randomization
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "randomized prompt"
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        # Mock images.generate with b64_json
        img = PILImage.new("RGB", (64, 64), "black")
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        mock_image_response = MagicMock()
        mock_image_response.data = [MagicMock()]
        mock_image_response.data[0].b64_json = img_b64
        mock_client.images.generate.return_value = mock_image_response

        yield mock


def test_ai_image_missing_api_key(device_config_dev):
    """Test ai_image plugin with missing API key."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    settings = {
        "textPrompt": "a cat",
        "imageModel": "gpt-image-1.5",
        "quality": "medium",
    }

    with patch.object(device_config_dev, "load_env_key", lambda key: None):
        with pytest.raises(RuntimeError, match="OpenAI API Key not configured"):
            p.generate_image(settings, device_config_dev)


def test_ai_image_missing_google_api_key(device_config_dev):
    """Test ai_image plugin with missing Google API key."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    settings = {
        "textPrompt": "a cat",
        "provider": "google",
        "imageModel": "imagen-4.0-generate-001",
        "quality": "standard",
    }

    with patch.object(device_config_dev, "load_env_key", lambda key: None):
        with pytest.raises(RuntimeError, match="Google AI API Key not configured"):
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
    assert resp.status_code == 400


def test_ai_image_validate_settings_rejects_provider_model_mismatch():
    from plugins.ai_image.ai_image import AIImage

    plugin = AIImage({"id": "ai_image"})
    error = plugin.validate_settings(
        {
            "textPrompt": "a cat",
            "provider": "google",
            "imageModel": "gpt-image-1.5",
        }
    )
    assert error is not None
    assert "Invalid image model for provider" in error
    assert "google" in error


def test_ai_image_validate_settings_uses_default_model_for_openai() -> None:
    from plugins.ai_image.ai_image import AIImage

    plugin = AIImage({"id": "ai_image"})
    assert (
        plugin.validate_settings({"textPrompt": "a cat", "provider": "openai"}) is None
    )


def test_ai_image_validate_settings_allows_blank_prompt_when_vivid_remix_enabled() -> (
    None
):
    from plugins.ai_image.ai_image import AIImage

    plugin = AIImage({"id": "ai_image"})

    assert (
        plugin.validate_settings(
            {
                "textPrompt": "",
                "randomizePrompt": "true",
                "provider": "openai",
            }
        )
        is None
    )


def test_ai_image_validate_settings_rejects_blank_prompt_without_vivid_remix() -> None:
    from plugins.ai_image.ai_image import AIImage

    plugin = AIImage({"id": "ai_image"})

    error = plugin.validate_settings(
        {
            "textPrompt": " ",
            "randomizePrompt": "false",
            "provider": "openai",
        }
    )

    assert error == "Prompt is required."


def test_ai_image_generate_image_success(client, monkeypatch, mock_openai):
    monkeypatch.setenv("OPEN_AI_SECRET", "test")

    for model, quality in [
        ("gpt-image-1.5", "high"),
        ("gpt-image-1.5", "medium"),
        ("gpt-image-1.5", "low"),
        ("gpt-image-1.5", "auto"),
    ]:
        data = {
            "plugin_id": "ai_image",
            "textPrompt": "a cat",
            "imageModel": model,
            "quality": quality,
        }
        resp = client.post("/update_now", data=data)
        assert resp.status_code == 200


def test_ai_image_openai_resizes_generated_image_to_display(
    device_config_dev, monkeypatch, mock_openai
):
    from plugins.ai_image.ai_image import AIImage

    monkeypatch.setenv("OPEN_AI_SECRET", "test")

    plugin = AIImage({"id": "ai_image"})
    result = plugin.generate_image(
        {
            "textPrompt": "a cat",
            "provider": "openai",
            "imageModel": "gpt-image-2",
            "quality": "medium",
        },
        device_config_dev,
    )

    assert result.size == tuple(device_config_dev.get_resolution())


def test_ai_image_google_generate_success(device_config_dev, monkeypatch):
    """Test ai_image plugin with Google Imagen provider."""
    import sys

    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    mock_pil_image = MagicMock(spec=PILImage.Image)
    mock_pil_image.size = (1024, 1024)

    # Build fake google.genai module hierarchy
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai

    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    # Build real PNG bytes for the mock
    _buf = BytesIO()
    PILImage.new("RGB", (64, 64), "red").save(_buf, format="PNG")
    _png_bytes = _buf.getvalue()

    mock_response = MagicMock()
    mock_generated = MagicMock()
    mock_generated.image.image_bytes = _png_bytes
    mock_response.generated_images = [mock_generated]
    mock_client.models.generate_images.return_value = mock_response

    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", mock_genai.types)

    settings = {
        "textPrompt": "a cat",
        "provider": "google",
        "imageModel": "imagen-4.0-generate-001",
        "quality": "standard",
    }

    result = p.generate_image(settings, device_config_dev)
    assert result is not None
    assert isinstance(result, PILImage.Image)
    assert result.size == tuple(device_config_dev.get_resolution())


def test_ai_image_google_empty_results_raises(device_config_dev, monkeypatch):
    """Bug 5: Empty generated_images should raise RuntimeError."""
    import sys

    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai

    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    mock_response = MagicMock()
    mock_response.generated_images = []
    mock_client.models.generate_images.return_value = mock_response

    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", mock_genai.types)

    settings = {
        "textPrompt": "a cat",
        "provider": "google",
        "imageModel": "imagen-4.0-generate-001",
        "quality": "standard",
    }

    with pytest.raises(RuntimeError, match="no images"):
        p.generate_image(settings, device_config_dev)


def test_ai_image_openai_api_failure(device_config_dev, monkeypatch):
    """Test ai_image plugin with OpenAI API failure."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    with patch("plugins.ai_image.ai_image.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.images.generate.side_effect = Exception("API Error")

        settings = {
            "textPrompt": "a cat",
            "imageModel": "gpt-image-1.5",
            "quality": "medium",
        }

        with pytest.raises(RuntimeError, match="API request failure"):
            p.generate_image(settings, device_config_dev)


def test_ai_image_openai_moderation_block_reports_provider_reason(
    device_config_dev: Any, monkeypatch: Any
) -> None:
    from plugins.ai_image.ai_image import AIImage
    from utils.plugin_errors import (
        OPENAI_MODERATION_BLOCKED_MSG,
        ProviderReportedPluginError,
    )

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    with patch("plugins.ai_image.ai_image.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.images.generate.side_effect = _FakeOpenAIImageError()

        with pytest.raises(ProviderReportedPluginError) as exc:
            p.generate_image(
                {
                    "textPrompt": "icy sci-fi cathedral",
                    "provider": "openai",
                    "imageModel": "gpt-image-2",
                    "quality": "medium",
                    "safeRewriteBlockedPrompt": "false",
                },
                device_config_dev,
            )

    message = str(exc.value)
    assert "moderation_blocked" in message
    assert "req_testblocked123" in message
    assert exc.value.safe_message() == OPENAI_MODERATION_BLOCKED_MSG
    assert mock_client.chat.completions.create.call_count == 0


def test_ai_image_openai_safe_rewrite_retries_moderation_block(
    device_config_dev: Any, monkeypatch: Any
) -> None:
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    with patch("plugins.ai_image.ai_image.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        img = PILImage.new("RGB", (64, 64), "black")
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        success = MagicMock()
        success.data = [MagicMock()]
        success.data[0].b64_json = img_b64

        mock_client.images.generate.side_effect = [
            _FakeOpenAIImageError(),
            success,
        ]
        rewrite_response = MagicMock()
        rewrite_choice = MagicMock()
        rewrite_choice.message.content = "generic icy retro science fiction cathedral"
        rewrite_response.choices = [rewrite_choice]
        mock_client.chat.completions.create.return_value = rewrite_response

        result = p.generate_image(
            {
                "textPrompt": "icy sci-fi cathedral",
                "provider": "openai",
                "imageModel": "gpt-image-2",
                "quality": "medium",
                "safeRewriteBlockedPrompt": "true",
            },
            device_config_dev,
        )

    assert result.size == tuple(device_config_dev.get_resolution())
    assert mock_client.images.generate.call_count == 2
    second_prompt = mock_client.images.generate.call_args_list[1].kwargs["prompt"]
    assert "generic icy retro science fiction cathedral" in second_prompt


def test_ai_image_openai_safe_rewrite_reports_retry_rejection(
    device_config_dev: Any, monkeypatch: Any
) -> None:
    from plugins.ai_image.ai_image import AIImage
    from utils.plugin_errors import (
        OPENAI_MODERATION_BLOCKED_MSG,
        ProviderReportedPluginError,
    )

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    with patch("plugins.ai_image.ai_image.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.images.generate.side_effect = [
            _FakeOpenAIImageError(),
            _FakeOpenAIImageError(),
        ]
        rewrite_response = MagicMock()
        rewrite_choice = MagicMock()
        rewrite_choice.message.content = "generic icy retro science fiction cathedral"
        rewrite_response.choices = [rewrite_choice]
        mock_client.chat.completions.create.return_value = rewrite_response

        with pytest.raises(ProviderReportedPluginError) as exc:
            p.generate_image(
                {
                    "textPrompt": "icy sci-fi cathedral",
                    "provider": "openai",
                    "imageModel": "gpt-image-2",
                    "quality": "medium",
                    "safeRewriteBlockedPrompt": "true",
                },
                device_config_dev,
            )

    message = str(exc.value)
    assert "moderation_blocked" in message
    assert "req_testblocked123" in message
    assert exc.value.safe_message() == OPENAI_MODERATION_BLOCKED_MSG
    assert mock_client.images.generate.call_count == 2
    assert mock_client.chat.completions.create.call_count == 1


def test_ai_image_raises_when_provider_returns_no_image(device_config_dev, monkeypatch):
    """AI image generation should not return None on a falsy provider response."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    with (
        patch("plugins.ai_image.ai_image.OpenAI") as mock_openai,
        patch.object(AIImage, "fetch_image", return_value=None),
    ):
        mock_openai.return_value = MagicMock()

        with pytest.raises(RuntimeError, match="Failed to generate image"):
            p.generate_image(
                {
                    "textPrompt": "a cat",
                    "imageModel": "gpt-image-1.5",
                    "quality": "medium",
                },
                device_config_dev,
            )


def test_ai_image_randomize_prompt_enabled(device_config_dev, monkeypatch):
    """Test ai_image plugin with prompt randomization enabled."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    with (
        patch("plugins.ai_image.ai_image.OpenAI") as mock_openai,
        patch(
            "plugins.ai_image.ai_image.AIImage.fetch_image_prompt"
        ) as mock_fetch_prompt,
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # Mock b64 image response
        img = PILImage.new("RGB", (64, 64), "black")
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        mock_response = MagicMock()
        mock_response.data = [MagicMock()]
        mock_response.data[0].b64_json = img_b64
        mock_client.images.generate.return_value = mock_response

        mock_fetch_prompt.return_value = "randomized creative prompt"

        settings = {
            "textPrompt": "a cat",
            "imageModel": "gpt-image-1.5",
            "quality": "medium",
            "randomizePrompt": "true",
        }

        result = p.generate_image(settings, device_config_dev)

        mock_fetch_prompt.assert_called_once_with(mock_client, "a cat")
        assert result is not None


def test_ai_image_randomize_prompt_blank_input(device_config_dev, monkeypatch):
    """Test ai_image plugin with blank prompt when randomization is enabled."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    with (
        patch("plugins.ai_image.ai_image.OpenAI") as mock_openai,
        patch(
            "plugins.ai_image.ai_image.AIImage.fetch_image_prompt"
        ) as mock_fetch_prompt,
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        img = PILImage.new("RGB", (64, 64), "black")
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        mock_response = MagicMock()
        mock_response.data = [MagicMock()]
        mock_response.data[0].b64_json = img_b64
        mock_client.images.generate.return_value = mock_response

        mock_fetch_prompt.return_value = "completely random prompt"

        settings = {
            "textPrompt": "",
            "imageModel": "gpt-image-1.5",
            "quality": "medium",
            "randomizePrompt": "true",
        }

        result = p.generate_image(settings, device_config_dev)

        mock_fetch_prompt.assert_called_once_with(mock_client, "")
        assert result is not None


def test_ai_image_blank_prompt_without_randomize_raises(
    device_config_dev: Any, monkeypatch: Any
) -> None:
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    with pytest.raises(RuntimeError, match="Prompt is required"):
        p.generate_image(
            {
                "textPrompt": "",
                "imageModel": "gpt-image-2",
                "quality": "medium",
                "randomizePrompt": "false",
            },
            device_config_dev,
        )


def test_fetch_image_prompt_basic(monkeypatch):
    """Test fetch_image_prompt with basic functionality."""
    from plugins.ai_image.ai_image import AIImage

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "A surreal painting of a cat riding a bicycle"
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    result = AIImage.fetch_image_prompt(mock_client, "a cat")

    assert result == "A surreal painting of a cat riding a bicycle"
    mock_client.chat.completions.create.assert_called_once()

    call_args = mock_client.chat.completions.create.call_args
    assert call_args[1]["model"] == "gpt-5-nano"
    assert len(call_args[1]["messages"]) == 2
    assert "system" in call_args[1]["messages"][0]["role"]
    assert "user" in call_args[1]["messages"][1]["role"]


def test_fetch_image_prompt_blank_input(monkeypatch):
    """Test fetch_image_prompt with blank input."""
    from plugins.ai_image.ai_image import AIImage

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

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API Error")

    with pytest.raises(Exception, match="API Error"):
        AIImage.fetch_image_prompt(mock_client, "a cat")


def test_ai_image_orientation_handling(device_config_dev, monkeypatch):
    """Test ai_image plugin with different orientations."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")
    monkeypatch.setattr(
        device_config_dev,
        "get_config",
        lambda key, default=None: {"orientation": "vertical"}.get(key, default),
    )

    with patch("plugins.ai_image.ai_image.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        img = PILImage.new("RGB", (64, 64), "black")
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        mock_response = MagicMock()
        mock_response.data = [MagicMock()]
        mock_response.data[0].b64_json = img_b64
        mock_client.images.generate.return_value = mock_response

        settings = {
            "textPrompt": "a cat",
            "imageModel": "gpt-image-1.5",
            "quality": "medium",
        }

        p.generate_image(settings, device_config_dev)

        mock_client.images.generate.assert_called_once()
        call_kwargs = mock_client.images.generate.call_args[1]
        assert call_kwargs["size"] == "1024x1536"  # Vertical size


def test_ai_image_quality_normalization_edge_cases(device_config_dev, monkeypatch):
    """Test quality normalization edge cases."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    test_cases = [
        ("gpt-image-1.5", "LOW", "low"),
        ("gpt-image-1.5", "High", "high"),
        ("gpt-image-1.5", "auto", "auto"),
        ("gpt-image-1.5", "invalid", "medium"),  # Should fallback
        ("gpt-image-1.5", "medium", "medium"),
    ]

    for model, input_quality, expected_quality in test_cases:
        with patch("plugins.ai_image.ai_image.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            img = PILImage.new("RGB", (64, 64), "black")
            buf = BytesIO()
            img.save(buf, format="PNG")
            img_b64 = base64.b64encode(buf.getvalue()).decode()

            mock_response = MagicMock()
            mock_response.data = [MagicMock()]
            mock_response.data[0].b64_json = img_b64
            mock_client.images.generate.return_value = mock_response

            settings = {
                "textPrompt": "a cat",
                "imageModel": model,
                "quality": input_quality,
            }

            p.generate_image(settings, device_config_dev)

            call_kwargs = mock_client.images.generate.call_args[1]
            assert call_kwargs.get("quality") == expected_quality


def test_ai_image_generate_settings_template():
    """Test settings template generation."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    template = p.generate_settings_template()

    assert "api_key" in template
    assert template["api_key"]["required"] is True
    services = template["api_key"]["services"]
    assert [s["name"] for s in services] == ["OpenAI", "Google"]
    assert [s["env_var"] for s in services] == ["OPEN_AI_SECRET", "GOOGLE_AI_SECRET"]
    # Legacy expected_key/alt_key are now obsolete — `services` is the sole
    # source of truth for multi-provider plugins.
    assert "expected_key" not in template["api_key"]
    assert "alt_key" not in template["api_key"]
    assert "settings_schema" in template


def test_ai_image_prompt_field_is_textarea():
    """Prompt field should be a textarea so long prompts are not clipped (JTN-377)."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    schema = p.build_settings_schema()

    prompt_field = None
    for section in schema["sections"]:
        for item in section["items"]:
            if item.get("kind") == "field" and item.get("name") == "textPrompt":
                prompt_field = item
                break
        if prompt_field:
            break

    assert prompt_field is not None, "textPrompt field missing from schema"
    assert prompt_field["type"] == "textarea"
    assert prompt_field.get("rows") == 4
    assert prompt_field.get("required") is not True


def test_ai_image_schema_includes_random_prompt_widget() -> None:
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    schema = p.build_settings_schema()

    widgets = [
        item
        for section in schema["sections"]
        for item in section["items"]
        if item.get("kind") == "widget"
    ]

    assert any(item.get("widget_type") == "ai-image-prompt-tools" for item in widgets)


def test_ai_image_schema_includes_safe_rewrite_opt_in() -> None:
    from plugins.ai_image.ai_image import SAFE_REWRITE_SETTING, AIImage

    p = AIImage({"id": "ai_image"})
    schema = p.build_settings_schema()

    fields = [
        item
        for section in schema["sections"]
        for item in section["items"]
        if item.get("kind") == "field"
    ]

    assert any(item.get("name") == SAFE_REWRITE_SETTING for item in fields)


def test_ai_image_prompt_renders_as_textarea(client: Any) -> None:
    """Settings page should render the prompt as a <textarea> (JTN-377)."""
    resp = client.get("/plugin/ai_image")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "<textarea" in body
    assert 'name="textPrompt"' in body
    assert "Surprise me" in body
    assert "data-ai-image-random-prompt" in body


def test_ai_image_random_prompt_endpoint_openai(client: Any, monkeypatch: Any) -> None:
    from plugins.ai_image.ai_image import AIImage

    monkeypatch.setenv("OPEN_AI_SECRET", "test")

    with patch.object(AIImage, "fetch_image_prompt", return_value="a glass city"):
        resp = client.post(
            "/plugin/ai_image/random_prompt",
            json={"provider": "openai", "prompt": ""},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["prompt"] == "a glass city"


def test_ai_image_random_prompt_endpoint_missing_key(
    client: Any, monkeypatch: Any
) -> None:
    monkeypatch.delenv("OPEN_AI_SECRET", raising=False)

    resp = client.post(
        "/plugin/ai_image/random_prompt",
        json={"provider": "openai", "prompt": ""},
    )

    assert resp.status_code == 400
    assert "OpenAI API Key" in resp.get_json()["error"]


def test_ai_image_random_prompt_endpoint_rejects_unknown_provider(client: Any) -> None:
    resp = client.post(
        "/plugin/ai_image/random_prompt",
        json={"provider": "opneai", "prompt": ""},
    )

    assert resp.status_code == 400
    body = resp.get_json()
    assert "Unsupported provider" in body["error"]
    assert body["details"]["field"] == "provider"


def test_fetch_image_prompt_api_error_handling():
    """Empty/malformed API responses should return ``""`` so callers fall back."""
    from plugins.ai_image.ai_image import AIImage

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = []
    mock_client.chat.completions.create.return_value = mock_response

    assert AIImage.fetch_image_prompt(mock_client, "a cat") == ""

    # None content (e.g. reasoning models that route output elsewhere)
    null_choice = MagicMock()
    null_choice.message.content = None
    mock_response_null = MagicMock()
    mock_response_null.choices = [null_choice]
    mock_client.chat.completions.create.return_value = mock_response_null
    assert AIImage.fetch_image_prompt(mock_client, "a cat") == ""


def test_ai_image_randomize_falls_back_when_remix_fails(device_config_dev, monkeypatch):
    """If prompt remix raises, image generation should still succeed with the
    user's original prompt rather than aborting the whole flow."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    with (
        patch("plugins.ai_image.ai_image.OpenAI") as mock_openai,
        patch(
            "plugins.ai_image.ai_image.AIImage.fetch_image_prompt",
            side_effect=Exception("remix boom"),
        ),
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        img = PILImage.new("RGB", (64, 64), "black")
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        mock_response = MagicMock()
        mock_response.data = [MagicMock()]
        mock_response.data[0].b64_json = img_b64
        mock_client.images.generate.return_value = mock_response

        settings = {
            "textPrompt": "a calm forest at dusk",
            "imageModel": "gpt-image-2",
            "quality": "medium",
            "randomizePrompt": "true",
        }

        result = p.generate_image(settings, device_config_dev)
        assert result is not None

        prompt_arg = mock_client.images.generate.call_args[1]["prompt"]
        assert prompt_arg.startswith("a calm forest at dusk")


def test_fetch_image_prompt_content_parsing():
    """Test fetch_image_prompt with various content formats."""
    from plugins.ai_image.ai_image import AIImage

    test_cases = [
        ("  Some prompt  ", "Some prompt"),
        ("Prompt with\nnewlines", "Prompt with\nnewlines"),
        ("", ""),
        ("   ", ""),
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


def test_ai_image_openai_raises_when_decode_returns_none(
    device_config_dev, monkeypatch
):
    """If the image loader fails to decode bytes from OpenAI, raise an error."""
    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    with patch("plugins.ai_image.ai_image.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_image_response = MagicMock()
        mock_image_response.data = [MagicMock()]
        mock_image_response.data[0].b64_json = base64.b64encode(b"junk").decode()
        mock_client.images.generate.return_value = mock_image_response

        # from_bytesio returns None when decoding fails
        with patch.object(p.image_loader, "from_bytesio", return_value=None):
            with pytest.raises(RuntimeError, match="(Failed to decode|API request)"):
                p.generate_image(
                    {
                        "textPrompt": "a cat",
                        "imageModel": "gpt-image-1.5",
                        "quality": "medium",
                    },
                    device_config_dev,
                )


def test_ai_image_google_raises_when_decode_returns_none(
    device_config_dev, monkeypatch
):
    """If the image loader fails to decode bytes from Google Imagen, raise an error."""
    import sys

    from plugins.ai_image.ai_image import AIImage

    p = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    # Build fake google.genai module hierarchy
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai

    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    mock_response = MagicMock()
    mock_generated = MagicMock()
    mock_generated.image.image_bytes = b"junk-bytes"
    mock_response.generated_images = [mock_generated]
    mock_client.models.generate_images.return_value = mock_response

    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", mock_genai.types)

    # from_bytesio returns None when decoding fails
    with patch.object(p.image_loader, "from_bytesio", return_value=None):
        with pytest.raises(RuntimeError, match="(Failed to decode|API request)"):
            p.generate_image(
                {
                    "textPrompt": "a cat",
                    "provider": "google",
                    "imageModel": "imagen-4.0-generate-001",
                    "quality": "standard",
                },
                device_config_dev,
            )


# ---------------------------------------------------------------------------
# Coverage for the remix-prompt fallback branches. PR #590 hardened these so
# a broken prompt-rewriter cannot tank the whole image-generation flow; the
# tests below lock in every branch (success, exception, empty string) for
# both providers so regressions show up immediately in pytest, not as a
# silently degraded UI.
# ---------------------------------------------------------------------------


def _google_modules(monkeypatch, mock_client):
    """Stub the google.genai module tree for tests that use the Google path."""
    import sys

    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    mock_genai.Client.return_value = mock_client
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", mock_genai.types)
    return mock_genai


def _make_b64_image() -> str:
    img = PILImage.new("RGB", (64, 64), "green")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_maybe_randomize_openai_prompt_uses_original_when_empty(monkeypatch):
    """Empty remix output must fall back to the user's prompt."""
    from plugins.ai_image.ai_image import AIImage

    plugin = AIImage({"id": "ai_image"})
    with patch(
        "plugins.ai_image.ai_image.AIImage.fetch_image_prompt", return_value="   "
    ):
        assert (
            plugin._maybe_randomize_openai_prompt(MagicMock(), "keep me", True)
            == "keep me"
        )


def test_openai_blank_random_prompt_uses_fallback_before_image_call(
    device_config_dev: Any, monkeypatch: Any
) -> None:
    from plugins.ai_image.ai_image import FALLBACK_IMAGE_PROMPT, AIImage

    plugin = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    with (
        patch(
            "plugins.ai_image.ai_image.AIImage.fetch_image_prompt",
            return_value="",
        ),
        patch.object(plugin, "fetch_image", return_value=MagicMock()) as mock_fetch,
    ):
        plugin.generate_image(
            {
                "textPrompt": "",
                "provider": "openai",
                "imageModel": "gpt-image-2",
                "quality": "medium",
                "randomizePrompt": "true",
            },
            device_config_dev,
        )

    assert mock_fetch.call_args.args[1] == FALLBACK_IMAGE_PROMPT


def test_maybe_randomize_google_prompt_success(monkeypatch):
    """Success path: remixed text replaces the prompt."""
    from plugins.ai_image.ai_image import AIImage

    plugin = AIImage({"id": "ai_image"})
    with patch(
        "plugins.ai_image.ai_image.AIImage.fetch_image_prompt_google",
        return_value="remixed gemini",
    ):
        assert (
            plugin._maybe_randomize_google_prompt(MagicMock(), "orig", True)
            == "remixed gemini"
        )


def test_maybe_randomize_google_prompt_falls_back_on_exception():
    """Exception in Gemini remix must fall back to the user's prompt."""
    from plugins.ai_image.ai_image import AIImage

    plugin = AIImage({"id": "ai_image"})
    with patch(
        "plugins.ai_image.ai_image.AIImage.fetch_image_prompt_google",
        side_effect=Exception("gemini boom"),
    ):
        assert (
            plugin._maybe_randomize_google_prompt(MagicMock(), "stay calm", True)
            == "stay calm"
        )


def test_maybe_randomize_google_prompt_falls_back_on_empty():
    """Empty Gemini remix output must fall back to the user's prompt."""
    from plugins.ai_image.ai_image import AIImage

    plugin = AIImage({"id": "ai_image"})
    with patch(
        "plugins.ai_image.ai_image.AIImage.fetch_image_prompt_google", return_value=""
    ):
        assert (
            plugin._maybe_randomize_google_prompt(MagicMock(), "orig", True) == "orig"
        )


def test_maybe_randomize_disabled_returns_original():
    """When the checkbox is off, neither path should call the remixer."""
    from plugins.ai_image.ai_image import AIImage

    plugin = AIImage({"id": "ai_image"})
    with patch(
        "plugins.ai_image.ai_image.AIImage.fetch_image_prompt"
    ) as mock_openai_fetch:
        assert (
            plugin._maybe_randomize_openai_prompt(MagicMock(), "stay", False) == "stay"
        )
        mock_openai_fetch.assert_not_called()

    with patch(
        "plugins.ai_image.ai_image.AIImage.fetch_image_prompt_google"
    ) as mock_google_fetch:
        assert (
            plugin._maybe_randomize_google_prompt(MagicMock(), "stay", False) == "stay"
        )
        mock_google_fetch.assert_not_called()


def test_fetch_image_prompt_google_empty_text_returns_empty(monkeypatch):
    """fetch_image_prompt_google should return '' (not crash) on empty/None text."""
    from plugins.ai_image.ai_image import AIImage

    mock_client = MagicMock()
    _google_modules(monkeypatch, mock_client)

    # None response.text → ""
    mock_resp_none = MagicMock()
    mock_resp_none.text = None
    mock_client.models.generate_content.return_value = mock_resp_none
    assert AIImage.fetch_image_prompt_google(mock_client, "seed") == ""

    # Whitespace-only response.text → ""
    mock_resp_blank = MagicMock()
    mock_resp_blank.text = "   \n  "
    mock_client.models.generate_content.return_value = mock_resp_blank
    assert AIImage.fetch_image_prompt_google(mock_client, "seed") == ""


def test_ai_image_schema_exposes_gpt_image_2_and_quality_presets():
    """build_settings_schema should wire up the GPT Image 2 model + quality
    options added in PR #590. Traversing the schema here also gives coverage
    credit for the option(...) lines that land inside nested dict literals."""
    from plugins.ai_image.ai_image import AIImage

    plugin = AIImage({"id": "ai_image"})
    schema = plugin.build_settings_schema()

    # Collect every field by name across all sections.
    fields = {}
    for section in schema["sections"]:
        for item in section["items"]:
            if item.get("kind") == "row":
                for sub in item["items"]:
                    if sub.get("kind") == "field":
                        fields[sub["name"]] = sub
            elif item.get("kind") == "field":
                fields[item["name"]] = item

    model_options = fields["imageModel"]["options_by_value"]["openai"]
    model_values = [o["value"] for o in model_options]
    assert "gpt-image-2" in model_values
    assert "gpt-image-1.5" in model_values
    # GPT Image 2 should be listed first (recommended/default).
    assert model_values[0] == "gpt-image-2"

    quality_by_model = fields["quality"]["options_by_value"]
    assert "gpt-image-2" in quality_by_model
    gpt2_qualities = [o["value"] for o in quality_by_model["gpt-image-2"]]
    assert set(gpt2_qualities) == {"high", "medium", "low"}


def test_ai_image_google_randomize_end_to_end_falls_back(
    device_config_dev, monkeypatch
):
    """End-to-end: Google provider + randomize + remix failure → generation
    still succeeds using the original prompt (matches the OpenAI parity test
    just above but exercises the Gemini branch)."""
    from plugins.ai_image.ai_image import AIImage

    plugin = AIImage({"id": "ai_image"})
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    mock_client = MagicMock()
    _google_modules(monkeypatch, mock_client)

    # Remix blows up; image generation succeeds.
    with patch(
        "plugins.ai_image.ai_image.AIImage.fetch_image_prompt_google",
        side_effect=Exception("gemini boom"),
    ):
        mock_generated = MagicMock()
        mock_generated.image.image_bytes = _make_b64_image()
        mock_response = MagicMock()
        mock_response.generated_images = [mock_generated]
        mock_client.models.generate_images.return_value = mock_response

        result = plugin.generate_image(
            {
                "textPrompt": "a quiet library",
                "provider": "google",
                "imageModel": "imagen-4.0-generate-001",
                "quality": "standard",
                "randomizePrompt": "true",
            },
            device_config_dev,
        )
        assert result is not None
        # Prompt passed to Imagen should still begin with the user's original.
        prompt_arg = mock_client.models.generate_images.call_args[1]["prompt"]
        assert prompt_arg.startswith("a quiet library")
